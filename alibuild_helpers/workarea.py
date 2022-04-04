import codecs
import os
import os.path
import tempfile
try:
  from collections import OrderedDict
except ImportError:
  from ordereddict import OrderedDict

from alibuild_helpers.log import dieOnError, debug
from alibuild_helpers.git import git, partialCloneFilter


def updateReferenceRepoSpec(referenceSources, p, spec, fetch, usePartialClone=True):
  """
  Update source reference area whenever possible, and set the spec's "reference"
  if available for reading.

  @referenceSources : a string containing the path to the sources to be updated
  @p                : the name of the package to be updated
  @spec             : the spec of the package to be updated (an OrderedDict)
  @fetch            : whether to fetch updates: if False, only clone if not found
  """
  spec["reference"] = updateReferenceRepo(referenceSources, p, spec, fetch, usePartialClone)
  if not spec["reference"]:
    del spec["reference"]

def updateReferenceRepo(referenceSources, p, spec, fetch=True, usePartialClone=True):
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
    cmd = ["clone", "--bare", spec["source"], referenceRepo]
    if usePartialClone:
      cmd.append(partialCloneFilter)
    git(cmd)
  elif fetch:
    with codecs.open(os.path.join(os.path.dirname(referenceRepo),
                                  "fetch-log.txt"),
                     "w", encoding="utf-8", errors="replace") as logf:
      err, output = git(("fetch", "-f", "--tags", spec["source"],
                         "+refs/heads/*:refs/heads/*"),
                        directory=referenceRepo, check=False)
      logf.write(output)
      debug(output)
      dieOnError(err, "Error while updating reference repo for %s." % spec["source"])
  return referenceRepo  # reference is read-write


def is_writeable(dirpath):
  try:
    with tempfile.NamedTemporaryFile(dir=dirpath):
      return True
  except:
    return False
