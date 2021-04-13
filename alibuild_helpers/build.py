from os.path import abspath, exists, basename, dirname, join, realpath
from os import makedirs, unlink, readlink, rmdir
try:
  from commands import getstatusoutput
except ImportError:
  from subprocess import getstatusoutput
from alibuild_helpers.analytics import report_event
from alibuild_helpers.log import debug, error, info, banner, warning
from alibuild_helpers.log import dieOnError
from alibuild_helpers.cmd import execute, getStatusOutputBash, BASH
from alibuild_helpers.utilities import prunePaths
from alibuild_helpers.utilities import format, dockerStatusOutput, parseDefaults, readDefaults
from alibuild_helpers.utilities import getPackageList
from alibuild_helpers.utilities import validateDefaults
from alibuild_helpers.utilities import Hasher
from alibuild_helpers.utilities import yamlDump
from alibuild_helpers.git import partialCloneFilter
from alibuild_helpers.sync import NoRemoteSync, HttpRemoteSync, S3RemoteSync, RsyncRemoteSync
import yaml
from alibuild_helpers.workarea import updateReferenceRepoSpec
from alibuild_helpers.log import logger_handler, LogFormatter, ProgressPrint
from datetime import datetime
from glob import glob
try:
  from collections import OrderedDict
except ImportError:
  from ordereddict import OrderedDict

import socket
import os
import ssl
import re
import shutil
import sys
import time

def star():
  return re.sub("build.*$", "", basename(sys.argv[0]).lower())

def gzip():
  return getstatusoutput("which pigz")[0] and "gzip" or "pigz"

def tar():
  return getstatusoutput("tar --ignore-failed-read -cvvf /dev/null /dev/zero")[0] and "tar" or "tar --ignore-failed-read"

def writeAll(fn, txt):
  f = open(fn, "w")
  f.write(txt)
  f.close()

def readHashFile(fn):
  try:
    return open(fn).read().strip("\n")
  except IOError:
    return "0"

def getDirectoryHash(d):
  if exists(join(d, ".git")):
    err, out = getstatusoutput("GIT_DIR=%s/.git git rev-parse HEAD" % d)
    dieOnError(err, "Impossible to find reference for %s " % d)
  else:
    err, out = getstatusoutput("pip --disable-pip-version-check show alibuild | grep -e \"^Version:\" | sed -e 's/.* //'")
    dieOnError(err, "Impossible to find reference for %s " % d)
  return out

# Creates a directory in the store which contains symlinks to the package
# and its direct / indirect dependencies
def createDistLinks(spec, specs, args, repoType, requiresType):
  # At the point we call this function, spec has a single, definitive hash.
  target = format("TARS/%(a)s/%(rp)s/%(p)s/%(p)s-%(v)s-%(r)s",
                  a=args.architecture,
                  rp=repoType,
                  p=spec["package"],
                  v=spec["version"],
                  r=spec["revision"])
  shutil.rmtree(target.encode("utf-8"), True)
  cmd = format("cd %(w)s && mkdir -p %(t)s", w=args.workDir, t=target)
  links = []
  for x in [spec["package"]] + list(spec[requiresType]):
    dep = specs[x]
    source = format("../../../../../TARS/%(a)s/store/%(sh)s/%(h)s/%(p)s-%(v)s-%(r)s.%(a)s.tar.gz",
                    a=args.architecture,
                    sh=dep["hash"][0:2],
                    h=dep["hash"],
                    p=dep["package"],
                    v=dep["version"],
                    r=dep["revision"])
    links.append(format("ln -sfn %(source)s %(target)s",
                 target=target,
                 source=source))
  # We do it in chunks to avoid hitting shell limits but
  # still do more than one symlink at the time, to save the
  # forking cost.
  for g in [ links[i:i+10] for i in range(0, len(links), 10) ]:
    execute(" && ".join([cmd] + g))

  rsyncOptions = ""
  if args.writeStore.startswith("s3://"):
    bucket = re.sub("^s3://", "", args.writeStore)
    cmd = format("cd %(w)s && "
                 "for x in `find %(t)s -type l`; do"
                 "  HASHEDURL=`readlink $x | sed -e 's|.*/[.][.]/TARS|TARS|'` && "
                 "  echo $HASHEDURL | s3cmd put --skip-existing -q -P -s --add-header=\"x-amz-website-redirect-location:https://s3.cern.ch/swift/v1/%(b)s/${HASHEDURL}\" --host s3.cern.ch --host-bucket %(b)s.s3.cern.ch - s3://%(b)s/$x 2>/dev/null;"
                 "done",
                 w=args.workDir,
                 b=bucket,
                 t=target)
    execute(cmd)
  elif args.writeStore:
    cmd = format("cd %(w)s && "
                 "rsync -avR %(o)s --ignore-existing %(t)s/  %(rs)s/",
                 w=args.workDir,
                 rs=args.writeStore,
                 o=rsyncOptions,
                 t=target)
    execute(cmd)


def storeHashes(package, specs, isDevelPkg, considerRelocation):
  """Calculate various hashes for package, and store them in specs[package].

  Assumes that all dependencies of the package already have a definitive hash.
  """
  spec = specs[package]

  if "remote_revision_hash" in spec and "local_revision_hash" in spec:
    # We've already calculated these hashes before, so no need to do it again.
    # This also works around a bug, where after the first hash calculation,
    # some attributes of spec are changed (e.g. append_path and prepend_path
    # entries are turned from strings into lists), which changes the hash on
    # subsequent calculations.
    return

  h = Hasher()
  dh = Hasher()

  for x in ["recipe", "version", "package", "commit_hash",
            "env", "append_path", "prepend_path"]:
    if sys.version_info[0] < 3 and x in spec and type(spec[x]) == OrderedDict:
      # Python 2: use YAML dict order to prevent changing hashes
      h(str(yaml.safe_load(yamlDump(spec[x]))))
    else:
      h(str(spec.get(x, "none")))

  # If the commit hash is a real hash, and not a tag, we can safely assume
  # that's unique, and therefore we can avoid putting the repository or the
  # name of the branch in the hash.
  if spec["commit_hash"] == spec.get("tag", "0"):
    h(spec.get("source", "none"))
    if "source" in spec:
      h(spec["tag"])

  for dep in spec.get("requires", []):
    # At this point, our dependencies have a single hash, local or remote.
    h(specs[dep]["hash"])
    dh(specs[dep]["hash"] + specs[dep].get("devel_hash", ""))

  if spec.get("force_rebuild", False):
    h(str(time.time()))

  if isDevelPkg and "incremental_recipe" in spec:
    h(spec["incremental_recipe"])
    ih = Hasher()
    ih(spec["incremental_recipe"])
    spec["incremental_hash"] = ih.hexdigest()
  elif isDevelPkg:
    h(spec.get("devel_hash"))

  if considerRelocation and "relocate_paths" in spec:
    h("relocate:"+" ".join(sorted(spec["relocate_paths"])))

  spec["remote_revision_hash"] = h.hexdigest()
  spec["deps_hash"] = dh.hexdigest()
  # The local hash must differ from the remote hash to avoid conflicts where
  # the remote has a package with the same hash as an existing local revision.
  h("local")
  spec["local_revision_hash"] = h.hexdigest()


def doBuild(args, parser):
  if args.remoteStore.startswith("http"):
    syncHelper = HttpRemoteSync(args.remoteStore, args.architecture, args.workDir, args.insecure)
  elif args.remoteStore.startswith("s3://"):
    syncHelper = S3RemoteSync(args.remoteStore, args.writeStore,
                              args.architecture, args.workDir)
  elif args.remoteStore:
    syncHelper = RsyncRemoteSync(args.remoteStore, args.writeStore, args.architecture, args.workDir, "")
  else:
    syncHelper = NoRemoteSync()

  packages = args.pkgname
  dockerImage = args.dockerImage if "dockerImage" in args else None
  specs = {}
  buildOrder = []
  workDir = abspath(args.workDir)
  prunePaths(workDir)

  if not exists(args.configDir):
    return (error, ("Cannot find %sdist recipes under directory \"%s\".\n" +
                    "Maybe you need to \"cd\" to the right directory or " +
                    "you forgot to run \"aliBuild init\"?") % (star(), args.configDir), 1)

  err, value = getstatusoutput("GIT_DIR=%s/.git git symbolic-ref -q HEAD" % args.configDir)
  branch_basename = re.sub("refs/heads/", "", value)
  branch_stream = re.sub("-patches$", "", branch_basename)
  # In case the basename and the stream are the same,
  # the stream becomes empty.
  if branch_stream == branch_basename:
    branch_stream = ""

  defaultsReader = lambda : readDefaults(args.configDir, args.defaults, parser.error, args.architecture)
  (err, overrides, taps) = parseDefaults(args.disable,
                                         defaultsReader, debug)
  dieOnError(err, err)

  specDir = "%s/SPECS" % workDir
  if not exists(specDir):
    makedirs(specDir)

  os.environ["ALIBUILD_ALIDIST_HASH"] = getDirectoryHash(args.configDir)

  debug("Building for architecture %s", args.architecture)
  debug("Number of parallel builds: %d", args.jobs)
  debug("Using %sBuild from %sbuild@%s recipes in %sdist@%s",
        star(), star(), getDirectoryHash(dirname(__file__)), star(),
        os.environ["ALIBUILD_ALIDIST_HASH"])

  (systemPackages, ownPackages, failed, validDefaults) = getPackageList(packages                = packages,
                                                                        specs                   = specs,
                                                                        configDir               = args.configDir,
                                                                        preferSystem            = args.preferSystem,
                                                                        noSystem                = args.noSystem,
                                                                        architecture            = args.architecture,
                                                                        disable                 = args.disable,
                                                                        defaults                = args.defaults,
                                                                        dieOnError              = dieOnError,
                                                                        performPreferCheck      = lambda pkg, cmd : dockerStatusOutput(cmd, dockerImage, executor=getStatusOutputBash),
                                                                        performRequirementCheck = lambda pkg, cmd : dockerStatusOutput(cmd, dockerImage, executor=getStatusOutputBash),
                                                                        performValidateDefaults = lambda spec : validateDefaults(spec, args.defaults),
                                                                        overrides               = overrides,
                                                                        taps                    = taps,
                                                                        log                     = debug)
  if validDefaults and args.defaults not in validDefaults:
    return (error, "Specified default `%s' is not compatible with the packages you want to build.\n" % args.defaults +
                   "Valid defaults:\n\n- " +
                   "\n- ".join(sorted(validDefaults)), 1)

  if failed:
    return (error, "The following packages are system requirements and could not be found:\n\n- " + "\n- ".join(sorted(list(failed))) +
                   "\n\nPlease run:\n\n\taliDoctor %s\n\nto get a full diagnosis." % args.pkgname.pop(), 1)

  for x in specs.values():
    x["requires"] = [r for r in x["requires"] if not r in args.disable]
    x["build_requires"] = [r for r in x["build_requires"] if not r in args.disable]
    x["runtime_requires"] = [r for r in x["runtime_requires"] if not r in args.disable]

  if systemPackages:
    banner("%sBuild can take the following packages from the system and will not build them:\n  %s",
           star(), ", ".join(systemPackages))
  if ownPackages:
    banner("The following packages cannot be taken from the system and will be built:\n  %s",
           ", ".join(ownPackages))

  # Do topological sort to have the correct build order even in the
  # case of non-tree like dependencies..
  # The actual algorith used can be found at:
  #
  # http://www.stoimen.com/blog/2012/10/01/computer-algorithms-topological-sort-of-a-graph/
  #
  edges = [(p["package"], d) for p in specs.values() for d in p["requires"] ]
  L = [l for l in specs.values() if not l["requires"]]
  S = []
  while L:
    spec = L.pop(0)
    S.append(spec)
    nextVertex = [e[0] for e in edges if e[1] == spec["package"]]
    edges = [e for e in edges if e[1] != spec["package"]]
    hasPredecessors = set([m for e in edges for m in nextVertex if e[0] == m])
    withPredecessor = set(nextVertex) - hasPredecessors
    L += [specs[m] for m in withPredecessor]
  buildOrder = [s["package"] for s in S]

  # Date fields to substitute: they are zero-padded
  now = datetime.now()
  nowKwds = { "year": str(now.year),
              "month": str(now.month).zfill(2),
              "day": str(now.day).zfill(2),
              "hour": str(now.hour).zfill(2) }

  # Check if any of the packages can be picked up from a local checkout
  develCandidates = [basename(d) for d in glob("*") if os.path.isdir(d)]
  develCandidatesUpper = [basename(d).upper() for d in glob("*") if os.path.isdir(d)]
  develPkgs = [p for p in buildOrder
               if p in develCandidates and p not in args.noDevel]
  develPkgsUpper = [(p, p.upper()) for p in buildOrder
                    if p.upper() in develCandidatesUpper and p not in args.noDevel]
  if set(develPkgs) != set(x for (x, y) in develPkgsUpper):
    return (error, format("The following development packages have wrong spelling: %(pkgs)s.\n"
                          "Please check your local checkout and adapt to the correct one indicated.",
                          pkgs=", ".join(set(x.strip() for (x,y) in develPkgsUpper) - set(develPkgs))), 1)

  if buildOrder:
    banner("Packages will be built in the following order:\n - %s",
           "\n - ".join(x+" (development package)" if x in develPkgs else "%s@%s" % (x, specs[x]["tag"])
                        for x in buildOrder if x != "defaults-release"))

  if develPkgs:
    banner("You have packages in development mode.\n"
           "This means their source code can be freely modified under:\n\n"
           "  %s/<package_name>\n\n"
           "%sBuild does not automatically update such packages to avoid work loss.\n"
           "In most cases this is achieved by doing in the package source directory:\n\n"
           "  git pull --rebase\n",
           os.getcwd(), star())

  # Clone/update repos
  import concurrent.futures
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    def downloadTask(p):
      updateReferenceRepoSpec(args.referenceSources, p, specs[p], args.fetchRepos, not args.docker)

      # Retrieve git heads
      cmd = "git ls-remote --heads %s" % (specs[p].get("reference", specs[p]["source"]))
      if specs[p]["package"] in develPkgs:
         specs[p]["source"] = join(os.getcwd(), specs[p]["package"])
         cmd = "git ls-remote --heads %s" % specs[p]["source"]
      debug("Executing %s", cmd)
      err, output = getStatusOutputBash(cmd)
      if err:
        raise RuntimeError("Error on '%s': %s" % (cmd, output))
      specs[p]["git_heads"] = output.split("\n")
      return "ok"
    future_to_download = {executor.submit(downloadTask, p): p for p in [p for p in buildOrder if "source" in specs[p]]}
    for future in concurrent.futures.as_completed(future_to_download):
        futurePackage = future_to_download[future]
        try:
            data = future.result()
        except Exception as exc:
            raise RuntimeError("Error on fetching '%r'. Aborting." % futurePackage)
        else:
            debug("%r package updated: %s", futurePackage, data)

  # Resolve the tag to the actual commit ref
  for p in buildOrder:
    spec = specs[p]
    spec["commit_hash"] = "0"
    develPackageBranch = ""
    if "source" in spec:
      # Tag may contain date params like %(year)s, %(month)s, %(day)s, %(hour).
      spec["tag"] = format(spec["tag"], **nowKwds)
      # By default we assume tag is a commit hash. We then try to find
      # out if the tag is actually a branch and we use the tip of the branch
      # as commit_hash. Finally if the package is a development one, we use the
      # name of the branch as commit_hash.
      spec["commit_hash"] = spec["tag"]
      for head in spec["git_heads"]:
        if head.endswith("refs/heads/{0}".format(spec["tag"])) or spec["package"] in develPkgs:
          spec["commit_hash"] = head.split("\t", 1)[0]
          # We are in development mode, we need to rebuild if the commit hash
          # is different and if there are extra changes on to.
          if spec["package"] in develPkgs:
            # Devel package: we get the commit hash from the checked source, not from remote.
            cmd = "cd %s && git rev-parse HEAD" % spec["source"]
            err, out = getstatusoutput(cmd)
            dieOnError(err, "Unable to detect current commit hash.")
            spec["commit_hash"] = out.strip()
            cmd = "cd %s && git diff -r HEAD && git status --porcelain" % spec["source"]
            h = Hasher()
            err = execute(cmd, lambda s, *a: h(s % a))
            debug("Command %s returned %d", cmd, err)
            dieOnError(err, "Unable to detect source code changes.")
            spec["devel_hash"] = spec["commit_hash"] + h.hexdigest()
            cmd = "cd %s && git rev-parse --abbrev-ref HEAD" % spec["source"]
            err, out = getstatusoutput(cmd)
            if out == "HEAD":
              err, out = getstatusoutput("cd %s && git rev-parse HEAD" % spec["source"])
              out = out[0:10]
            if err:
              return (error, "Error, unable to lookup changes in development package %s. Is it a git clone?" % spec["source"], 1)
            develPackageBranch = out.replace("/", "-")
            spec["tag"] = args.develPrefix if "develPrefix" in args else develPackageBranch
            spec["commit_hash"] = "0"
          break

    # Version may contain date params like tag, plus %(commit_hash)s,
    # %(short_hash)s and %(tag)s.
    defaults_upper = args.defaults != "release" and "_" + args.defaults.upper().replace("-", "_") or ""
    spec["version"] = format(spec["version"],
                             commit_hash=spec["commit_hash"],
                             short_hash=spec["commit_hash"][0:10],
                             tag=spec["tag"],
                             branch_basename = branch_basename,
                             branch_stream = branch_stream or spec["tag"],
                             tag_basename=basename(spec["tag"]),
                             defaults_upper=defaults_upper,
                             **nowKwds)

    if spec["package"] in develPkgs and "develPrefix" in args and args.develPrefix != "ali-master":
      spec["version"] = args.develPrefix

  # Decide what is the main package we are building and at what commit.
  #
  # We emit an event for the main package, when encountered, so that we can use
  # it to index builds of the same hash on different architectures. We also
  # make sure add the main package and it's hash to the debug log, so that we
  # can always extract it from it.
  # If one of the special packages is in the list of packages to be built,
  # we use it as main package, rather than the last one.
  if not buildOrder:
    return (banner, "Nothing to be done.", 0)
  mainPackage = buildOrder[-1]
  mainHash = specs[mainPackage]["commit_hash"]

  debug("Main package is %s@%s", mainPackage, mainHash)
  if args.debug:
    logger_handler.setFormatter(
        LogFormatter("%%(asctime)s:%%(levelname)s:%s:%s: %%(message)s" %
                     (mainPackage, args.develPrefix if "develPrefix" in args else mainHash[0:8])))

  # Now that we have the main package set, we can print out Useful information
  # which we will be able to associate with this build. Also lets make sure each package
  # we need to build can be built with the current default.
  for p in buildOrder:
    spec = specs[p]
    if "source" in spec:
      debug("Commit hash for %s@%s is %s", spec["source"], spec["tag"], spec["commit_hash"])

  # We recursively calculate the full set of requires "full_requires"
  # including build_requires and the subset of them which are needed at
  # runtime "full_runtime_requires".
  for p in buildOrder:
    spec = specs[p]
    todo = [p]
    spec["full_requires"] = []
    spec["full_runtime_requires"] = []
    spec["full_build_requires"] = []
    while todo:
      i = todo.pop(0)
      requires = specs[i].get("requires", [])
      runTimeRequires = specs[i].get("runtime_requires", [])
      buildRequires = specs[i].get("build_requires", [])
      spec["full_requires"] += requires
      spec["full_runtime_requires"] += runTimeRequires
      spec["full_build_requires"] += buildRequires
      todo += requires
    spec["full_requires"] = set(spec["full_requires"])
    spec["full_runtime_requires"] = set(spec["full_runtime_requires"])
    # If something requires or runtime_requires a package, then it's not 
    # a build_requires only anymore, so we drop it from the list.
    spec["full_build_requires"] = set(spec["full_build_requires"]) - spec["full_runtime_requires"]

  debug("We will build packages in the following order: %s", " ".join(buildOrder))
  if args.dryRun:
    return (info, "--dry-run / -n specified. Not building.", 0)

  # We now iterate on all the packages, making sure we build correctly every
  # single one of them. This is done this way so that the second time we run we
  # can check if the build was consistent and if it is, we bail out.
  packageIterations = 0
  report_event("install",
               format("%(p)s disabled=%(dis)s devel=%(dev)s system=%(sys)s own=%(own)s deps=%(deps)s",
                      p=args.pkgname,
                      dis=",".join(sorted(args.disable)),
                      dev=",".join(sorted(develPkgs)),
                      sys=",".join(sorted(systemPackages)),
                      own=",".join(sorted(ownPackages)),
                      deps=",".join(buildOrder[:-1])
                     ),
               args.architecture)

  while buildOrder:
    packageIterations += 1
    if packageIterations > 20:
      return (error, "Too many attempts at building %s. Something wrong with the repository?" % spec["package"], 1)
    p = buildOrder[0]
    spec = specs[p]
    if args.debug:
      logger_handler.setFormatter(
          LogFormatter("%%(asctime)s:%%(levelname)s:%s:%s:%s: %%(message)s" %
                       (mainPackage, p, args.develPrefix if "develPrefix" in args else mainHash[0:8])))

    # Calculate the hashes. We do this in build order so that we can guarantee
    # that the hashes of the dependencies are calculated first. Do this inside
    # the main build loop to make sure that our dependencies have been assigned
    # a single, definitive hash.
    debug("Calculating hash.")
    debug("spec = %r", spec)
    debug("develPkgs = %r", develPkgs)
    storeHashes(p, specs, isDevelPkg=p in develPkgs,
                considerRelocation=args.architecture.startswith("osx"))
    debug("Hashes for recipe %s are %s (remote), %s (local)",
          p, spec["remote_revision_hash"], spec["local_revision_hash"])

    # This adds to the spec where it should find, locally or remotely the
    # various tarballs and links.
    pkgSpec = {
      "workDir": workDir,
      "package": spec["package"],
      "version": spec["version"],
      "remote_revision_hash": spec["remote_revision_hash"],
      "remote_prefix": spec["remote_revision_hash"][0:2],
      "local_revision_hash": spec["local_revision_hash"],
      "local_prefix": spec["local_revision_hash"][0:2],
      "architecture": args.architecture
    }
    spec.update({k: v % pkgSpec for k, v in (
      ("remote_store_path", "TARS/%(architecture)s/store/%(remote_prefix)s/%(remote_revision_hash)s"),
      ("remote_links_path", "TARS/%(architecture)s/%(package)s"),
      ("remote_tar_hash_dir",
       "%(workDir)s/TARS/%(architecture)s/store/%(remote_prefix)s/%(remote_revision_hash)s"),
      ("local_tar_hash_dir",
       "%(workDir)s/TARS/%(architecture)s/store/%(local_prefix)s/%(local_revision_hash)s"),
      ("remote_tar_link_dir", "%(workDir)s/TARS/%(architecture)s/%(package)s"),
    )})

    if spec["package"] in develPkgs and getattr(syncHelper, "writeStore", None):
      warning("Disabling remote write store from now since %s is a development package.", spec["package"])
      syncHelper.writeStore = ""

    # Since we can execute this multiple times for a given package, in order to
    # ensure consistency, we need to reset things and make them pristine.
    spec.pop("revision", None)

    debug("Updating from tarballs")
    # If we arrived here it really means we have a tarball which was created
    # using the same recipe. We will use it as a cache for the build. This means
    # that while we will still perform the build process, rather than
    # executing the build itself we will:
    #
    # - Unpack it in a temporary place.
    # - Invoke the relocation specifying the correct work_dir and the
    #   correct path which should have been used.
    # - Move the version directory to its final destination, including the
    #   correct revision.
    # - Repack it and put it in the store with the
    #
    # this will result in a new package which has the same binary contents of
    # the old one but where the relocation will work for the new dictory. Here
    # we simply store the fact that we can reuse the contents of cachedTarball.
    syncHelper.syncToLocal(p, spec)

    # Decide how it should be called, based on the hash and what is already
    # available.
    debug("Checking for packages already built.")
    linksGlob = format("%(w)s/TARS/%(a)s/%(p)s/%(p)s-%(v)s-*.%(a)s.tar.gz",
                       w=workDir,
                       a=args.architecture,
                       p=spec["package"],
                       v=spec["version"])
    debug("Glob pattern used: %s", linksGlob)
    packages = glob(linksGlob)
    # In case there is no installed software, revision is 1
    # If there is already an installed package:
    # - Remove it if we do not know its hash
    # - Use the latest number in the version, to decide its revision
    debug("Packages already built using this version\n%s", "\n".join(packages))

    # Calculate the build_family for the package
    #
    # If the package is a devel package, we need to associate it a devel
    # prefix, either via the -z option or using its checked out branch. This
    # affects its build hash.
    #
    # Moreover we need to define a global "buildFamily" which is used
    # to tag all the packages incurred in the build, this way we can have
    # a latest-<buildFamily> link for all of them an we will not incur in the
    # flip - flopping described in https://github.com/alisw/alibuild/issues/325.
    develPrefix = ""
    possibleDevelPrefix = getattr(args, "develPrefix", develPackageBranch)
    if spec["package"] in develPkgs:
      develPrefix = possibleDevelPrefix

    if possibleDevelPrefix:
      spec["build_family"] = "%s-%s" % (possibleDevelPrefix, args.defaults)
    else:
      spec["build_family"] = args.defaults
    if spec["package"] == mainPackage:
      mainBuildFamily = spec["build_family"]

    busyRevisions = set()
    # We can tell that the remote store is read-only if it has an empty or
    # no writeStore property. See below for explanation of why we need this.
    revisionPrefix = "" if getattr(syncHelper, "writeStore", "") else "local"
    for d in packages:
      realPath = readlink(d)
      matcher = format("../../%(a)s/store/[0-9a-f]{2}/([0-9a-f]*)/%(p)s-%(v)s-((?:local)?[0-9]*).%(a)s.tar.gz$",
                       a=args.architecture,
                       p=spec["package"],
                       v=spec["version"])
      m = re.match(matcher, realPath)
      if not m:
        continue
      h, revision = m.groups()

      if not (("local" in revision and h == spec["local_revision_hash"]) or
              ("local" not in revision and h == spec["remote_revision_hash"])):
        # This tarball's hash doesn't match what we need. Remember that its
        # revision number is taken, in case we assign our own later.
        if revision.startswith(revisionPrefix) and revision[len(revisionPrefix):].isdigit():
          # Strip revisionPrefix; the rest is an integer. Convert it to an int
          # so we can get a sensible max() existing revision below.
          busyRevisions.add(int(revision[len(revisionPrefix):]))
        continue

      # Don't re-use local revisions when we have a read-write store, so that
      # packages we'll upload later don't depend on local revisions.
      if getattr(syncHelper, "writeStore", False) and "local" in revision:
        continue

      # If we have an hash match, we use the old revision for the package
      # and we do not need to build it.
      spec["revision"] = revision
      if spec["package"] in develPkgs and "incremental_recipe" in spec:
        spec["obsolete_tarball"] = d
      else:
        debug("Package %s with hash %s is already found in %s. Not building.", p, h, d)
        src = format("%(v)s-%(r)s",
                     w=workDir,
                     v=spec["version"],
                     r=spec["revision"])
        dst1 = format("%(w)s/%(a)s/%(p)s/latest-%(bf)s",
                      w=workDir,
                      a=args.architecture,
                      p=spec["package"],
                      bf=spec["build_family"])
        dst2 = format("%(w)s/%(a)s/%(p)s/latest",
                      w=workDir,
                      a=args.architecture,
                      p=spec["package"])

        getstatusoutput("ln -snf %s %s" % (src, dst1))
        getstatusoutput("ln -snf %s %s" % (src, dst2))
        info("Using cached build for %s", p)
      break

    # If we aren't using an existing revision, assign the next free revision
    # to this package. If we're not uploading it, name it localN to avoid
    # interference with the remote store -- in case this package is built
    # somewhere else, the next revision N might be assigned there, and would
    # conflict with our revision N.
    if "revision" not in spec:
      # The code finding busyRevisions above already ensures that revision
      # numbers start with revisionPrefix, and has left us plain ints.
      spec["revision"] = revisionPrefix + str(
        min(set(range(1, max(busyRevisions) + 2)) - busyRevisions)
        if busyRevisions else 1)

    # Now we know whether we're using a local or remote package, so we can set
    # the proper hash and tarball directory.
    if spec["revision"].startswith("local"):
      spec["hash"] = spec["local_revision_hash"]
      spec["tar_hash_dir"] = spec["local_tar_hash_dir"]
    else:
      spec["hash"] = spec["remote_revision_hash"]
      spec["tar_hash_dir"] = spec["remote_tar_hash_dir"]
    spec["old_devel_hash"] = readHashFile(join(
      workDir, "BUILD", spec["hash"], spec["package"], ".build_succeeded"))

    # Recreate symlinks to this development package builds.
    if spec["package"] in develPkgs:
      debug("Creating symlinks to builds of devel package %s", spec["package"])
      cmd = format("ln -snf %(pkgHash)s %(wd)s/BUILD/%(pkgName)s-latest",
                   wd=workDir,
                   pkgName=spec["package"],
                   pkgHash=spec["hash"])
      if develPrefix:
        cmd += format(" && ln -snf %(pkgHash)s %(wd)s/BUILD/%(pkgName)s-latest-%(devPrefix)s",
                      wd=workDir,
                      pkgName=spec["package"],
                      pkgHash=spec["hash"],
                      devPrefix=develPrefix)
      err = execute(cmd)
      debug("Command %s returned %d", cmd, err)
      # Last package built gets a "latest" mark.
      cmd = format("ln -snf %(pkgVersion)s-%(pkgRevision)s %(wd)s/%(arch)s/%(pkgName)s/latest",
                   wd=workDir,
                   arch=args.architecture,
                   pkgName=spec["package"],
                   pkgVersion=spec["version"],
                   pkgRevision=spec["revision"])
      # Latest package built for a given devel prefix gets a "latest-%(family)s" mark.
      if spec["build_family"]:
        cmd += format(" && ln -snf %(pkgVersion)s-%(pkgRevision)s %(wd)s/%(arch)s/%(pkgName)s/latest-%(family)s",
                      wd=workDir,
                      arch=args.architecture,
                      pkgName=spec["package"],
                      pkgVersion=spec["version"],
                      pkgRevision=spec["revision"],
                      family=spec["build_family"])
      err = execute(cmd)
      debug("Command %s returned %d", cmd, err)

    # Check if this development package needs to be rebuilt.
    if spec["package"] in develPkgs:
      debug("Checking if devel package %s needs rebuild", spec["package"])
      if spec["devel_hash"]+spec["deps_hash"] == spec["old_devel_hash"]:
        info("Development package %s does not need rebuild", spec["package"])
        buildOrder.pop(0)
        continue

    # Now that we have all the information about the package we want to build, let's
    # check if it wasn't built / unpacked already.
    hashFile = "%s/%s/%s/%s-%s/.build-hash" % (workDir,
                                               args.architecture,
                                               spec["package"],
                                               spec["version"],
                                               spec["revision"])
    fileHash = readHashFile(hashFile)
    # Development packages have their own rebuild-detection logic above.
    # spec["hash"] is only useful here for regular packages.
    if fileHash == spec["hash"] and spec["package"] not in develPkgs:
      # If we get here, we know we are in sync with whatever remote store.  We
      # can therefore create a directory which contains all the packages which
      # were used to compile this one.
      debug("Package %s was correctly compiled. Moving to next one.", spec["package"])
      # If using incremental builds, next time we execute the script we need to remove
      # the placeholders which avoid rebuilds.
      if spec["package"] in develPkgs and "incremental_recipe" in spec:
        unlink(hashFile)
      if "obsolete_tarball" in spec:
        unlink(realpath(spec["obsolete_tarball"]))
        unlink(spec["obsolete_tarball"])
      # We need to create 2 sets of links, once with the full requires,
      # once with only direct dependencies, since that's required to
      # register packages in Alien.
      createDistLinks(spec, specs, args, "dist", "full_requires")
      createDistLinks(spec, specs, args, "dist-direct", "requires")
      createDistLinks(spec, specs, args, "dist-runtime", "full_runtime_requires")
      buildOrder.pop(0)
      packageIterations = 0
      # We can now delete the INSTALLROOT and BUILD directories,
      # assuming the package is not a development one. We also can
      # delete the SOURCES in case we have aggressive-cleanup enabled.
      if not spec["package"] in develPkgs and args.autoCleanup:
        cleanupDirs = [format("%(w)s/BUILD/%(h)s",
                              w=workDir,
                              h=spec["hash"]),
                       format("%(w)s/INSTALLROOT/%(h)s",
                              w=workDir,
                              h=spec["hash"])]
        if args.aggressiveCleanup:
          cleanupDirs.append(format("%(w)s/SOURCES/%(p)s",
                                    w=workDir,
                                    p=spec["package"]))
        debug("Cleaning up:\n%s", "\n".join(cleanupDirs))

        for d in cleanupDirs:
          shutil.rmtree(d.encode("utf8"), True)
        try:
          unlink(format("%(w)s/BUILD/%(p)s-latest",
                 w=workDir, p=spec["package"]))
          if "develPrefix" in args:
            unlink(format("%(w)s/BUILD/%(p)s-latest-%(dp)s",
                   w=workDir, p=spec["package"], dp=args.develPrefix))
        except:
          pass
        try:
          rmdir(format("%(w)s/BUILD",
                w=workDir, p=spec["package"]))
          rmdir(format("%(w)s/INSTALLROOT",
                w=workDir, p=spec["package"]))
        except:
          pass
      continue

    if fileHash != "0":
      debug("Mismatch between local area (%s) and the one which I should build (%s). Redoing.",
            fileHash, spec["hash"])
    # shutil.rmtree under Python 2 fails when hashFile is unicode and the
    # directory contains files with non-ASCII names, e.g. Golang/Boost.
    shutil.rmtree(dirname(hashFile).encode("utf-8"), True)

    debug("Looking for cached tarball in %s", spec["tar_hash_dir"])
    # FIXME: I should get the tar_hash_dir updated with server at this point.
    #        It does not really matter that the symlinks are ok at this point
    #        as I only used the tarballs as reusable binary blobs.
    spec["cachedTarball"] = ""
    if not spec["package"] in develPkgs:
      tarballs = glob(join(spec["tar_hash_dir"], "*gz"))
      spec["cachedTarball"] = tarballs[0] if len(tarballs) else ""
      debug("Found tarball in %s" % spec["cachedTarball"]
            if spec["cachedTarball"] else "No cache tarballs found")

    # Generate the part which sources the environment for all the dependencies.
    # Notice that we guarantee that a dependency is always sourced before the
    # parts depending on it, but we do not guaranteed anything for the order in
    # which unrelated components are activated.
    dependencies = "ALIBUILD_ARCH_PREFIX=\"${ALIBUILD_ARCH_PREFIX:-%s}\"\n" % args.architecture
    dependenciesInit = "echo ALIBUILD_ARCH_PREFIX=\"\${ALIBUILD_ARCH_PREFIX:-%s}\" >> $INSTALLROOT/etc/profile.d/init.sh\n" % args.architecture
    for dep in spec.get("requires", []):
      depSpec = specs[dep]
      depInfo = {
        "architecture": args.architecture,
        "package": dep,
        "version": depSpec["version"],
        "revision": depSpec["revision"],
        "bigpackage": dep.upper().replace("-", "_")
      }
      dependencies += format("[ -z ${%(bigpackage)s_REVISION+x} ] && source \"$WORK_DIR/$ALIBUILD_ARCH_PREFIX/%(package)s/%(version)s-%(revision)s/etc/profile.d/init.sh\"\n",
                             **depInfo)
      dependenciesInit += format('echo [ -z \${%(bigpackage)s_REVISION+x} ] \&\& source \${WORK_DIR}/\${ALIBUILD_ARCH_PREFIX}/%(package)s/%(version)s-%(revision)s/etc/profile.d/init.sh >> \"$INSTALLROOT/etc/profile.d/init.sh\"\n',
                             **depInfo)
    dependenciesDict = {}
    for dep in spec.get("full_requires", []):
      depSpec = specs[dep]
      depInfo = {
        "architecture": args.architecture,
        "package": dep,
        "version": depSpec["version"],
        "revision": depSpec["revision"],
        "hash": depSpec["hash"]
      }
      dependenciesDict[dep] = depInfo
    dependenciesJSON = str(dependenciesDict)
      
    # Generate the part which creates the environment for the package.
    # This can be either variable set via the "env" keyword in the metadata
    # or paths which get appended via the "append_path" one.
    # By default we append LD_LIBRARY_PATH, PATH
    environment = ""
    dieOnError(not isinstance(spec.get("env", {}), dict),
               "Tag `env' in %s should be a dict." % p)
    for key,value in spec.get("env", {}).items():
      if key == "DYLD_LIBRARY_PATH":
        continue
      environment += format("echo 'export %(key)s=\"%(value)s\"' >> $INSTALLROOT/etc/profile.d/init.sh\n",
                            key=key,
                            value=value)
    basePath = "%s_ROOT" % p.upper().replace("-", "_")

    pathDict = spec.get("append_path", {})
    dieOnError(not isinstance(pathDict, dict),
               "Tag `append_path' in %s should be a dict." % p)
    for pathName,pathVal in pathDict.items():
      pathVal = isinstance(pathVal, list) and pathVal or [ pathVal ]
      if pathName == "DYLD_LIBRARY_PATH":
        continue
      environment += format("\ncat << \EOF >> \"$INSTALLROOT/etc/profile.d/init.sh\"\nexport %(key)s=$%(key)s:%(value)s\nEOF",
                            key=pathName,
                            value=":".join(pathVal))

    # Same thing, but prepending the results so that they win against system ones.
    defaultPrependPaths = { "LD_LIBRARY_PATH": "$%s/lib" % basePath,
                            "PATH": "$%s/bin" % basePath }
    pathDict = spec.get("prepend_path", {})
    dieOnError(not isinstance(pathDict, dict),
               "Tag `prepend_path' in %s should be a dict." % p)
    for pathName,pathVal in pathDict.items():
      pathDict[pathName] = isinstance(pathVal, list) and pathVal or [ pathVal ]
    for pathName,pathVal in defaultPrependPaths.items():
      pathDict[pathName] = [ pathVal ] + pathDict.get(pathName, [])
    for pathName,pathVal in pathDict.items():
      if pathName == "DYLD_LIBRARY_PATH":
        continue
      environment += format("\ncat << \EOF >> \"$INSTALLROOT/etc/profile.d/init.sh\"\nexport %(key)s=%(value)s${%(key)s+:$%(key)s}\nEOF",
                            key=pathName,
                            value=":".join(pathVal))

    # The actual build script.
    referenceStatement = ""
    if "reference" in spec:
      referenceStatement = "export GIT_REFERENCE=${GIT_REFERENCE_OVERRIDE:-%s}/%s" % (dirname(spec["reference"]), basename(spec["reference"]))

    partialCloneStatement = ""
    if partialCloneFilter and not args.docker:
      partialCloneStatement = "export GIT_PARTIAL_CLONE_FILTER='--filter=blob:none'"

    debug("spec = %r", spec)

    cmd_raw = ""
    try:
      fp = open(dirname(realpath(__file__))+'/build_template.sh', 'r')
      cmd_raw = fp.read()
      fp.close()
    except:
      from pkg_resources import resource_string
      cmd_raw = resource_string("alibuild_helpers", 'build_template.sh')

    source = spec.get("source", "")
    # Shortend the commit hash in case it's a real commit hash and not simply
    # the tag.
    commit_hash = spec["commit_hash"]
    if spec["tag"] != spec["commit_hash"]:
      commit_hash = spec["commit_hash"][0:10]

    # Split the source in two parts, sourceDir and sourceName.  This is done so
    # that when we use Docker we can replace sourceDir with the correct
    # container path, if required.  No changes for what concerns the standard
    # bash builds, though.
    if args.docker:
      cachedTarball = re.sub("^" + workDir, "/sw", spec["cachedTarball"])
    else:
      cachedTarball = spec["cachedTarball"]


    cmd = format(cmd_raw,
                 dependencies=dependencies,
                 dependenciesInit=dependenciesInit,
                 dependenciesJSON=dependenciesJSON,
                 develPrefix=develPrefix,
                 environment=environment,
                 workDir=workDir,
                 configDir=abspath(args.configDir),
                 incremental_recipe=spec.get("incremental_recipe", ":"),
                 sourceDir=source and (dirname(source) + "/") or "",
                 sourceName=source and basename(source) or "",
                 referenceStatement=referenceStatement,
                 partialCloneStatement=partialCloneStatement,
                 requires=" ".join(spec["requires"]),
                 build_requires=" ".join(spec["build_requires"]),
                 runtime_requires=" ".join(spec["runtime_requires"])
                )

    commonPath = "%s/%%s/%s/%s/%s-%s" % (workDir,
                                         args.architecture,
                                         spec["package"],
                                         spec["version"],
                                         spec["revision"])
    scriptDir = commonPath % "SPECS"

    err, out = getstatusoutput("mkdir -p %s" % scriptDir)
    writeAll("%s/build.sh" % scriptDir, cmd)
    writeAll("%s/%s.sh" % (scriptDir, spec["package"]), spec["recipe"])

    banner("Building %s@%s", spec["package"],
           args.develPrefix if "develPrefix" in args and spec["package"] in develPkgs
           else spec["version"])
    # Define the environment so that it can be passed up to the
    # actual build script
    buildEnvironment = [
      ("ARCHITECTURE", args.architecture),
      ("BUILD_REQUIRES", " ".join(spec["build_requires"])),
      ("CACHED_TARBALL", cachedTarball),
      ("CAN_DELETE", args.aggressiveCleanup and "1" or ""),
      ("COMMIT_HASH", commit_hash),
      ("DEPS_HASH", spec.get("deps_hash", "")),
      ("DEVEL_HASH", spec.get("devel_hash", "")),
      ("DEVEL_PREFIX", develPrefix),
      ("BUILD_FAMILY", spec["build_family"]),
      ("GIT_COMMITTER_NAME", "unknown"),
      ("GIT_COMMITTER_EMAIL", "unknown"),
      ("GIT_TAG", spec["tag"]),
      ("MY_GZIP", gzip()),
      ("MY_TAR", tar()),
      ("INCREMENTAL_BUILD_HASH", spec.get("incremental_hash", "0")),
      ("JOBS", args.jobs),
      ("PKGHASH", spec["hash"]),
      ("PKGNAME", spec["package"]),
      ("PKGREVISION", spec["revision"]),
      ("PKGVERSION", spec["version"]),
      ("RELOCATE_PATHS", " ".join(spec.get("relocate_paths", []))),
      ("REQUIRES", " ".join(spec["requires"])),
      ("RUNTIME_REQUIRES", " ".join(spec["runtime_requires"])),
      ("FULL_RUNTIME_REQUIRES", " ".join(spec["full_runtime_requires"])),
      ("FULL_BUILD_REQUIRES", " ".join(spec["full_build_requires"])),
      ("FULL_REQUIRES", " ".join(spec["full_requires"])),
      ("WRITE_REPO", spec.get("write_repo", source)),
    ]
    # Add the extra environment as passed from the command line.
    buildEnvironment += [e.partition('=')[::2] for e in args.environment]
    # In case the --docker options is passed, we setup a docker container which
    # will perform the actual build. Otherwise build as usual using bash.
    if args.docker:
      additionalEnv = ""
      additionalVolumes = ""
      develVolumes = ""
      mirrorVolume = "reference" in spec and " -v %s:/mirror" % dirname(spec["reference"]) or ""
      overrideSource = source.startswith("/") and "-e SOURCE0_DIR_OVERRIDE=/" or ""

      for devel in develPkgs:
        develVolumes += " -v $PWD/`readlink %s || echo %s`:/%s:ro " % (devel, devel, devel)
      for env in buildEnvironment:
        additionalEnv += " -e %s='%s' " % env
      for volume in args.volumes:
        additionalVolumes += " -v %s " % volume
      dockerWrapper = format("docker run --rm"
              " --user $(id -u):$(id -g)"
              " -v %(workdir)s:/sw"
              " -v %(scriptDir)s/build.sh:/build.sh:ro"
              " %(mirrorVolume)s"
              " %(develVolumes)s"
              " %(additionalEnv)s"
              " %(additionalVolumes)s"
              " -e GIT_REFERENCE_OVERRIDE=/mirror"
              " %(overrideSource)s"
              " -e WORK_DIR_OVERRIDE=/sw"
              " %(image)s"
              " -c \"%(bash)s -e -x /build.sh\"",
              additionalEnv=additionalEnv,
              additionalVolumes=additionalVolumes,
              bash=BASH,
              develVolumes=develVolumes,
              workdir=abspath(args.workDir),
              image=dockerImage,
              mirrorVolume=mirrorVolume,
              overrideSource=overrideSource,
              scriptDir=scriptDir)
      debug("Docker command: %s", dockerWrapper)
      err = execute(dockerWrapper)
    else:
      progress = ProgressPrint("%s is being built (use --debug for full output)" % spec["package"])
      for k,v in buildEnvironment:
        os.environ[k] = str(v)
      err = execute("%s -e -x %s/build.sh 2>&1" % (BASH, scriptDir),
                    printer=debug if args.debug or not sys.stdout.isatty() else progress)
      progress.end("failed" if err else "ok", err)
    report_event("BuildError" if err else "BuildSuccess",
                 spec["package"],
                 format("%(a)s %(v)s %(c)s %(h)s",
                        a = args.architecture,
                        v = spec["version"],
                        c = spec["commit_hash"],
                        h = os.environ["ALIBUILD_ALIDIST_HASH"][0:10]))

    updatablePkgs = [ x for x in spec["requires"] if x in develPkgs ]
    if spec["package"] in develPkgs:
      updatablePkgs.append(spec["package"])

    buildErrMsg = format("Error while executing %(sd)s/build.sh on `%(h)s'.\n"
                         "Log can be found in %(w)s/BUILD/%(p)s-latest%(devSuffix)s/log\n"
                         "Please upload it to CERNBox/Dropbox if you intend to request support.\n"
                         "Build directory is %(w)s/BUILD/%(p)s-latest%(devSuffix)s/%(p)s.",
                         h=socket.gethostname(),
                         sd=scriptDir,
                         w=abspath(args.workDir),
                         p=spec["package"],
                         devSuffix="-" + args.develPrefix
                                   if "develPrefix" in args and spec["package"] in develPkgs
                                   else "")
    if updatablePkgs:
      buildErrMsg += format("\n\n"
                            "Note that you have packages in development mode.\n"
                            "Devel sources are not updated automatically, you must do it by hand.\n"
                            "This problem might be due to one or more outdated devel sources.\n"
                            "To update all development packages required for this build "
                            "it is usually sufficient to do:\n%(updatablePkgs)s",
                            updatablePkgs="".join(["\n  ( cd %s && git pull --rebase )" % dp
                                                   for dp in updatablePkgs]))

    dieOnError(err, buildErrMsg)

    # Make sure not to upload local-only packages! These might have been
    # produced in a previous run with a read-only remote store.
    if spec["revision"].startswith("local"):
      continue   # Skip upload below.
    syncHelper.syncToRemote(p, spec)

  banner("Build of %s successfully completed on `%s'.\n"
         "Your software installation is at:"
         "\n\n  %s\n\n"
         "You can use this package by loading the environment:"
         "\n\n  alienv enter %s/latest-%s",
         mainPackage, socket.gethostname(),
         abspath(join(args.workDir, args.architecture)),
         mainPackage, mainBuildFamily)
  for x in develPkgs:
    banner("Build directory for devel package %s:\n%s/BUILD/%s-latest%s/%s",
           x, abspath(args.workDir), x, "-"+args.develPrefix if "develPrefix" in args else "", x)
  return (debug, "Everything done", 0)

