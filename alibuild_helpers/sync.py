"""Sync backends for alibuild."""

import glob
import os
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


def remote_from_url(read_url, write_url, architecture, work_dir, insecure=False):
  """Parse remote store URLs and return the correct RemoteSync instance for them."""
  if read_url.startswith("http"):
    return HttpRemoteSync(read_url, architecture, work_dir, insecure)
  if read_url.startswith("s3://"):
    return S3RemoteSync(read_url, write_url, architecture, work_dir)
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
            url = "https://s3.cern.ch/swift/v1/%s/?prefix=%s" % (bucket, prefix.lstrip("/"))
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
          except:
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
        tarballs = self.getRetry("%s/%s/" % (self.remoteStore, store_path),
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
      manifest = self.getRetry("%s/%s.manifest" % (self.remoteStore, links_path),
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
      for link in self.getRetry("%s/%s/" % (self.remoteStore, links_path),
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
    for install_path in $(find "{remote_store}/{cvmfs_architecture}/Packages/{package}" -type d -mindepth 1 -maxdepth 1); do
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
      find "{remote_store}/{cvmfs_architecture}/Packages/{package}/$full_version" ! -name etc -maxdepth 1 -mindepth 1 -exec ln -sf {} "{workDir}/INSTALLROOT/$pkg_hash/{architecture}/{package}/" \\;
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
    self._s3_init()

  def _s3_init(self) -> None:
    # This is a separate method so that we can patch it out for unit tests.
    # Import boto3 here, so that if we don't use this remote store, we don't
    # have to install it in the first place.
    try:
      import boto3
    except ImportError:
      error("boto3 must be installed to use %s", Boto3RemoteSync)
      sys.exit(1)

    try:
      self.s3 = boto3.client("s3", endpoint_url="https://s3.cern.ch",
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

    self.s3.upload_file(Bucket=self.writeStore, Key=tar_path,
                        Filename=os.path.join(self.workdir, tar_path))
