import codecs
import errno
import os
import os.path
import tempfile
try:
  from collections import OrderedDict
except ImportError:
  from ordereddict import OrderedDict

from alibuild_helpers.log import dieOnError, debug, info, error
from alibuild_helpers.git import clone_speedup_options

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
  # This might take a long time, so show the user what's going on.
  info("%s %s for repository for %s...", scm.name, command[0], package)
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
  info("Done %s %s for repository for %s", scm.name.lower(), command[0], package)
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
    os.makedirs(os.path.abspath(referenceSources))
  except:
    pass

  if not is_writeable(referenceSources):
    if os.path.exists(referenceRepo):
      debug("Using %s as reference for %s", referenceRepo, p)
      return referenceRepo  # reference is read-only
    else:
      debug("Cannot create reference for %s in %s", p, referenceSources)
      return None  # no reference can be found and created (not fatal)

  if not os.path.exists(referenceRepo):
    cmd = scm.cloneCmd(spec["source"], referenceRepo, usePartialClone)
    logged_scm(scm, p, referenceSources, cmd, ".", allowGitPrompt)
  elif fetch:
    cmd = scm.fetchCmd(spec["source"])
    logged_scm(scm, p, referenceSources, cmd, referenceRepo, allowGitPrompt)

  return referenceRepo  # reference is read-write


def is_writeable(dirpath):
  try:
    with tempfile.NamedTemporaryFile(dir=dirpath):
      return True
  except:
    return False
