"""Sync backends for alibuild."""

import glob
import hashlib
import json
import os
from datetime import datetime, timezone
import os.path
import re
import sys
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.exceptions import RequestException
from urllib.parse import quote

from alibuild_helpers.cmd import execute
from alibuild_helpers.log import debug, info, error, dieOnError, ProgressPrint
from alibuild_helpers.utilities import resolve_store_path, resolve_links_path, symlink
from alibuild_helpers.utilities import resolve_cas_path, resolve_ac_path, file_digest


def remote_from_url(read_url, write_url, architecture, work_dir, insecure=False,
                    ac_url="", ac_write_url="", storage="ephemeral"):
  """Parse remote store URLs and return the correct RemoteSync instance for them."""
  if read_url.startswith("http"):
    return HttpRemoteSync(read_url, architecture, work_dir, insecure)
  if read_url.startswith("s3://"):
    return S3RemoteSync(read_url, write_url, architecture, work_dir)
  if read_url.startswith("reapi://"):
    return REAPIRemoteSync(read_url, write_url, architecture, work_dir, insecure,
                           ac_url, ac_write_url, storage)
  if read_url.startswith("b3://"):
    return Boto3RemoteSync(read_url, write_url, architecture, work_dir)
  if read_url.startswith("cvmfs://"):
    return CVMFSRemoteSync(read_url, None, architecture, work_dir)
  if read_url:
    return RsyncRemoteSync(read_url, write_url, architecture, work_dir)
  return NoRemoteSync()


class NoRemoteSync:
  """Helper class which does not do anything to sync"""
  def fetch_symlinks(self, spec) -> None:
    pass
  def fetch_tarball(self, spec) -> None:
    pass
  def upload_symlinks_and_tarball(self, spec) -> None:
    pass

class PartialDownloadError(Exception):
  def __init__(self, downloaded, size) -> None:
    self.downloaded = downloaded
    self.size = size
  def __str__(self):
    return "only %d out of %d bytes downloaded" % (self.downloaded, self.size)


class HttpRemoteSync:
  def __init__(self, remoteStore, architecture, workdir, insecure) -> None:
    self.remoteStore = remoteStore
    self.writeStore = ""
    self.architecture = architecture
    self.workdir = workdir
    self.insecure = insecure
    self.httpTimeoutSec = 15
    self.httpConnRetries = 4
    self.httpBackoff = 0.4

  def getRetry(self, url, dest=None, returnResult=False, log=True, session=None, progress=debug):
    get = session.get if session is not None else requests.get
    url = quote(url, safe=":/")
    for i in range(0, self.httpConnRetries):
      if i > 0:
        pauseSec = self.httpBackoff * (2 ** (i - 1))
        debug("GET %s failed: retrying in %.2f", url, pauseSec)
        time.sleep(pauseSec)
        # If the download has failed, enable debug output, even if it was
        # disabled before. We disable debug output for e.g. symlink downloads
        # to make sure the output log isn't overwhelmed. If the download
        # failed, we want to know about it, though. Note that aliBuild has to
        # be called with --debug for this to take effect.
        log = True
      try:
        if log:
          debug("GET %s: processing (attempt %d/%d)", url, i+1, self.httpConnRetries)
        if dest or returnResult:
          # Destination specified -- file (dest) or buffer (returnResult).
          # Use requests in stream mode
          resp = get(url, stream=True, verify=not self.insecure, timeout=self.httpTimeoutSec)
          size = int(resp.headers.get("content-length", "-1"))
          downloaded = 0
          reportTime = time.time()
          result = []

          try:
            destFp = open(dest+".tmp", "wb") if dest else None
            for chunk in filter(bool, resp.iter_content(chunk_size=32768)):
              if destFp:
                destFp.write(chunk)
              if returnResult:
                result.append(chunk)
              downloaded += len(chunk)
              if log and size != -1:
                now = time.time()
                if downloaded == size:
                  progress("[100%%] Download complete")
                elif now - reportTime > 1:
                  progress("[%.0f%%] downloaded...", 100 * downloaded / size)
                  reportTime = now
          finally:
            if destFp:
              destFp.close()

          if size not in (downloaded, -1):
            raise PartialDownloadError(downloaded, size)
          if dest:
            os.rename(dest+".tmp", dest)  # we should not have errors here
          return b''.join(result) if returnResult else True
        else:
          # For CERN S3 we need to construct the JSON ourself...
          s3Request = re.match("https://s3.cern.ch/swift/v1[/]+([^/]*)/(.*)$", url)
          if s3Request:
            [bucket, prefix] = s3Request.groups()
            url = "https://s3.cern.ch/swift/v1/{}/?prefix={}".format(bucket, prefix.lstrip("/"))
            resp = get(url, verify=not self.insecure, timeout=self.httpTimeoutSec)
            if resp.status_code == 404:
              # No need to retry any further
              return None
            resp.raise_for_status()
            return [{"name": os.path.basename(x), "type": "file"}
                    for x in resp.text.split()]
          else:
            # No destination specified: JSON request
            resp = get(url, verify=not self.insecure, timeout=self.httpTimeoutSec)
            if resp.status_code == 404:
              # No need to retry any further
              return None
            resp.raise_for_status()
            return resp.json()
      except (RequestException,ValueError,PartialDownloadError) as e:
        if i == self.httpConnRetries-1:
          error("GET %s failed: %s", url, e)
        if dest:
          try:
            os.unlink(dest+".tmp")
          except Exception:
            pass
    return None

  def fetch_tarball(self, spec) -> None:
    # Check for any existing tarballs we can use instead of fetching new ones.
    for pkg_hash in spec["remote_hashes"]:
      try:
        have_tarballs = os.listdir(os.path.join(
          self.workdir, resolve_store_path(self.architecture, pkg_hash)))
      except OSError:  # store path not readable
        continue
      for tarball in have_tarballs:
        if re.match(r"^{package}-{version}-[0-9]+\.{arch}\.tar\.gz$".format(
            package=re.escape(spec["package"]),
            version=re.escape(spec["version"]),
            arch=re.escape(self.architecture),
        ), os.path.basename(tarball)):
          debug("Previously downloaded tarball for %s with hash %s, reusing",
                spec["package"], pkg_hash)
          return

    with requests.Session() as session:
      debug("Updating remote store for package %s; trying hashes %s",
            spec["package"], ", ".join(spec["remote_hashes"]))
      store_path = use_tarball = None
      # Find the first tarball that matches any possible hash and fetch it.
      for pkg_hash in spec["remote_hashes"]:
        store_path = resolve_store_path(self.architecture, pkg_hash)
        tarballs = self.getRetry(f"{self.remoteStore}/{store_path}/",
                                 session=session)
        if tarballs:
          use_tarball = tarballs[0]["name"]
          break

      if store_path is None or use_tarball is None:
        debug("Nothing fetched for %s (%s)", spec["package"],
              ", ".join(spec["remote_hashes"]))
        return

      os.makedirs(os.path.join(self.workdir, store_path), exist_ok=True)

      destPath = os.path.join(self.workdir, store_path, use_tarball)
      if not os.path.isfile(destPath):   # do not download twice
        progress = ProgressPrint("Downloading tarball for %s@%s" %
                                 (spec["package"], spec["version"]), min_interval=5.0)
        progress("[0%%] Starting download of %s", use_tarball)  # initialise progress bar
        self.getRetry("/".join((self.remoteStore, store_path, use_tarball)),
                      destPath, session=session, progress=progress)
        progress.end("done")

  def fetch_symlinks(self, spec) -> None:
    links_path = resolve_links_path(self.architecture, spec["package"])
    os.makedirs(os.path.join(self.workdir, links_path), exist_ok=True)

    # If we already have a symlink we can use, don't update the list. This
    # speeds up rebuilds significantly.
    if any(f"/{pkg_hash[:2]}/{pkg_hash}/" in target
           for target in (os.readlink(os.path.join(self.workdir, links_path, link))
                          for link in os.listdir(os.path.join(self.workdir, links_path)))
           for pkg_hash in spec["remote_hashes"]):
      debug("Found symlink for %s@%s, not updating", spec["package"], spec["version"])
      return

    with requests.Session() as session:
      # Fetch manifest file with initial symlinks. This file is updated
      # regularly; we use it to avoid many small network requests.
      manifest = self.getRetry(f"{self.remoteStore}/{links_path}.manifest",
                               returnResult=True, session=session)
      symlinks = {
        linkname.decode("utf-8"): target.decode("utf-8")
        for linkname, sep, target in (line.partition(b"\t")
                                      for line in manifest.splitlines())
        if sep and linkname and target
      }
      # Now add any remaining symlinks that aren't in the manifest yet. There
      # should always be relatively few of these, as the separate network
      # requests are a bit expensive.
      for link in self.getRetry(f"{self.remoteStore}/{links_path}/",
                                session=session):
        linkname = link["name"]
        if linkname in symlinks:
          # This symlink is already present in the manifest.
          continue
        if os.path.islink(os.path.join(self.workdir, links_path, linkname)):
          # We have this symlink locally. With local revisions, we won't produce
          # revisions that will conflict with remote revisions unless we upload
          # them anyway, so there's no need to redownload.
          continue
        # This symlink isn't in the manifest yet, and we don't have it locally,
        # so download it individually.
        symlinks[linkname] = \
            self.getRetry("/".join((self.remoteStore, links_path, linkname)),
                          returnResult=True, log=False, session=session) \
                .decode("utf-8").rstrip("\r\n")
    for linkname, target in symlinks.items():
      symlink("../../" + target.lstrip("./"),
              os.path.join(self.workdir, links_path, linkname))

  def upload_symlinks_and_tarball(self, spec) -> None:
    pass


class RsyncRemoteSync:
  """Helper class to sync package build directory using RSync."""

  def __init__(self, remoteStore, writeStore, architecture, workdir) -> None:
    self.remoteStore = re.sub("^ssh://", "", remoteStore)
    self.writeStore = re.sub("^ssh://", "", writeStore)
    self.architecture = architecture
    self.workdir = workdir

  def fetch_tarball(self, spec) -> None:
    info("Downloading tarball for %s@%s, if available", spec["package"], spec["version"])
    debug("Updating remote store for package %s with hashes %s", spec["package"],
          ", ".join(spec["remote_hashes"]))
    err = execute("""\
    for storePath in {storePaths}; do
      # Only get the first matching tarball. If there are multiple with the
      # same hash, we only need one and they should be interchangeable.
      if tars=$(rsync -s --list-only "{remoteStore}/$storePath/{pkg}-{ver}-*.{arch}.tar.gz" 2>/dev/null) &&
         # Strip away the metadata in rsync's file listing, leaving only the first filename.
         tar=$(echo "$tars" | sed -rn '1s#[- a-z0-9,/]* [0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}} ##p') &&
         mkdir -p "{workDir}/$storePath" &&
         # If we already have a file with the same name, assume it's up to date
         # with the remote. In reality, we'll have unpacked, relocated and
         # repacked the tarball from the remote, so the file differs, but
         # there's no point in downloading the one from the remote again.
         rsync -vW --ignore-existing "{remoteStore}/$storePath/$tar" "{workDir}/$storePath/"
      then
        break
      fi
    done
    """.format(pkg=spec["package"], ver=spec["version"], arch=self.architecture,
               remoteStore=self.remoteStore,
               workDir=self.workdir,
               storePaths=" ".join(resolve_store_path(self.architecture, pkg_hash)
                                   for pkg_hash in spec["remote_hashes"])))
    dieOnError(err, "Unable to fetch tarball from specified store.")

  def fetch_symlinks(self, spec) -> None:
    links_path = resolve_links_path(self.architecture, spec["package"])
    os.makedirs(os.path.join(self.workdir, links_path), exist_ok=True)
    err = execute("rsync -rlvW --delete {remote_store}/{links_path}/ {workdir}/{links_path}/".format(
      remote_store=self.remoteStore,
      links_path=links_path,
      workdir=self.workdir,
    ))
    dieOnError(err, "Unable to fetch symlinks from specified store.")

  def upload_symlinks_and_tarball(self, spec) -> None:
    if not self.writeStore:
      return
    dieOnError(execute("""\
    set -e
    cd {workdir}
    tarball={package}-{version}-{revision}.{arch}.tar.gz
    rsync -avR --ignore-existing "{links_path}/$tarball" {remote}/
    for link_dir in dist dist-direct dist-runtime; do
      rsync -avR --ignore-existing "TARS/{arch}/$link_dir/{package}/{package}-{version}-{revision}/" {remote}/
    done
    rsync -avR --ignore-existing "{store_path}/$tarball" {remote}/
    """.format(
      workdir=self.workdir,
      remote=self.remoteStore,
      store_path=resolve_store_path(self.architecture, spec["hash"]),
      links_path=resolve_links_path(self.architecture, spec["package"]),
      arch=self.architecture,
      package=spec["package"],
      version=spec["version"],
      revision=spec["revision"],
    )), "Unable to upload tarball.")

class CVMFSRemoteSync:
  """ Sync packages build directory from CVMFS or similar
      FS based deployment. The tarball will be created on the fly with a single
      symlink to the remote store in it, so that unpacking really
      means unpacking the symlink to the wanted package.
  """

  def __init__(self, remoteStore, writeStore, architecture, workdir) -> None:
    self.remoteStore = re.sub("^cvmfs://", "", remoteStore)
    # We do not support uploading directly to CVMFS, for obvious
    # reasons.
    assert(writeStore is None)
    self.writeStore = None
    self.architecture = architecture
    self.workdir = workdir

  def fetch_tarball(self, spec) -> None:
    info("Downloading tarball for %s@%s-%s, if available", spec["package"], spec["version"], spec["revision"])
    # If we already have a tarball with any equivalent hash, don't check S3.
    for pkg_hash in spec["remote_hashes"] + spec["local_hashes"]:
      store_path = resolve_store_path(self.architecture, pkg_hash)
      pattern = os.path.join(self.workdir, store_path, "%s-*.tar.gz" % spec["package"])
      if glob.glob(pattern):
        info("Reusing existing tarball for %s@%s", spec["package"], pkg_hash)
        return
    info("Could not find prebuilt tarball for %s@%s-%s, will be rebuilt",
         spec["package"], spec["version"], spec["revision"])

  def fetch_symlinks(self, spec) -> None:
    # When using CVMFS, we create the symlinks grass by reading the .
    info("Fetching available build hashes for %s, from %s", spec["package"], self.remoteStore)
    links_path = resolve_links_path(self.architecture, spec["package"])
    os.makedirs(os.path.join(self.workdir, links_path), exist_ok=True)

    cvmfs_architecture = re.sub(r"slc(\d+)_x86-64", r"el\1-x86_64", self.architecture)
    err = execute("""\
    set -x
    # Exit without error in case we do not have any package published
    test -d "{remote_store}/{cvmfs_architecture}/Packages/{package}" || exit 0
    mkdir -p "{workDir}/{links_path}"
    for install_path in $(find "{remote_store}/{cvmfs_architecture}/Packages/{package}" -mindepth 1 -maxdepth 1 -type d); do
      full_version="${{install_path##*/}}"
      tarball={package}-$full_version.{architecture}.tar.gz
      pkg_hash=$(cat "${{install_path}}/.build-hash" || jq -r '.package.hash' <${{install_path}}/.meta.json)
      if [ "X$pkg_hash" = X ]; then
        continue
      fi
      ln -sf ../../{architecture}/store/${{pkg_hash:0:2}}/$pkg_hash/$tarball "{workDir}/{links_path}/$tarball"
      # Create the dummy tarball, if it does not exists
      test -f "{workDir}/{architecture}/store/${{pkg_hash:0:2}}/$pkg_hash/$tarball" && continue
      mkdir -p "{workDir}/INSTALLROOT/$pkg_hash/{architecture}/{package}"
      find "{remote_store}/{cvmfs_architecture}/Packages/{package}/$full_version" -mindepth 1 -maxdepth 1 ! -name etc -exec ln -sf {{}} "{workDir}/INSTALLROOT/$pkg_hash/{architecture}/{package}/" \\;
      cp -fr "{remote_store}/{cvmfs_architecture}/Packages/{package}/$full_version/etc" "{workDir}/INSTALLROOT/$pkg_hash/{architecture}/{package}/etc"
      mkdir -p "{workDir}/TARS/{architecture}/store/${{pkg_hash:0:2}}/$pkg_hash"
      tar -C "{workDir}/INSTALLROOT/$pkg_hash" -czf "{workDir}/TARS/{architecture}/store/${{pkg_hash:0:2}}/$pkg_hash/$tarball" .
      rm -rf "{workDir}/INSTALLROOT/$pkg_hash"
    done
    """.format(
      workDir=self.workdir,
      architecture=self.architecture,
      cvmfs_architecture=cvmfs_architecture,
      package=spec["package"],
      remote_store=self.remoteStore,
      links_path=links_path,
    ))

  def upload_symlinks_and_tarball(self, spec) -> None:
    dieOnError(True, "CVMFS backend does not support uploading directly")

class S3RemoteSync:
  """Sync package build directory from and to S3 using s3cmd.

  s3cmd must be installed separately in order for this to work.
  """

  def __init__(self, remoteStore, writeStore, architecture, workdir) -> None:
    self.remoteStore = re.sub("^s3://", "", remoteStore)
    self.writeStore = re.sub("^s3://", "", writeStore)
    self.architecture = architecture
    self.workdir = workdir

  def fetch_tarball(self, spec) -> None:
    info("Downloading tarball for %s@%s, if available", spec["package"], spec["version"])
    debug("Updating remote store for package %s with hashes %s",
          spec["package"], ", ".join(spec["remote_hashes"]))
    err = execute("""\
    for storePath in {storePaths}; do
      # For the first store path that contains tarballs, fetch them, and skip
      # any possible later tarballs (we only need one).
      if [ -n "$(s3cmd ls -s -v --host s3.cern.ch --host-bucket {b}.s3.cern.ch \
                       "s3://{b}/$storePath/")" ]; then
        s3cmd --no-check-md5 sync -s -v --host s3.cern.ch --host-bucket {b}.s3.cern.ch \
              "s3://{b}/$storePath/" "{workDir}/$storePath/" 2>&1 || :
        break
      fi
    done
    """.format(
      workDir=self.workdir,
      b=self.remoteStore,
      storePaths=" ".join(resolve_store_path(self.architecture, pkg_hash)
                          for pkg_hash in spec["remote_hashes"]),
    ))
    dieOnError(err, "Unable to fetch tarball from specified store.")

  def fetch_symlinks(self, spec) -> None:
    err = execute("""\
    mkdir -p "{workDir}/{linksPath}"
    find "{workDir}/{linksPath}" -type l -delete
    curl -sL "https://s3.cern.ch/swift/v1/{b}/{linksPath}.manifest" |
      while IFS='\t' read -r symlink target; do
        ln -sf "../../${{target#../../}}" "{workDir}/{linksPath}/$symlink" || true
      done
    for x in $(curl -sL "https://s3.cern.ch/swift/v1/{b}/?prefix={linksPath}/"); do
      # Skip already existing symlinks -- these were from the manifest.
      # (We delete leftover symlinks from previous runs above.)
      [ -L "{workDir}/{linksPath}/$(basename "$x")" ] && continue
      ln -sf "$(curl -sL "https://s3.cern.ch/swift/v1/{b}/$x" | sed -r 's,^(\\.\\./\\.\\./)?,../../,')" \
         "{workDir}/{linksPath}/$(basename "$x")" || true
    done
    """.format(
      b=self.remoteStore,
      linksPath=resolve_links_path(self.architecture, spec["package"]),
      workDir=self.workdir,
    ))
    dieOnError(err, "Unable to fetch symlinks from specified store.")

  def upload_symlinks_and_tarball(self, spec) -> None:
    if not self.writeStore:
      return
    dieOnError(execute("""\
    set -e
    put () {{
      s3cmd put -s -v --host s3.cern.ch --host-bucket {bucket}.s3.cern.ch "$@" 2>&1
    }}
    tarball={package}-{version}-{revision}.{arch}.tar.gz
    cd {workdir}

    # First, upload "main" symlink, to reserve this revision number, in case
    # the below steps fail.
    readlink "{links_path}/$tarball" | sed 's|^\\.\\./\\.\\./||' |
      put - "s3://{bucket}/{links_path}/$tarball"

    # Then, upload dist symlink trees -- these must be in place before the main
    # tarball.
    find TARS/{arch}/{{dist,dist-direct,dist-runtime}}/{package}/{package}-{version}-{revision}/ \
         -type l | while read -r link; do
      hashedurl=$(readlink "$link" | sed 's|.*/\\.\\./TARS|TARS|')
      echo "$hashedurl" |
        put --skip-existing -q -P \\
            --add-header="x-amz-website-redirect-location:\
https://s3.cern.ch/swift/v1/{bucket}/$hashedurl" \\
            - "s3://{bucket}/$link" 2>&1
    done

    # Finally, upload the tarball.
    put "{store_path}/$tarball" s3://{bucket}/{store_path}/
    """.format(
      workdir=self.workdir,
      bucket=self.remoteStore,
      store_path=resolve_store_path(self.architecture, spec["hash"]),
      links_path=resolve_links_path(self.architecture, spec["package"]),
      arch=self.architecture,
      package=spec["package"],
      version=spec["version"],
      revision=spec["revision"],
    )), "Unable to upload tarball.")


class Boto3RemoteSync:
  """Sync package build directory from and to S3 using boto3.

  As boto3 doesn't support Python 2, this class can only be used under Python
  3. boto3 is only imported at __init__ time, so if this class is never
  instantiated, boto3 doesn't have to be installed.

  This class has the advantage over S3RemoteSync that it uses the same
  connection to S3 every time, while s3cmd must establish a new connection each
  time.
  """

  def __init__(self, remoteStore, writeStore, architecture, workdir) -> None:
    self.remoteStore = re.sub("^b3://", "", remoteStore)
    self.writeStore = re.sub("^b3://", "", writeStore)
    self.architecture = architecture
    self.workdir = workdir
    self.endpoint_url = "https://s3.cern.ch"
    self._s3_init()

  def _s3_init(self) -> None:
    # This is a separate method so that we can patch it out for unit tests.
    # Import boto3 here, so that if we don't use this remote store, we don't
    # have to install it in the first place.
    try:
      import boto3
      from botocore.config import Config
    except ImportError:
      error("boto3 must be installed to use %s", Boto3RemoteSync)
      sys.exit(1)

    try:
      try:
        config = Config(
          request_checksum_calculation='WHEN_REQUIRED',
          response_checksum_validation='WHEN_REQUIRED',
          # Allow room for parallel migrate/build jobs sharing this client.
          max_pool_connections=32,
        )
      except TypeError:
        # Older boto3 versions don't support these parameters (<1.36.0)
        config = Config(max_pool_connections=32)
      self.s3 = boto3.client("s3",
                             **({"config": config} if config else {}),
                             endpoint_url=self.endpoint_url,
                             aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
                             aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"])
    except KeyError:
      error("you must pass the AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY env "
            "variables to aliBuild in order to use the S3 remote store")
      sys.exit(1)

  def _s3_listdir(self, dirname):
    """List keys of items under dirname in the read bucket."""
    pages = self.s3.get_paginator("list_objects_v2") \
                   .paginate(Bucket=self.remoteStore, Delimiter="/",
                             Prefix=dirname.rstrip("/") + "/")
    return (item["Key"] for pg in pages for item in pg.get("Contents", ()))

  def _s3_key_exists(self, key):
    """Return whether the given key exists in the write bucket already."""
    from botocore.exceptions import ClientError
    try:
      self.s3.head_object(Bucket=self.writeStore, Key=key)
    except ClientError as err:
      if err.response["Error"]["Code"] == "404":
        return False
      raise
    return True

  def fetch_tarball(self, spec) -> None:
    debug("Updating remote store for package %s with hashes %s", spec["package"],
          ", ".join(spec["remote_hashes"]))

    # If we already have a tarball with any equivalent hash, don't check S3.
    for pkg_hash in spec["remote_hashes"]:
      store_path = resolve_store_path(self.architecture, pkg_hash)
      if glob.glob(os.path.join(self.workdir, store_path, "%s-*.tar.gz" % spec["package"])):
        debug("Reusing existing tarball for %s@%s", spec["package"], pkg_hash)
        return

    for pkg_hash in spec["remote_hashes"]:
      store_path = resolve_store_path(self.architecture, pkg_hash)

      # We don't already have a tarball with the hash that we need, so download
      # the first existing one from the remote, if possible. (Downloading more
      # than one is a waste of time as they should be equivalent and we only
      # ever use one anyway.)
      for tarball in self._s3_listdir(store_path):
        debug("Fetching tarball %s", tarball)
        progress = ProgressPrint("Downloading tarball for %s@%s" %
                                 (spec["package"], spec["version"]), min_interval=5.0)
        progress("[0%%] Starting download of %s", tarball)   # initialise progress bar
        # Create containing directory locally. (exist_ok= is python3-specific.)
        os.makedirs(os.path.join(self.workdir, store_path), exist_ok=True)
        meta = self.s3.head_object(Bucket=self.remoteStore, Key=tarball)
        total_size = int(meta.get("ContentLength", 0))
        self.s3.download_file(
          Bucket=self.remoteStore, Key=tarball,
          Filename=os.path.join(self.workdir, store_path, os.path.basename(tarball)),
          Callback=lambda num_bytes: progress("[%d/%d] bytes transferred", num_bytes, total_size),
        )
        progress.end("done")
        return

    debug("Remote has no tarballs for %s with hashes %s", spec["package"],
          ", ".join(spec["remote_hashes"]))

  def fetch_symlinks(self, spec) -> None:
    from botocore.exceptions import ClientError
    links_path = resolve_links_path(self.architecture, spec["package"])
    os.makedirs(os.path.join(self.workdir, links_path), exist_ok=True)

    # Remove existing symlinks: we'll fetch the ones from the remote next.
    parent = os.path.join(self.workdir, links_path)
    for fname in os.listdir(parent):
      path = os.path.join(parent, fname)
      if os.path.islink(path):
        os.unlink(path)

    # Fetch symlink manifest and create local symlinks to match.
    debug("Fetching symlink manifest")
    n_symlinks = 0
    try:
      manifest = self.s3.get_object(Bucket=self.remoteStore, Key=links_path + ".manifest")
    except ClientError as exc:
      debug("Could not fetch manifest: %s", exc)
    else:
      for line in manifest["Body"].iter_lines():
        link_name, has_sep, target = line.rstrip(b"\n").partition(b"\t")
        if not has_sep:
          debug("Ignoring malformed line in manifest: %r", line)
          continue
        if not target.startswith(b"../../"):
          target = b"../../" + target
        target = os.fsdecode(target)
        link_path = os.path.join(self.workdir, links_path, os.fsdecode(link_name))
        symlink(target, link_path)
        n_symlinks += 1
      debug("Got %d entries in manifest", n_symlinks)

    # Create remote symlinks that aren't in the manifest yet.
    debug("Looking for symlinks not in manifest")
    for link_key in self._s3_listdir(links_path):
      link_path = os.path.join(self.workdir, link_key)
      if os.path.islink(link_path):
        continue
      debug("Fetching leftover symlink %s", link_key)
      resp = self.s3.get_object(Bucket=self.remoteStore, Key=link_key)
      target = os.fsdecode(resp["Body"].read()).rstrip("\n")
      if not target.startswith("../../"):
        target = "../../" + target
      symlink(target, link_path)

  def upload_symlinks_and_tarball(self, spec) -> None:
    if not self.writeStore:
      return

    dist_symlinks = {}
    for link_dir in ("dist", "dist-direct", "dist-runtime"):
      link_dir = "TARS/{arch}/{link_dir}/{package}/{package}-{version}-{revision}" \
        .format(arch=self.architecture, link_dir=link_dir, **spec)

      debug("Comparing dist symlinks against S3 from %s", link_dir)

      symlinks = []
      for fname in os.listdir(os.path.join(self.workdir, link_dir)):
        link_key = os.path.join(link_dir, fname)
        path = os.path.join(self.workdir, link_key)
        if os.path.islink(path):
          hash_path = re.sub(r"^(\.\./)*", "", os.readlink(path))
          symlinks.append((link_key, hash_path))

      # To make sure there are no conflicts, see if anything already exists in
      # our symlink directory.
      symlinks_existing = frozenset(self._s3_listdir(link_dir))

      # If all the symlinks we would upload already exist, skip uploading. We
      # probably just downloaded a prebuilt package earlier, and it already has
      # symlinks available.
      if all(link_key in symlinks_existing for link_key, _ in symlinks):
        debug("All %s symlinks already exist on S3, skipping upload", link_dir)
        continue

      # Excluding our own symlinks (above), if there is anything in our link_dir
      # on the remote, something else is uploading symlinks (or already has)!
      dieOnError(symlinks_existing,
                 "Conflicts detected in %s on S3; aborting: %s" %
                 (link_dir, ", ".join(sorted(symlinks_existing))))

      dist_symlinks[link_dir] = symlinks

    tarball = "{package}-{version}-{revision}.{architecture}.tar.gz" \
      .format(architecture=self.architecture, **spec)
    tar_path = os.path.join(resolve_store_path(self.architecture, spec["hash"]),
                            tarball)
    link_path = os.path.join(resolve_links_path(self.architecture, spec["package"]),
                             tarball)
    tar_exists = self._s3_key_exists(tar_path)
    link_exists = self._s3_key_exists(link_path)
    if tar_exists and link_exists:
      debug("%s exists on S3 already, not uploading", tarball)
      return
    dieOnError(tar_exists or link_exists,
               "%s already exists on S3 but %s does not, aborting!" %
               (tar_path if tar_exists else link_path,
                link_path if tar_exists else tar_path))

    debug("Uploading tarball and symlinks for %s %s-%s (%s) to S3",
          spec["package"], spec["version"], spec["revision"], spec["hash"])

    # Upload the smaller file first, so that any parallel uploads are more
    # likely to find it and fail.
    self.s3.put_object(Bucket=self.writeStore, Key=link_path,
                       Body=os.readlink(os.path.join(self.workdir, link_path))
                              .lstrip("./").encode("utf-8"))

    # Second, upload dist symlinks. These should be in place before the main
    # tarball, to avoid races in the publisher.
    start_time = time.time()
    total_symlinks = 0

    # Limit concurrency to avoid overwhelming S3 with too many simultaneous requests
    max_workers = min(32, (len(dist_symlinks) * 10) or 1)

    def _upload_single_symlink(link_key, hash_path):
      self.s3.put_object(Bucket=self.writeStore,
                         Key=link_key,
                         Body=os.fsencode(hash_path),
                         ACL="public-read",
                         WebsiteRedirectLocation=hash_path)
      return link_key

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
      future_to_info = {}
      for link_dir, symlinks in dist_symlinks.items():
        for link_key, hash_path in symlinks:
          future = executor.submit(_upload_single_symlink, link_key, hash_path)
          future_to_info[future] = (link_dir, link_key)
          total_symlinks += 1

      dir_counts = {link_dir: 0 for link_dir in dist_symlinks.keys()}
      for future in as_completed(future_to_info):
        link_dir, link_key = future_to_info[future]
        try:
          future.result()
          dir_counts[link_dir] += 1
        except Exception as e:
          error("Failed to upload symlink %s: %s", link_key, e)
          raise

      for link_dir, count in dir_counts.items():
        if count > 0:
          debug("Uploaded %d dist symlinks to S3 from %s", count, link_dir)

    end_time = time.time()
    debug("Uploaded %d dist symlinks in %.2f seconds",
          total_symlinks, end_time - start_time)

    self._upload_tarball(spec, tar_path)

  def _upload_tarball(self, spec, tar_path) -> None:
    """Upload the tarball bytes to the remote store under tar_path.

    Factored out so that REAPIRemoteSync can store the bytes content-addressed
    in a CAS and write an Action Cache entry instead.
    """
    self.s3.upload_file(Bucket=self.writeStore, Key=tar_path,
                        Filename=os.path.join(self.workdir, tar_path))


class REAPIRemoteSync(Boto3RemoteSync):
  """S3 remote store using a REAPI-style Action Cache (AC) + CAS layout.

  Unlike Boto3RemoteSync (scheme ``b3://``), which stores each tarball under its
  *action* hash and hardcodes the CERN endpoint, this backend (scheme
  ``reapi://``):

    * stores the tarball and recipe bytes content-addressed under
      ``cas/<algo>/<h[:2]>/<h>``, so equivalent builds (e.g. tag aliases that
      share a commit) deduplicate to a single blob;
    * writes a small Action Cache entry ``ac/<arch>/<h[:2]>/<h>.json`` recording
      how the tarball was produced (recipe, commit, dependency action hashes,
      build environment), so the CAS can be reconstructed from it;
    * keeps the legacy ``TARS/store`` + symlink + ``.manifest`` layout, with the
      store object as an S3 redirect to the CAS blob, so the existing publisher
      and HttpRemoteSync keep working without duplicating bytes;
    * parameterises the endpoint, so it works against AWS, MinIO, Ceph RGW and
      CERN.

  URL form: ``reapi://<endpoint-host>/<bucket>``. The endpoint scheme defaults
  to https; pass ``insecure=True`` (aliBuild ``--insecure``) to use http, e.g.
  for a local MinIO.

  See REMOTE_STORE_CAS_AC.md for the full design.
  """

  CAS_ALGO = "sha256"
  # Object-tag lifecycle for the artifact store (see the bucket lifecycle rule,
  # ali-marathon/s3/alibuild-cas-lifecycle.xml, and REMOTE_STORE_CAS_AC.md):
  # objects tagged retention=ephemeral expire 90 days after last-modified;
  # untagged / retention=permanent are kept forever.
  RETENTION_TAG_KEY = "retention"
  EPHEMERAL_TTL_DAYS = 90
  REFRESH_WITHIN_DAYS = 30   # touch (LRU-refresh) ephemeral objects within this of expiry

  def __init__(self, remoteStore, writeStore, architecture, workdir,
               insecure=False, acStore="", acWriteStore="", storage="ephemeral") -> None:
    scheme = "http" if insecure else "https"
    read_endpoint, self.remoteStore = self._parse_reapi_url(remoteStore, scheme)
    write_endpoint, self.writeStore = self._parse_reapi_url(writeStore, scheme)
    self.architecture = architecture
    self.workdir = workdir
    # Read and write endpoints are normally the same host; prefer the read one.
    self.endpoint_url = read_endpoint or write_endpoint
    # The artifact store (self.remoteStore/self.writeStore) holds the large,
    # deletable/regenerable output tarballs. The *ledger* store holds the small,
    # keep-forever set: Action Cache entries plus the reconstruction-input blobs
    # (recipe, source, refs). They have different lifetimes, so they can live in
    # different buckets with different retention policies -- deleting the
    # artifact store is then safe, since reconstruct rebuilds it from the ledger.
    # The ledger defaults to the artifact store (single-bucket setups), and must
    # share the endpoint (one S3 client; only the bucket differs).
    ac_read_ep, self.acRemoteStore = (self._parse_reapi_url(acStore, scheme)
                                      if acStore else ("", self.remoteStore))
    ac_write_ep, self.acWriteStore = (self._parse_reapi_url(acWriteStore, scheme)
                                      if acWriteStore else ("", self.writeStore))
    for endpoint in (ac_read_ep, ac_write_ep):
      dieOnError(bool(endpoint) and bool(self.endpoint_url) and
                 endpoint != self.endpoint_url,
                 "the AC/ledger store must share the endpoint with the artifact "
                 "store (%s); a cross-endpoint split is not supported" %
                 self.endpoint_url)
    # Artifact retention: "ephemeral" (default; LRU-expired by the bucket
    # lifecycle) or "permanent" (pinned, and promotes any ephemeral blob it
    # reuses). The ledger store is never tagged -- it is always keep-forever.
    dieOnError(storage not in ("ephemeral", "permanent"),
               "storage must be 'ephemeral' or 'permanent', not %r" % storage)
    self.storage = storage
    self._s3_init()

  @staticmethod
  def _parse_reapi_url(url, scheme):
    """Split ``reapi://<host>/<bucket>`` into ``(endpoint_url, bucket)``."""
    if not url:
      return "", ""
    host, _, bucket = re.sub("^reapi://", "", url).partition("/")
    return "%s://%s" % (scheme, host), bucket.strip("/")

  def _upload_tarball(self, spec, tar_path) -> None:
    """Store the tarball content-addressed in the CAS, write its Action Cache
    entry and the recipe blob, and leave the legacy store object as a redirect
    to the CAS blob."""
    local_tar = os.path.join(self.workdir, tar_path)
    content_hash = file_digest(local_tar, self.CAS_ALGO)
    cas_path = resolve_cas_path(content_hash, self.CAS_ALGO)
    output_digest = "%s:%s" % (self.CAS_ALGO, content_hash)

    # 1. Content-addressed tarball bytes. Skip the upload if an identical blob
    #    already exists -- this is where equivalent action hashes deduplicate --
    #    but promote it if this is a permanent build reusing an ephemeral blob.
    if self._exists(self.writeStore, cas_path):
      self._maybe_promote(cas_path)
      debug("CAS already has %s, not re-uploading bytes", cas_path)
    else:
      self.s3.upload_file(Bucket=self.writeStore, Key=cas_path, Filename=local_tar,
                          ExtraArgs={"Tagging": self._retention_tagging()})

    ac_entry = spec.get("ac_entry")
    if ac_entry:
      # 2. Recipe blob in the *ledger* store (keep-forever reconstruction input).
      recipe_digest = ac_entry["action"]["recipeDigest"].split(":", 1)[-1]
      recipe_cas = resolve_cas_path(recipe_digest, self.CAS_ALGO)
      if not self._exists(self.acWriteStore, recipe_cas):
        # Store the full recipe (header + body); its digest is recipeDigest.
        recipe_text = spec.get("fullRecipe") or spec.get("recipe") or ""
        self.s3.put_object(Bucket=self.acWriteStore, Key=recipe_cas,
                           Body=recipe_text.encode("utf-8", "ignore"))

      # 3. Action Cache entry (ledger store), now that we know the output digest.
      ac_entry = dict(ac_entry, result={
        "tarball": os.path.basename(tar_path),
        "outputDigest": output_digest,
        "size": os.path.getsize(local_tar),
      })
      ac_path = resolve_ac_path(self.architecture, ac_entry["action"]["actionHash"])
      self.s3.put_object(Bucket=self.acWriteStore, Key=ac_path,
                         Body=json.dumps(ac_entry, indent=2, sort_keys=True)
                                .encode("utf-8"),
                         ContentType="application/json")
    else:
      debug("No Action Cache entry for %s; uploaded CAS blob only", tar_path)

    # 4. Legacy store object: a redirect to the CAS blob, so the existing
    #    publisher / HttpRemoteSync resolve it without storing the bytes twice.
    self.s3.put_object(Bucket=self.writeStore, Key=tar_path,
                       Body=os.fsencode(cas_path),
                       WebsiteRedirectLocation="/" + cas_path)

  def _exists(self, bucket, key):
    """Return whether key exists in the given bucket."""
    from botocore.exceptions import ClientError
    debug("S3 head_object %s/%s", bucket, key)
    try:
      self.s3.head_object(Bucket=bucket, Key=key)
    except ClientError:
      return False
    return True

  # --- Ledger store: AC entries + reconstruction-input blobs (recipe/source/
  #     refs). Small, keep-forever; read from acRemoteStore, write acWriteStore.

  def read_ac_entry(self, action_hash):
    """Return the parsed Action Cache entry for action_hash, or None if absent."""
    from botocore.exceptions import ClientError
    ac_path = resolve_ac_path(self.architecture, action_hash)
    debug("S3 get_object %s/%s (read AC)", self.acRemoteStore, ac_path)
    try:
      obj = self.s3.get_object(Bucket=self.acRemoteStore, Key=ac_path)
    except ClientError:
      return None
    return json.loads(obj["Body"].read())

  def download_blob(self, content_hash, dest, algo="sha256"):
    """Download a ledger (input) blob -- e.g. a source bundle -- to dest."""
    self.s3.download_file(Bucket=self.acRemoteStore,
                          Key=resolve_cas_path(content_hash, algo), Filename=dest)

  def read_blob(self, content_hash, algo="sha256"):
    """Return the bytes of a ledger (input) blob -- e.g. a recipe or refs blob."""
    return self.s3.get_object(Bucket=self.acRemoteStore,
                              Key=resolve_cas_path(content_hash, algo))["Body"].read()

  def put_file_as_blob(self, path, algo="sha256"):
    """Upload a ledger (input) blob from a file -- e.g. a source bundle. Dedups.
    Returns the content hash."""
    content_hash = file_digest(path, algo)
    cas_path = resolve_cas_path(content_hash, algo)
    if not self._exists(self.acWriteStore, cas_path):
      self.s3.upload_file(Bucket=self.acWriteStore, Key=cas_path, Filename=path)
    return content_hash

  def put_bytes_as_blob(self, data, algo="sha256"):
    """Upload an in-memory ledger (input) blob -- e.g. a refs blob. Dedups."""
    content_hash = hashlib.new(algo, data).hexdigest()
    cas_path = resolve_cas_path(content_hash, algo)
    if not self._exists(self.acWriteStore, cas_path):
      self.s3.put_object(Bucket=self.acWriteStore, Key=cas_path, Body=data)
    return content_hash

  def read_object_json(self, key):
    """Return the JSON object at key in the ledger store, or None."""
    from botocore.exceptions import ClientError
    try:
      obj = self.s3.get_object(Bucket=self.acRemoteStore, Key=key)
    except ClientError:
      return None
    return json.loads(obj["Body"].read())

  def write_object_json(self, key, obj):
    """Write a small JSON object at key in the ledger store."""
    self.s3.put_object(Bucket=self.acWriteStore, Key=key,
                       Body=json.dumps(obj, sort_keys=True).encode("utf-8"),
                       ContentType="application/json")

  # --- Artifact store: large, deletable/regenerable output tarball blobs;
  #     read from remoteStore, write writeStore.

  def _retention_tagging(self):
    """The retention tag to apply to freshly uploaded artifact blobs."""
    return "%s=%s" % (self.RETENTION_TAG_KEY, self.storage)

  def _retention_of(self, bucket, key):
    """Return the retention tag value of an object, or None if untagged/absent."""
    from botocore.exceptions import ClientError
    try:
      tags = self.s3.get_object_tagging(Bucket=bucket, Key=key)["TagSet"]
    except ClientError:
      return None
    return next((t["Value"] for t in tags if t["Key"] == self.RETENTION_TAG_KEY), None)

  def _maybe_promote(self, cas_path):
    """When uploading as 'permanent' and the blob already exists tagged
    ephemeral, promote it to permanent so it is no longer LRU-expired."""
    if self.storage != "permanent":
      return
    if self._retention_of(self.writeStore, cas_path) == "ephemeral":
      self.s3.put_object_tagging(
        Bucket=self.writeStore, Key=cas_path,
        Tagging={"TagSet": [{"Key": self.RETENTION_TAG_KEY, "Value": "permanent"}]})
      debug("Promoted %s from ephemeral to permanent", cas_path)

  def put_artifact_blob(self, path, algo="sha256"):
    """Upload an output tarball to the artifact CAS keyed by content hash,
    tagged with the current retention. Dedups; promotes on a permanent reuse."""
    content_hash = file_digest(path, algo)
    cas_path = resolve_cas_path(content_hash, algo)
    if self._exists(self.writeStore, cas_path):
      self._maybe_promote(cas_path)
    else:
      debug("S3 upload_file %s/%s (%d bytes)", self.writeStore, cas_path,
            os.path.getsize(path))
      self.s3.upload_file(Bucket=self.writeStore, Key=cas_path, Filename=path,
                          ExtraArgs={"Tagging": self._retention_tagging()})
    return content_hash

  def _touch_if_expiring(self, cas_path):
    """LRU-refresh: if the blob is ephemeral and within REFRESH_WITHIN_DAYS of
    its EPHEMERAL_TTL_DAYS expiry, copy it onto itself (preserving the tag) to
    reset last-modified. Best-effort and only when we can write the same bucket."""
    from botocore.exceptions import ClientError
    if not self.writeStore or self.writeStore != self.remoteStore:
      return
    try:
      if self._retention_of(self.remoteStore, cas_path) != "ephemeral":
        return
      head = self.s3.head_object(Bucket=self.remoteStore, Key=cas_path)
      age_days = (datetime.now(timezone.utc) - head["LastModified"]).days
      if age_days < self.EPHEMERAL_TTL_DAYS - self.REFRESH_WITHIN_DAYS:
        return
      debug("Refreshing ephemeral %s (%d days old)", cas_path, age_days)
      self.s3.copy_object(Bucket=self.writeStore, Key=cas_path,
                          CopySource={"Bucket": self.remoteStore, "Key": cas_path},
                          MetadataDirective="COPY", TaggingDirective="COPY")
    except ClientError as exc:
      debug("Could not refresh %s: %s", cas_path, exc)

  def download_artifact(self, content_hash, dest, algo="sha256"):
    """Download an output tarball blob from the artifact store to dest, LRU-
    refreshing it if it is ephemeral and close to expiry."""
    cas_path = resolve_cas_path(content_hash, algo)
    self._touch_if_expiring(cas_path)
    debug("S3 download_file %s/%s", self.remoteStore, cas_path)
    self.s3.download_file(Bucket=self.remoteStore, Key=cas_path, Filename=dest)

  def artifact_blob_exists(self, content_hash, algo="sha256"):
    """Return whether an output tarball blob exists in the artifact store."""
    return self._exists(self.remoteStore, resolve_cas_path(content_hash, algo))

  def resolve_action_hash(self, package, version, revision=None):
    """Resolve a human label (package, version[, revision]) to an action hash,
    using the per-package symlink objects written at upload time. With no
    revision, the highest available one for the version is chosen. Returns None
    if nothing matches."""
    links_path = resolve_links_path(self.architecture, package)
    name_prefix = "%s-%s-" % (package, version)
    name_suffix = ".%s.tar.gz" % self.architecture
    candidates = []   # (revision, link key)
    for key in self._s3_listdir(links_path):
      name = os.path.basename(key)
      if name.startswith(name_prefix) and name.endswith(name_suffix):
        candidates.append((name[len(name_prefix):-len(name_suffix)], key))
    if revision is not None:
      candidates = [(rev, key) for rev, key in candidates if rev == str(revision)]
    if not candidates:
      return None

    def revision_sort_key(rev_key):
      # Prefer the highest numeric revision; fall back to lexicographic.
      rev = rev_key[0]
      return (1, int(rev)) if rev.isdigit() else (0, rev)

    _, link_key = max(candidates, key=revision_sort_key)
    target = os.fsdecode(self.s3.get_object(Bucket=self.remoteStore,
                                            Key=link_key)["Body"].read())
    match = re.search(r"store/[0-9a-f]{2}/([0-9a-f]+)/", target)
    return match.group(1) if match else None

  def migrate_put(self, ac_entry, tarball_path, recipe_text):
    """Write a migrated legacy release into the reapi store: the tarball as a
    CAS blob, the recovered recipe blob, the Action Cache entry, plus the legacy
    store redirect and per-package link so it stays installable and
    publisher-compatible. Returns the tarball's content hash."""
    action = ac_entry["action"]
    arch, pkg = action["architecture"], action["package"]
    action_hash = action["actionHash"]
    tarball = "{package}-{version}-{revision}.{arch}.tar.gz".format(arch=arch, **action)

    # Tarball -> artifact store; recipe + AC -> ledger store.
    content_hash = self.put_artifact_blob(tarball_path, self.CAS_ALGO)
    cas_path = resolve_cas_path(content_hash, self.CAS_ALGO)

    recipe_digest = action["recipeDigest"].split(":", 1)[-1]
    recipe_cas = resolve_cas_path(recipe_digest, self.CAS_ALGO)
    if not self._exists(self.acWriteStore, recipe_cas):
      debug("S3 put_object %s/%s (recipe)", self.acWriteStore, recipe_cas)
      self.s3.put_object(Bucket=self.acWriteStore, Key=recipe_cas,
                         Body=(recipe_text or "").encode("utf-8", "ignore"))

    entry = dict(ac_entry, result={
      "tarball": tarball,
      "outputDigest": "%s:%s" % (self.CAS_ALGO, content_hash),
      "size": os.path.getsize(tarball_path),
    })
    ac_path = resolve_ac_path(arch, action_hash)
    debug("S3 put_object %s/%s (AC entry)", self.acWriteStore, ac_path)
    self.s3.put_object(Bucket=self.acWriteStore, Key=ac_path,
                       Body=json.dumps(entry, indent=2, sort_keys=True).encode("utf-8"),
                       ContentType="application/json")

    store_key = os.path.join(resolve_store_path(arch, action_hash), tarball)
    debug("S3 put_object %s/%s (store redirect)", self.writeStore, store_key)
    self.s3.put_object(Bucket=self.writeStore, Key=store_key,
                       Body=os.fsencode(cas_path), WebsiteRedirectLocation="/" + cas_path)

    link_target = "../../%s/store/%s/%s/%s" % (arch, action_hash[:2], action_hash, tarball)
    link_key = os.path.join(resolve_links_path(arch, pkg), tarball)
    debug("S3 put_object %s/%s (link)", self.writeStore, link_key)
    self.s3.put_object(Bucket=self.writeStore, Key=link_key,
                       Body=link_target.encode("utf-8"),
                       WebsiteRedirectLocation=link_target)
    return content_hash

  def fetch_tarball(self, spec) -> None:
    """Resolve the tarball via the Action Cache (action hash -> AC entry ->
    output digest -> CAS blob). Falls back to the legacy store layout when no
    AC entry exists, so mixed / migrating stores keep working."""
    from botocore.exceptions import ClientError

    # If we already have a tarball with any equivalent hash, don't hit S3.
    for pkg_hash in spec["remote_hashes"]:
      store_path = resolve_store_path(self.architecture, pkg_hash)
      if glob.glob(os.path.join(self.workdir, store_path, "%s-*.tar.gz" % spec["package"])):
        debug("Reusing existing tarball for %s@%s", spec["package"], pkg_hash)
        return

    for pkg_hash in spec["remote_hashes"]:
      ac_path = resolve_ac_path(self.architecture, pkg_hash)
      try:
        obj = self.s3.get_object(Bucket=self.acRemoteStore, Key=ac_path)
      except ClientError:
        continue
      entry = json.loads(obj["Body"].read())
      result = entry.get("result", {})
      digest = result.get("outputDigest", "")
      if ":" not in digest:
        debug("AC entry %s has no usable output digest", ac_path)
        continue
      algo, _, content_hash = digest.partition(":")
      cas_path = resolve_cas_path(content_hash, algo)
      store_path = resolve_store_path(self.architecture, pkg_hash)
      tarball = result.get("tarball") or \
        "{package}-{version}-{revision}.{arch}.tar.gz".format(arch=self.architecture, **spec)
      dest = os.path.join(self.workdir, store_path, tarball)
      os.makedirs(os.path.join(self.workdir, store_path), exist_ok=True)
      debug("Fetching CAS blob %s for %s@%s", cas_path, spec["package"], pkg_hash)
      progress = ProgressPrint("Downloading tarball for %s@%s" %
                               (spec["package"], spec["version"]), min_interval=5.0)
      progress("[0%%] Starting download of %s", cas_path)
      meta = self.s3.head_object(Bucket=self.remoteStore, Key=cas_path)
      total_size = int(meta.get("ContentLength", 0))
      self.s3.download_file(
        Bucket=self.remoteStore, Key=cas_path, Filename=dest,
        Callback=lambda num_bytes: progress("[%d/%d] bytes transferred", num_bytes, total_size),
      )
      progress.end("done")
      return

    debug("No Action Cache entry for %s with hashes %s; trying legacy store",
          spec["package"], ", ".join(spec["remote_hashes"]))
    super().fetch_tarball(spec)
