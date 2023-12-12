# Import as function if they do not have any side effects
from os.path import dirname, basename

# Import as modules if I need to mock them later
import os.path as path
import os
import glob
import sys
import shutil
from alibuild_helpers import log


def decideClean(workDir, architecture, aggressiveCleanup):
  """Decide what to delete, without actually doing it.

  To clean up obsolete build directories:
  - Find all the symlinks in "BUILD"
  - Find all the directories in "BUILD"
  - Schedule a directory for deletion if it does not have a symlink

  Installed packages are deleted from the final installation directory
  according to the above scheme as well.

  The temporary directory and temporary install roots are always cleaned up.

  In aggressive mode, the following are also cleaned up:

  - Tarballs (but not their symlinks), since these are expected to either be
    unpacked in the installation directory, available from the remote store
    for download, or not needed any more if their installation directory is
    gone.
  - Git checkouts for specific tags, since we expect to be able to rebuild
    those easily from the mirror directory.

  In the case of installed packages and tarballs, only those for the given
  architecture are considered for deletion.
  """
  symlinksBuild = [os.readlink(x) for x in glob.glob("%s/BUILD/*-latest*" % workDir)]
  # $WORK_DIR/TMP should always be cleaned up. This does not happen only
  # in the case we run out of space while unpacking. INSTALLROOT is similar,
  # though it is not cleaned up automatically in case of build errors.
  # $WORK_DIR/<architecture>/store can be cleaned up as well, because
  # we do not need the actual tarballs after they have been built.
  toDelete = ["%s/TMP" % workDir, "%s/INSTALLROOT" % workDir]
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
    log.info("Nothing to delete.")
    sys.exit(0)

  log.banner("This %s delete the following directories:\n%s",
             "would" if dryRun else "will", "\n".join(toDelete))
  if dryRun:
    log.info("--dry-run / -n specified. Doing nothing.")
    sys.exit(0)

  have_error = False
  for directory in toDelete:
    try:
      shutil.rmtree(directory)
    except OSError as exc:
      have_error = True
      log.error("Unable to delete %s:", directory, exc_info=exc)

  sys.exit(1 if have_error else 0)
