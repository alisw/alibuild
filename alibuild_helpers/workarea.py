import codecs
import errno
import os
import os.path
import shutil
import tempfile
from collections import OrderedDict

from alibuild_helpers.log import dieOnError, debug, error
from alibuild_helpers.utilities import call_ignoring_oserrors, symlink, short_commit_hash

FETCH_LOG_NAME = "fetch-log.txt"


def cleanup_git_log(referenceSources):
  """Remove a stale fetch-log.txt.

  You must call this function before running updateReferenceRepoSpec or
  updateReferenceRepo any number of times. This is not done automatically, so
  that running those functions in parallel works properly.
  """
  try:
    os.unlink(os.path.join(referenceSources, FETCH_LOG_NAME))
  except OSError as exc:
    # Ignore errors when deleting a nonexistent file.
    dieOnError(exc.errno != errno.ENOENT,
               "Could not delete stale git log: %s" % exc)


def logged_scm(scm, package, referenceSources,
               command, directory, prompt, logOutput=True):
  """Run an SCM command, but produce an output file if it fails.

  This is useful in CI, so that we can pick up SCM failures and show them in
  the final produced log. For this reason, the file we write in this function
  must not contain any secrets. We only output the SCM command we ran, its exit
  code, and the package name, so this should be safe.
  """
  debug("%s %s for repository for %s...", scm.name, command[0], package)
  err, output = scm.exec(command, directory=directory, check=False, prompt=prompt)
  if logOutput:
    debug(output)
  if err:
    try:
      with codecs.open(os.path.join(referenceSources, FETCH_LOG_NAME),
                       "a", encoding="utf-8", errors="replace") as logf:
        logf.write("%s command for package %r failed.\n"
                   "Command: %s %s\nIn directory: %s\nExit code: %d\n" %
                   (scm.name, package, scm.name.lower(), " ".join(command), directory, err))
    except OSError as exc:
      error("Could not write error log from SCM command:", exc_info=exc)
  dieOnError(err, "Error during %s %s for reference repo for %s." %
             (scm.name.lower(), command[0], package))
  debug("Done %s %s for repository for %s", scm.name.lower(), command[0], package)
  return output


def updateReferenceRepoSpec(referenceSources, p, spec,
                            fetch=True, usePartialClone=True, allowGitPrompt=True):
  """
  Update source reference area whenever possible, and set the spec's "reference"
  if available for reading.

  @referenceSources : a string containing the path to the sources to be updated
  @p                : the name of the package to be updated
  @spec             : the spec of the package to be updated (an OrderedDict)
  @fetch            : whether to fetch updates: if False, only clone if not found
  """
  spec["reference"] = updateReferenceRepo(referenceSources, p, spec, fetch,
                                          usePartialClone, allowGitPrompt)
  if not spec["reference"]:
    del spec["reference"]


def updateReferenceRepo(referenceSources, p, spec,
                        fetch=True, usePartialClone=True, allowGitPrompt=True):
  """
  Update source reference area, if possible.
  If the area is already there and cannot be written, assume it maintained
  by someone else.

  If the area can be created, clone a bare repository with the sources.

  Returns the reference repository's local path if available, otherwise None.
  Throws a fatal error in case repository cannot be updated even if it appears
  to be writeable.

  @referenceSources : a string containing the path to the sources to be updated
  @p                : the name of the package to be updated
  @spec             : the spec of the package to be updated (an OrderedDict)
  @fetch            : whether to fetch updates: if False, only clone if not found
  """
  assert isinstance(spec, OrderedDict)
  if spec["is_devel_pkg"] or "source" not in spec:
    return None

  scm = spec["scm"]

  debug("Updating references.")
  referenceRepo = os.path.join(os.path.abspath(referenceSources), p.lower())

  call_ignoring_oserrors(os.makedirs, os.path.abspath(referenceSources), exist_ok=True)

  if not is_writeable(referenceSources):
    if os.path.exists(referenceRepo):
      debug("Using %s as reference for %s", referenceRepo, p)
      return referenceRepo  # reference is read-only
    else:
      debug("Cannot create reference for %s in %s", p, referenceSources)
      return None  # no reference can be found and created (not fatal)

  if not os.path.exists(referenceRepo):
    cmd = scm.cloneReferenceCmd(spec["source"], referenceRepo, usePartialClone)
    logged_scm(scm, p, referenceSources, cmd, ".", allowGitPrompt)
  elif fetch:
    cmd = scm.fetchCmd(spec["source"], "+refs/tags/*:refs/tags/*", "+refs/heads/*:refs/heads/*")
    logged_scm(scm, p, referenceSources, cmd, referenceRepo, allowGitPrompt)

  return referenceRepo  # reference is read-write


def is_writeable(dirpath):
  try:
    with tempfile.NamedTemporaryFile(dir=dirpath):
      return True
  except:
    return False


def checkout_sources(spec, work_dir, reference_sources, containerised_build):
  """Check out sources to be compiled, potentially from a given reference."""
  scm = spec["scm"]

  def scm_exec(command, directory=".", check=True):
    """Run the given SCM command, simulating a shell exit code."""
    try:
      logged_scm(scm, spec["package"], reference_sources, command, directory, prompt=False)
    except SystemExit as exc:
      if check:
        raise
      return exc.code
    return 0

  source_parent_dir = os.path.join(work_dir, "SOURCES", spec["package"], spec["version"])
  # The build script expects SOURCEDIR to be named after the shortened commit
  # hash, not the full one.
  source_dir = os.path.join(source_parent_dir, short_commit_hash(spec))
  os.makedirs(source_parent_dir, exist_ok=True)

  if spec["commit_hash"] != spec["tag"]:
    symlink(spec["commit_hash"], os.path.join(source_parent_dir, spec["tag"].replace("/", "_")))

  if "source" not in spec:
    # There are no sources, so just create an empty SOURCEDIR.
    os.makedirs(source_dir, exist_ok=True)
  elif spec["is_devel_pkg"]:
    shutil.rmtree(source_dir, ignore_errors=True)
    # In a container, we mount development packages' source dirs in /.
    # Outside a container, we have access to the source dir directly.
    symlink("/" + os.path.basename(spec["source"])
            if containerised_build else spec["source"],
            source_dir)
  elif os.path.isdir(source_dir):
    # Sources are a relative path or URL and the local repo already exists, so
    # checkout the right commit there.
    err = scm_exec(scm.checkoutCmd(spec["tag"]), source_dir, check=False)
    if err:
      # If we can't find the tag, it might be new. Fetch tags and try again.
      tag_ref = "refs/tags/{0}:refs/tags/{0}".format(spec["tag"])
      scm_exec(scm.fetchCmd(spec["source"], tag_ref), source_dir)
      scm_exec(scm.checkoutCmd(spec["tag"]), source_dir)
  else:
    # Sources are a relative path or URL and don't exist locally yet, so clone
    # and checkout the git repo from there.
    shutil.rmtree(source_dir, ignore_errors=True)
    scm_exec(scm.cloneSourceCmd(spec["source"], source_dir, spec.get("reference"),
                                usePartialClone=True))
    scm_exec(scm.setWriteUrlCmd(spec.get("write_repo", spec["source"])), source_dir)
    scm_exec(scm.checkoutCmd(spec["tag"]), source_dir)
