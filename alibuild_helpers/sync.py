"""Sync backends for alibuild."""

import glob
import os
import os.path
import re
import sys
import time
from requests import get
from requests.exceptions import RequestException

from alibuild_helpers.cmd import execute
from alibuild_helpers.log import debug, warning, error, dieOnError
from alibuild_helpers.utilities import format, star, resolve_store_path, resolve_links_path


class NoRemoteSync:
  """Helper class which does not do anything to sync"""
  def syncToLocal(self, p, spec):
    pass
  def syncToRemote(self, p, spec):
    pass
  def syncDistLinksToRemote(self, link_dir):
    pass

class PartialDownloadError(Exception):
  def __init__(self, downloaded, size):
    self.downloaded = downloaded
    self.size = size
  def __str__(self):
    return "only %d out of %d bytes downloaded" % (self.downloaded, self.size)


class HttpRemoteSync:
  def __init__(self, remoteStore, architecture, workdir, insecure):
    self.remoteStore = remoteStore
    self.writeStore = ""
    self.architecture = architecture
    self.workdir = workdir
    self.insecure = insecure
    self.httpTimeoutSec = 15
    self.httpConnRetries = 4
    self.httpBackoff = 0.4

  def getRetry(self, url, dest=None, returnResult=False, log=True):
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
                  debug("Download complete")
                elif now - reportTime > 3:
                  debug("%.0f%% downloaded...", 100*downloaded/size)
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

  def syncToLocal(self, p, spec):
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
                p, pkg_hash)
          return

    debug("Updating remote store for package %s; trying hashes %s",
          p, ", ".join(spec["remote_hashes"]))
    store_path = use_tarball = None
    # Find the first tarball that matches any possible hash and fetch it.
    for pkg_hash in spec["remote_hashes"]:
      store_path = resolve_store_path(self.architecture, pkg_hash)
      tarballs = self.getRetry("%s/%s/" % (self.remoteStore, store_path))
      if tarballs:
        use_tarball = tarballs[0]["name"]
        break

    if store_path is None or use_tarball is None:
      warning("%s (%s) not fetched: have you tried updating the recipes?",
              p, ", ".join(spec["remote_hashes"]))
      return

    links_path = resolve_links_path(self.architecture, spec["package"])
    execute("mkdir -p {}/{} {}/{}".format(self.workdir, store_path,
                                          self.workdir, links_path))

    destPath = os.path.join(self.workdir, store_path, use_tarball)
    if not os.path.isfile(destPath):
      # Do not download twice
      self.getRetry("/".join((self.remoteStore, store_path, use_tarball)),
                    destPath)

    # Fetch manifest file with initial symlinks. This file is updated
    # regularly; we use it to avoid many small network requests.
    manifest = self.getRetry("%s/%s.manifest" % (self.remoteStore, links_path),
                             returnResult=True)
    symlinks = {
      linkname.decode("utf-8"): target.decode("utf-8")
      for linkname, sep, target in (line.partition(b"\t")
                                    for line in manifest.splitlines())
      if sep and linkname and target
    }
    # If we've just downloaded a tarball, add a symlink to it.
    # We need to strip the leading TARS/ first, though.
    assert store_path.startswith("TARS/"), store_path
    symlinks[use_tarball] = os.path.join(store_path[len("TARS/"):], use_tarball)
    # Now add any remaining symlinks that aren't in the manifest yet. There
    # should always be relatively few of these, as the separate network
    # requests are a bit expensive.
    for link in self.getRetry("%s/%s/" % (self.remoteStore, links_path)):
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
      symlinks[linkname] = self.getRetry(
        "/".join((self.remoteStore, links_path, linkname)),
        returnResult=True, log=False).decode("utf-8").rstrip("\r\n")
    for linkname, target in symlinks.items():
      execute("ln -nsf ../../{target} {workdir}/{linkdir}/{name}".format(
        workdir=self.workdir, linkdir=links_path, name=linkname,
        target=target))

  def syncToRemote(self, p, spec):
    pass

  def syncDistLinksToRemote(self, link_dir):
    pass


class RsyncRemoteSync:
  """Helper class to sync package build directory using RSync."""

  def __init__(self, remoteStore, writeStore, architecture, workdir, rsyncOptions):
    self.remoteStore = re.sub("^ssh://", "", remoteStore)
    self.writeStore = re.sub("^ssh://", "", writeStore)
    self.architecture = architecture
    self.rsyncOptions = rsyncOptions
    self.workdir = workdir

  def syncToLocal(self, p, spec):
    debug("Updating remote store for package %s with hashes %s", p,
          ", ".join(spec["remote_hashes"]))
    err = execute("""\
    rsync -av --delete {ro} {remoteStore}/{linksPath}/ {workDir}/{linksPath}/ || :
    for storePath in {storePaths}; do
      mkdir -p {workDir}/$storePath
      # If we transferred at least one file, quit. This assumes that the remote
      # doesn't have empty dirs under TARS/<arch>/store/.
      rsync -av {ro} {remoteStore}/$storePath/ {workDir}/$storePath/ && break || :
    done
    """.format(ro=self.rsyncOptions,
               remoteStore=self.remoteStore,
               workDir=self.workdir,
               linksPath=resolve_links_path(self.architecture, p),
               storePaths=" ".join(resolve_store_path(self.architecture, pkg_hash)
                                   for pkg_hash in spec["remote_hashes"])))
    dieOnError(err, "Unable to update from specified store.")

  def syncToRemote(self, p, spec):
    if not self.writeStore:
      return
    tarballNameWithRev = format("%(package)s-%(version)s-%(revision)s.%(architecture)s.tar.gz",
                                architecture=self.architecture,
                                **spec)
    cmd = format("cd %(workdir)s && "
                 "rsync -avR %(rsyncOptions)s --ignore-existing %(storePath)s/%(tarballNameWithRev)s  %(remoteStore)s/ &&"
                 "rsync -avR %(rsyncOptions)s --ignore-existing %(linksPath)s/%(tarballNameWithRev)s  %(remoteStore)s/",
                 workdir=self.workdir,
                 remoteStore=self.remoteStore,
                 rsyncOptions=self.rsyncOptions,
                 storePath=resolve_store_path(self.architecture, spec["hash"]),
                 linksPath=resolve_links_path(self.architecture, p),
                 tarballNameWithRev=tarballNameWithRev)
    err = execute(cmd)
    dieOnError(err, "Unable to upload tarball.")

  def syncDistLinksToRemote(self, link_dir):
    if not self.writeStore:
      return
    execute("cd {w} && rsync -avR {o} --ignore-existing {t}/ {rs}/".format(
      w=self.workdir, rs=self.writeStore, o=self.rsyncOptions, t=link_dir))


class S3RemoteSync:
  """Sync package build directory from and to S3 using s3cmd.

  s3cmd must be installed separately in order for this to work.
  """

  def __init__(self, remoteStore, writeStore, architecture, workdir):
    self.remoteStore = re.sub("^s3://", "", remoteStore)
    self.writeStore = re.sub("^s3://", "", writeStore)
    self.architecture = architecture
    self.workdir = workdir

  def syncToLocal(self, p, spec):
    debug("Updating remote store for package %s with hashes %s", p,
          ", ".join(spec["remote_hashes"]))
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
      storePaths=" ".join(resolve_store_path(self.architecture, pkg_hash)
                          for pkg_hash in spec["remote_hashes"]),
      linksPath=resolve_links_path(self.architecture, p),
      workDir=self.workdir,
    ))
    dieOnError(err, "Unable to update from specified store.")

  def syncToRemote(self, p, spec):
    if not self.writeStore:
      return
    tarballNameWithRev = format("%(package)s-%(version)s-%(revision)s.%(architecture)s.tar.gz",
                                architecture=self.architecture,
                                **spec)
    cmd = format("cd %(workdir)s && "
                 "TARSHA256=`sha256sum %(storePath)s/%(tarballNameWithRev)s | awk '{ print $1 }'` && "
                 "s3cmd put -s -v --host s3.cern.ch --host-bucket %(b)s.s3.cern.ch %(storePath)s/%(tarballNameWithRev)s s3://%(b)s/%(storePath)s/ 2>&1 || true\n"
                 "HASHEDURL=`readlink %(linksPath)s/%(tarballNameWithRev)s | sed -e's|^../../||'` && "
                 "echo $HASHEDURL | s3cmd put -s -v --host s3.cern.ch --host-bucket %(b)s.s3.cern.ch - s3://%(b)s/%(linksPath)s/%(tarballNameWithRev)s 2>&1 || true\n",
                 workdir=self.workdir,
                 b=self.remoteStore,
                 storePath=resolve_store_path(self.architecture, spec["hash"]),
                 linksPath=resolve_links_path(self.architecture, p),
                 tarballNameWithRev=tarballNameWithRev)
    err = execute(cmd)
    dieOnError(err, "Unable to upload tarball.")

  def syncDistLinksToRemote(self, link_dir):
    if not self.writeStore:
      return
    execute("""\
    cd {w} || exit 1
    find {t} -type l | while read -r x; do
      hashedurl=$(readlink "$x" | sed 's|.*/[.][.]/TARS|TARS|') || exit 1
      echo $hashedurl |
        s3cmd put --skip-existing -q -P -s \
                  --add-header="x-amz-website-redirect-location:\
https://s3.cern.ch/swift/v1/{b}/$hashedurl" \
                  --host s3.cern.ch --host-bucket {b}.s3.cern.ch \
                  - "s3://{b}/$x" 2>&1
    done
    """.format(w=self.workdir, b=self.writeStore, t=link_dir))


class Boto3RemoteSync:
  """Sync package build directory from and to S3 using boto3.

  As boto3 doesn't support Python 2, this class can only be used under Python
  3. boto3 is only imported at __init__ time, so if this class is never
  instantiated, boto3 doesn't have to be installed.

  This class has the advantage over S3RemoteSync that it uses the same
  connection to S3 every time, while s3cmd must establish a new connection each
  time.
  """

  def __init__(self, remoteStore, writeStore, architecture, workdir):
    self.remoteStore = re.sub("^b3://", "", remoteStore)
    self.writeStore = re.sub("^b3://", "", writeStore)
    self.architecture = architecture
    self.workdir = workdir
    self._s3_init()

  def _s3_init(self):
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
            "variables to %sBuild in order to use the S3 remote store", star())
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

  def syncToLocal(self, p, spec):
    from botocore.exceptions import ClientError
    debug("Updating remote store for package %s with hashes %s", p,
          ", ".join(spec["remote_hashes"]))

    # If we already have a tarball with any equivalent hash, don't check S3.
    have_tarball = False
    for pkg_hash in spec["remote_hashes"]:
      store_path = resolve_store_path(self.architecture, pkg_hash)
      if glob.glob(os.path.join(self.workdir, store_path, "%s-*.tar.gz" % p)):
        debug("Reusing existing tarball for %s@%s", p, pkg_hash)
        have_tarball = True
        break

    for pkg_hash in spec["remote_hashes"]:
      if have_tarball:
        break
      store_path = resolve_store_path(self.architecture, pkg_hash)

      # We don't already have a tarball with the hash that we need, so download
      # the first existing one from the remote, if possible. (Downloading more
      # than one is a waste of time as they should be equivalent and we only
      # ever use one anyway.)
      for tarball in self._s3_listdir(store_path):
        debug("Fetching tarball %s", tarball)
        # Create containing directory locally. (exist_ok= is python3-specific.)
        os.makedirs(os.path.join(self.workdir, store_path), exist_ok=True)
        self.s3.download_file(Bucket=self.remoteStore, Key=tarball,
                              Filename=os.path.join(self.workdir, store_path,
                                                    os.path.basename(tarball)))
        have_tarball = True  # break out of outer loop
        break

    if not have_tarball:
      debug("Remote has no tarballs for %s with hashes %s", p,
            ", ".join(spec["remote_hashes"]))

    links_path = resolve_links_path(self.architecture, p)
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
        dieOnError(execute("ln -sf {} {}".format(target, link_path)),
                  "Unable to create symlink {} -> {}".format(link_name, target))
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
      dieOnError(execute("ln -sf {} {}".format(target, link_path)),
                 "Unable to create symlink {} -> {}".format(link_key, target))

  def syncToRemote(self, p, spec):
    if not self.writeStore:
      return
    tarballNameWithRev = ("{package}-{version}-{revision}.{architecture}.tar.gz"
                          .format(architecture=self.architecture, **spec))
    tar_path = os.path.join(resolve_store_path(self.architecture, spec["hash"]),
                            tarballNameWithRev)
    link_path = os.path.join(resolve_links_path(self.architecture, p),
                             tarballNameWithRev)
    tar_exists = self._s3_key_exists(tar_path)
    link_exists = self._s3_key_exists(link_path)
    if tar_exists and link_exists:
      debug("%s exists on S3 already, not uploading", tarballNameWithRev)
      return
    if tar_exists or link_exists:
      warning("%s exists already but %s does not, overwriting!",
              tar_path if tar_exists else link_path,
              link_path if tar_exists else tar_path)
    debug("Uploading tarball and symlink for %s %s-%s (%s) to S3",
          p, spec["version"], spec["revision"], spec["hash"])
    self.s3.upload_file(Bucket=self.writeStore, Key=tar_path,
                        Filename=os.path.join(self.workdir, tar_path))
    self.s3.put_object(Bucket=self.writeStore, Key=link_path,
                       Body=os.readlink(os.path.join(self.workdir, link_path))
                              .lstrip("./").encode("utf-8"))

  def syncDistLinksToRemote(self, link_dir):
    if not self.writeStore:
      return
    for fname in os.listdir(os.path.join(self.workdir, link_dir)):
      link_key = os.path.join(link_dir, fname)
      path = os.path.join(self.workdir, link_key)
      if not os.path.islink(path) or self._s3_key_exists(link_key):
        continue
      hash_path = re.sub(r"^(\.\./)*", "", os.readlink(path))
      self.s3.put_object(Bucket=self.writeStore,
                         Key=link_key,
                         Body=os.fsencode(hash_path),
                         ACL="public-read",
                         WebsiteRedirectLocation=hash_path)
