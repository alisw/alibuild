from alibuild_helpers.log import dieOnError, debug
from alibuild_helpers.cmd import execute
from os.path import dirname, abspath
try:
  from commands import getstatusoutput
except ImportError:
  from subprocess import getstatusoutput
from alibuild_helpers.utilities import format

import os
import os.path as path
try:
  from collections import OrderedDict
except ImportError:
  from ordereddict import OrderedDict

def updateReferenceRepos(referenceSources, p, spec):
  """
  Update source reference area, if possible.
  If the area is already there and cannot be written, assume it maintained
  by someone else.

  If the area can be created, clone a bare repository with the sources.

  @referenceSources: a string containing the path to the sources to be updated
  @p: the name of the package (?) to be updated
  @spec: the spec of the package to be updated
  """
  assert(type(spec) == OrderedDict)
  debug("Updating references.")
  referenceRepo = "%s/%s" % (abspath(referenceSources), p.lower())

  if is_writeable(dirname(referenceSources)):
    getstatusoutput("mkdir -p %s" % referenceSources)

  if not is_writeable(referenceSources):
    if path.exists(referenceRepo):
      debug("Using %s as reference for %s." % (referenceRepo, p))
      spec["reference"] = referenceRepo
    else:
      debug("Cannot create reference for %s in %s" % (p, referenceSources))
    return

  err, out = getstatusoutput("mkdir -p %s" % abspath(referenceSources))
  if not "source" in spec:
    return

  if not path.exists(referenceRepo):
    cmd = ["git", "clone", "--bare", spec["source"], referenceRepo]
    debug(" ".join(cmd))
    err = execute(" ".join(cmd))
  else:
    err = execute(format("cd %(referenceRepo)s && "
                         "git fetch --tags %(source)s 2>&1 && "
                         "git fetch %(source)s 2>&1",
                         referenceRepo=referenceRepo,
                         source=spec["source"]))
  dieOnError(err, "Error while updating reference repos %s." % spec["source"])
  spec["reference"] = referenceRepo


def is_writeable(path):
  return os.access(path, os.W_OK)
