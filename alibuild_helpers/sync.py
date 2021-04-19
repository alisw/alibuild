"""Sync backends for alibuild."""

import os
import os.path
import re
import time
from requests import get
from requests.exceptions import RequestException

from alibuild_helpers.cmd import execute
from alibuild_helpers.log import debug, warning, error, dieOnError
from alibuild_helpers.utilities import format


# Helper class which does not do anything to sync
class NoRemoteSync:
  def syncToLocal(self, p, spec):
    pass
  def syncToRemote(self, p, spec):
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
    self.doneOrFailed = []

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
    if spec["remote_revision_hash"] in self.doneOrFailed:
      debug("Will not redownload %s with build hash %s",
            p, spec["remote_revision_hash"])
      return

    debug("Updating remote store for package %s@%s",
          p, spec["remote_revision_hash"])
    hashListUrl = "{rs}/{sp}/".format(rs=self.remoteStore, sp=spec["remote_store_path"])
    manifestUrl = "{rs}/{lp}.manifest".format(rs=self.remoteStore, lp=spec["remote_links_path"])
    pkgListUrl = "{rs}/{lp}/".format(rs=self.remoteStore, lp=spec["remote_links_path"])

    hashList = self.getRetry(hashListUrl)
    freeSymlinkList = None
    if hashList is not None:
      manifest = self.getRetry(manifestUrl, returnResult=True)
      freeSymlinkList = self.getRetry(pkgListUrl)
    if freeSymlinkList is None or hashList is None:
      warning("%s (%s) not fetched: have you tried updating the recipes?",
              p, spec["remote_revision_hash"])
      self.doneOrFailed.append(spec["remote_revision_hash"])
      return

    execute("mkdir -p {} {}".format(spec["remote_tar_hash_dir"],
                                    spec["remote_tar_link_dir"]))
    hashList = [x["name"] for x in hashList]

    hasErr = False
    for pkg in hashList:
      destPath = os.path.join(spec["remote_tar_hash_dir"], pkg)
      if os.path.isfile(destPath):
        # Do not redownload twice
        continue
      if not self.getRetry(
          "/".join((self.remoteStore, spec["remote_store_path"], pkg)),
          destPath):
        hasErr = True

    # Fetch manifest file with initial symlinks. This file is updated
    # regularly; we use it to avoid many small network requests.
    symlinks = {
      linkname.decode("utf-8"): target.decode("utf-8")
      for linkname, sep, target in (line.partition(b"\t")
                                    for line in manifest.splitlines())
      if sep and linkname and target
    }
    # If we've just downloaded a tarball, add a symlink to it.
    symlinks.update({
      linkname: os.path.join(self.architecture, "store",
                             spec["remote_revision_hash"][0:2],
                             spec["remote_revision_hash"],
                             linkname)
      for linkname in hashList
    })
    # Now add any remaining symlinks that aren't in the manifest yet. There
    # should always be relatively few of these, as the separate network
    # requests are a bit expensive.
    for link in freeSymlinkList:
      linkname = link["name"]
      if linkname in symlinks:
        # This symlink is already present in the manifest.
        continue
      if os.path.islink(os.path.join(spec["remote_tar_link_dir"], linkname)):
        # We have this symlink locally. With local revisions, we won't produce
        # revisions that will conflict with remote revisions unless we upload
        # them anyway, so there's no need to redownload.
        continue
      # This symlink isn't in the manifest yet, and we don't have it locally,
      # so download it individually.
      symlinks[linkname] = self.getRetry(
        "/".join((self.remoteStore, spec["remote_links_path"], linkname)),
        returnResult=True, log=False).decode("utf-8").rstrip("\r\n")
    for linkname, target in symlinks.items():
      execute("ln -nsf ../../{target} {linkdir}/{name}".format(
        linkdir=spec["remote_tar_link_dir"], target=target, name=linkname))

    if not hasErr:
      self.doneOrFailed.append(spec["remote_revision_hash"])

  def syncToRemote(self, p, spec):
    return

# Helper class to sync package build directory using RSync.
class RsyncRemoteSync:
  def __init__(self, remoteStore, writeStore, architecture, workdir, rsyncOptions):
    self.remoteStore = re.sub("^ssh://", "", remoteStore)
    self.writeStore = re.sub("^ssh://", "", writeStore)
    self.architecture = architecture
    self.rsyncOptions = rsyncOptions
    self.workdir = workdir

  def syncToLocal(self, p, spec):
    debug("Updating remote store for package %s@%s", p, spec["remote_revision_hash"])
    cmd = format("mkdir -p %(tarballHashDir)s\n"
                 "rsync -av %(ro)s %(remoteStore)s/%(storePath)s/ %(tarballHashDir)s/ || true\n"
                 "rsync -av --delete %(ro)s %(remoteStore)s/%(linksPath)s/ %(tarballLinkDir)s/ || true\n",
                 ro=self.rsyncOptions,
                 remoteStore=self.remoteStore,
                 storePath=spec["remote_store_path"],
                 linksPath=spec["remote_links_path"],
                 tarballHashDir=spec["remote_tar_hash_dir"],
                 tarballLinkDir=spec["remote_tar_link_dir"])
    err = execute(cmd)
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
                 storePath=spec["remote_store_path"],
                 linksPath=spec["remote_links_path"],
                 tarballNameWithRev=tarballNameWithRev)
    err = execute(cmd)
    dieOnError(err, "Unable to upload tarball.")

class S3RemoteSync:
  def __init__(self, remoteStore, writeStore, architecture, workdir):
    # This will require rclone to be installed in order to actually work
    # The name of the remote is always alibuild
    self.remoteStore = re.sub("^s3://", "", remoteStore)
    self.writeStore = re.sub("^s3://", "", writeStore)
    self.architecture = architecture
    self.workdir = workdir

  def syncToLocal(self, p, spec):
    debug("Updating remote store for package %s@%s", p, spec["remote_revision_hash"])
    err = execute("""\
    s3cmd --no-check-md5 sync -s -v --host s3.cern.ch --host-bucket {b}.s3.cern.ch \
          "s3://{b}/{storePath}/" "{tarballHashDir}/" 2>&1 || true
    mkdir -p "{tarballLinkDir}"
    find "{tarballLinkDir}" -type l -delete
    curl -sL "https://s3.cern.ch/swift/v1/{b}/{linksPath}.manifest" |
      while IFS='\t' read -r symlink target; do
        ln -sf "../../$target" "{tarballLinkDir}/$symlink" || true
      done
    for x in $(curl -sL "https://s3.cern.ch/swift/v1/{b}/?prefix={linksPath}/"); do
      # Skip already existing symlinks -- these were from the manifest.
      # (We delete leftover symlinks from previous runs above.)
      [ -L "{tarballLinkDir}/$(basename "$x")" ] && continue
      ln -sf "../../$(curl -sL "https://s3.cern.ch/swift/v1/{b}/$x")" \
         "{tarballLinkDir}/$(basename "$x")" || true
    done
    """.format(
      b=self.remoteStore,
      storePath=spec["remote_store_path"],
      linksPath=spec["remote_links_path"],
      tarballHashDir=spec["remote_tar_hash_dir"],
      tarballLinkDir=spec["remote_tar_link_dir"],
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
                 "s3cmd put -s -v --host s3.cern.ch --host-bucket %(b)s.s3.cern.ch %(storePath)s/%(tarballNameWithRev)s s3://%(b)s/%(storePath)s/ 2>/dev/null || true\n"
                 "HASHEDURL=`readlink %(linksPath)s/%(tarballNameWithRev)s | sed -e's|^../../||'` && "
                 "echo $HASHEDURL | s3cmd put -s -v --host s3.cern.ch --host-bucket %(b)s.s3.cern.ch - s3://%(b)s/%(linksPath)s/%(tarballNameWithRev)s 2>/dev/null || true\n",
                 workdir=self.workdir,
                 b=self.remoteStore,
                 storePath=spec["remote_store_path"],
                 linksPath=spec["remote_links_path"],
                 tarballNameWithRev=tarballNameWithRev)
    err = execute(cmd)
    dieOnError(err, "Unable to upload tarball.")
