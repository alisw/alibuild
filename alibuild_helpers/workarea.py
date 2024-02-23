import codecs
import errno
import os
import os.path
import tempfile
try:
  from collections import OrderedDict
except ImportError:
  from ordereddict import OrderedDict

from alibuild_helpers.git import Git
from alibuild_helpers.sl import Sapling
from alibuild_helpers.log import dieOnError, debug, error

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
  if "source" not in spec:
    return

  scm = spec["scm"]

  debug("Updating references.")
  referenceRepo = os.path.join(os.path.abspath(referenceSources), p.lower())

  try:
    os.makedirs(os.path.abspath(referenceSources), exist_ok=True)
  except OSError:
    pass

  if not is_writeable(referenceSources):
    if os.path.isdir(referenceRepo):
      debug("Using %s as reference for %s", referenceRepo, p)
      return referenceRepo  # reference is read-only
    else:
      debug("Cannot create reference for %s in %s", p, referenceSources)
      return None  # no reference can be found and created (not fatal)

  # In preparation for cloning the repo, wipe out any ref cache file with the
  # same name produced by update_refs.
  try:
    os.unlink(referenceRepo)
  except OSError:
    pass

  if not os.path.exists(referenceRepo):
    cmd = scm.cloneCmd(spec["source"], referenceRepo, usePartialClone)
    logged_scm(scm, p, referenceSources, cmd, ".", allowGitPrompt)
  elif fetch:
    cmd = scm.fetchCmd(spec["source"])
    logged_scm(scm, p, referenceSources, cmd, referenceRepo, allowGitPrompt)

  return referenceRepo  # reference is read-write


def update_refs(spec, reference_sources, always_fetch=True, allow_prompt=False):
    """Update SCM refs for the given package and cache them."""
    if "source" not in spec:
        # There is no repository to update. Skip this package.
        return
    reference_repo = os.path.join(reference_sources, spec["package"].lower())
    # If the reference repo exists and is a sapling checkout, then use
    # Sapling, else use Git.
    scm = Sapling() if os.path.exists(os.path.join(reference_repo, ".sl")) else Git()
    # If we previously cached a list of refs, and always_fetch isn't set, then
    # read that cache.
    if not always_fetch and os.path.isfile(reference_repo):
        with open(reference_repo) as refs_cache:
            raw_refs = refs_cache.read()
    else:
        # If reference_repo is a "real" checkout, not a cache file, use it;
        # otherwise fetch from the internet.
        list_refs_url = reference_repo if os.path.isdir(reference_repo) else spec["source"]
        raw_refs = logged_scm(
            scm, spec["package"], reference_sources, scm.listRefsCmd() + [list_refs_url],
            ".", prompt=allow_prompt, logOutput=False,
        )
    spec["scm_refs"] = scm.parseRefs(raw_refs)
    try:
        os.makedirs(reference_sources, exist_ok=True)
        with open(reference_repo, "w") as refs_cache:
            refs_cache.write(raw_refs)
    except OSError:
        # If we can't save refs (e.g. if a repo checkout exists here, or if
        # the path is not writable), then skip writing the cache.
        pass
    debug("%r package updated: %d refs found", spec["package"],
          len(spec["scm_refs"]))


def is_writeable(dirpath):
  try:
    with tempfile.NamedTemporaryFile(dir=dirpath):
      return True
  except:
    return False
