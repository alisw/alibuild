from __future__ import print_function

# Import as function if they do not have any side effects
from os.path import dirname, basename

# Import as modules if I need to mock them later
import os.path as path
import os
import glob
import sys
import shutil

def print_results(x):
  print(x)

def decideClean(workDir, architecture, aggressiveCleanup):
  """ Decides what to delete, without actually doing it:
      - Find all the symlinks in "BUILD"
      - Find all the directories in "BUILD"
      - Schedule a directory for deletion if it does not have a symlink
  """
  symlinksBuild = [os.readlink(x) for x in glob.glob("%s/BUILD/*-latest*" % workDir)]
  # $WORK_DIR/TMP should always be cleaned up. This does not happen only
  # in the case we run out of space while unpacking.
  # $WORK_DIR/<architecture>/store can be cleaned up as well, because
  # we do not need the actual tarballs after they have been built.
  toDelete = ["%s/TMP" % workDir]
  if aggressiveCleanup:
    toDelete += ["%s/TARS/%s/store" % (workDir, architecture),
                 "%s/SOURCES" % (workDir)]
  allBuildStuff = glob.glob("%s/BUILD/*" % workDir)
  toDelete += [x for x in allBuildStuff
               if not path.islink(x) and not basename(x) in symlinksBuild]
  installGlob ="%s/%s/*/" % (workDir, architecture)
  installedPackages = set([dirname(x) for x in glob.glob(installGlob)])
  symlinksInstall = []
  for x in installedPackages:
    symlinksInstall += [path.realpath(y) for y in glob.glob(x + "/latest*")]
  toDelete += [x for x in glob.glob(installGlob+ "*")
               if not path.islink(x) and not path.realpath(x) in symlinksInstall]
  toDelete = [x for x in toDelete if path.exists(x)]
  return toDelete

def doClean(workDir, architecture, aggressiveCleanup, dryRun):
  """ CLI API to cleanup build area """
  toDelete = decideClean(workDir, architecture, aggressiveCleanup)
  if not toDelete:
    print_results("Nothing to delete.")
    sys.exit(0)
  finalMessage = "This will delete the following directories:\n\n" + "\n".join(toDelete)

  if dryRun:
    finalMessage += "\n\n--dry-run / -n specified. Doing nothing."
    print_results(finalMessage)
    sys.exit(0)

  print_results(finalMessage)
  for x in toDelete:
    try:
      shutil.rmtree(x)
    except OSError:
      print_results("Unable to delete %s." % x)
      sys.exit(1)
  sys.exit(0)
