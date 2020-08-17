from alibuild_helpers.log import dieOnError, debug
from alibuild_helpers.cmd import execute
from alibuild_helpers.git import partialCloneFilter
from os.path import dirname, abspath
try:
  from commands import getstatusoutput
except ImportError:
  from subprocess import getstatusoutput
from alibuild_helpers.utilities import format

import os
import os.path as path
import tempfile
try:
  from collections import OrderedDict
except ImportError:
  from ordereddict import OrderedDict

def updateReferenceRepoSpec(referenceSources, p, spec, fetch):
  """
  Update source reference area whenever possible, and set the spec's "reference"
  if available for reading.

  @referenceSources : a string containing the path to the sources to be updated
  @p                : the name of the package to be updated
  @spec             : the spec of the package to be updated (an OrderedDict)
  @fetch            : whether to fetch updates: if False, only clone if not found
  """
  spec["reference"] = updateReferenceRepo(referenceSources, p, spec, fetch)
  if not spec["reference"]:
    del spec["reference"]

def updateReferenceRepo(referenceSources, p, spec, fetch=True):
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
  assert(type(spec) == OrderedDict)
  if not "source" in spec:
    return

  debug("Updating references.")
  referenceRepo = os.path.join(abspath(referenceSources), p.lower())

  try:
    os.makedirs(abspath(referenceSources))
  except:
    pass

  if not is_writeable(referenceSources):
    if path.exists(referenceRepo):
      debug("Using %s as reference for %s" % (referenceRepo, p))
      return referenceRepo  # reference is read-only
    else:
      debug("Cannot create reference for %s in %s" % (p, referenceSources))
      return None  # no reference can be found and created (not fatal)

  err = False
  if not path.exists(referenceRepo):
    cmd = ["git", "clone", partialCloneFilter, "--bare", spec["source"], referenceRepo]
    cmd = [x for x in cmd if x]
    debug("Cloning reference repository: %s" % " ".join(cmd))
    err = execute(cmd)
  elif fetch:
    cmd = format("cd %(referenceRepo)s && "
                 "git fetch -f --tags %(source)s 2>&1 && "
                 "git fetch -f %(source)s '+refs/heads/*:refs/heads/*' 2>&1",
                 referenceRepo=referenceRepo,
                 source=spec["source"])
    debug("Updating reference repository: %s" % cmd)
    err = execute(cmd)
  dieOnError(err, "Error while updating reference repos %s." % spec["source"])
  return referenceRepo  # reference is read-write

def is_writeable(dirpath):
  try:
    with tempfile.NamedTemporaryFile(dir=dirpath):
      return True
  except:
    return False
