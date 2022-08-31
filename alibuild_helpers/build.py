from os.path import abspath, exists, basename, dirname, join, realpath
from os import makedirs, unlink, readlink, rmdir
from alibuild_helpers import __version__
from alibuild_helpers.analytics import report_event
from alibuild_helpers.log import debug, error, info, banner, warning
from alibuild_helpers.log import dieOnError
from alibuild_helpers.cmd import execute, getstatusoutput, DockerRunner, BASH, install_wrapper_script
from alibuild_helpers.utilities import star, prunePaths
from alibuild_helpers.utilities import resolve_store_path
from alibuild_helpers.utilities import format, parseDefaults, readDefaults
from alibuild_helpers.utilities import getPackageList
from alibuild_helpers.utilities import validateDefaults
from alibuild_helpers.utilities import Hasher
from alibuild_helpers.utilities import yamlDump
from alibuild_helpers.utilities import resolve_tag, resolve_version
from alibuild_helpers.git import git, clone_speedup_options
from alibuild_helpers.sync import (NoRemoteSync, HttpRemoteSync, S3RemoteSync,
                                   Boto3RemoteSync, RsyncRemoteSync)
import yaml
from alibuild_helpers.workarea import updateReferenceRepoSpec
from alibuild_helpers.log import logger_handler, LogFormatter, ProgressPrint
from datetime import datetime
from glob import glob
try:
  from collections import OrderedDict
except ImportError:
  from ordereddict import OrderedDict
try:
  from shlex import quote  # Python 3.3+
except ImportError:
  from pipes import quote  # Python 2.7

import concurrent.futures
import importlib
import socket
import os
import re
import shutil
import sys
import time


def writeAll(fn, txt):
  f = open(fn, "w")
  f.write(txt)
  f.close()


def readHashFile(fn):
  try:
    return open(fn).read().strip("\n")
  except IOError:
    return "0"


def update_git_repos(args, specs, buildOrder, develPkgs):
    """Update and/or fetch required git repositories in parallel.

    If any repository fails to be fetched, then it is retried, while allowing the
    user to input their credentials if required.
    """

    def update_repo(package, git_prompt):
        updateReferenceRepoSpec(args.referenceSources, package, specs[package],
                                fetch=args.fetchRepos,
                                usePartialClone=not args.docker,
                                allowGitPrompt=git_prompt)

        # Retrieve git heads
        cmd = ["ls-remote", "--heads", "--tags"]
        if package in develPkgs:
            specs[package]["source"] = \
                os.path.join(os.getcwd(), specs[package]["package"])
            cmd.append(specs[package]["source"])
        else:
            cmd.append(specs[package].get("reference", specs[package]["source"]))

        output = git(cmd, prompt=git_prompt)
        specs[package]["git_refs"] = {
            git_ref: git_hash for git_hash, sep, git_ref
            in (line.partition("\t") for line in output.splitlines()) if sep
        }

    requires_auth = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_download = {
          executor.submit(update_repo, package, git_prompt=False): package
          for package in buildOrder if "source" in specs[package]
        }
        for future in concurrent.futures.as_completed(future_to_download):
            futurePackage = future_to_download[future]
            try:
                future.result()
            except RuntimeError as exc:
                # Git failed. Let's assume this is because the user needs to
                # supply a password.
                debug("%r requires auth; will prompt later", futurePackage)
                requires_auth.add(futurePackage)
            except Exception as exc:
                raise RuntimeError("Error on fetching %r: %s. Aborting." %
                                   (futurePackage, exc))
            else:
                debug("%r package updated: %d refs found", futurePackage,
                      len(specs[futurePackage]["git_refs"]))

    # Now execute git commands for private packages one-by-one, so the user can
    # type their username and password without multiple prompts interfering.
    for package in requires_auth:
        banner("If prompted now, enter your username and password for %s below\n"
               "If you are prompted too often, see: "
               "https://alisw.github.io/alibuild/troubleshooting.html"
               "#alibuild-keeps-asking-for-my-password",
               specs[package]["source"])
        update_repo(package, git_prompt=True)
        debug("%r package updated: %d refs found", package,
              len(specs[package]["git_refs"]))


# Creates a directory in the store which contains symlinks to the package
# and its direct / indirect dependencies
def createDistLinks(spec, specs, args, syncHelper, repoType, requiresType):
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

  syncHelper.syncDistLinksToRemote(target)


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

  # For now, all the hashers share data -- they'll be split below.
  h_all = Hasher()

  if spec.get("force_rebuild", False):
    h_all(str(time.time()))

  def hash_data_for_key(key):
    if sys.version_info[0] < 3 and key in spec and isinstance(spec[key], OrderedDict):
      # Python 2: use YAML dict order to prevent changing hashes
      return str(yaml.safe_load(yamlDump(spec[key])))
    else:
      return str(spec.get(key, "none"))

  for x in ("recipe", "version", "package"):
    h_all(hash_data_for_key(x))

  # commit_hash could be a commit hash (if we're not building a tag, but
  # instead e.g. a branch or particular commit specified by its hash), or it
  # could be a tag name (if we're building a tag). We want to calculate the
  # hash for both cases, so that if we build some commit, we want to be able to
  # reuse tarballs from other builds of the same commit, even if it was
  # referred to differently in the other build.
  debug("Base git ref is %s", spec["commit_hash"])
  h_default = h_all.copy()
  h_default(spec["commit_hash"])
  try:
    # If spec["commit_hash"] is a tag, get the actual git commit hash.
    real_commit_hash = spec["git_refs"]["refs/tags/" + spec["commit_hash"]]
  except KeyError:
    # If it's not a tag, assume it's an actual commit hash.
    real_commit_hash = spec["commit_hash"]
  # Get any other git tags that refer to the same commit. We do not consider
  # branches, as their heads move, and that will cause problems.
  debug("Real commit hash is %s, storing alternative", real_commit_hash)
  h_real_commit = h_all.copy()
  h_real_commit(real_commit_hash)
  h_alternatives = [(spec.get("tag", "0"), spec["commit_hash"], h_default),
                    (spec.get("tag", "0"), real_commit_hash, h_real_commit)]
  for ref, git_hash in spec.get("git_refs", {}).items():
    if ref.startswith("refs/tags/") and git_hash == real_commit_hash:
      tag_name = ref[len("refs/tags/"):]
      debug("Tag %s also points to %s, storing alternative",
            tag_name, real_commit_hash)
      hasher = h_all.copy()
      hasher(tag_name)
      h_alternatives.append((tag_name, git_hash, hasher))

  # Now that we've split the hasher with the real commit hash off from the ones
  # with a tag name, h_all has to add the data to all of them separately.
  def h_all(data):  # pylint: disable=function-redefined
    for _, _, hasher in h_alternatives:
      hasher(data)

  for x in ("env", "append_path", "prepend_path"):
    h_all(hash_data_for_key(x))

  for tag, commit_hash, hasher in h_alternatives:
    # If the commit hash is a real hash, and not a tag, we can safely assume
    # that's unique, and therefore we can avoid putting the repository or the
    # name of the branch in the hash.
    if commit_hash == tag:
      hasher(spec.get("source", "none"))
      if "source" in spec:
        hasher(tag)

  dh = Hasher()
  for dep in spec.get("requires", []):
    # At this point, our dependencies have a single hash, local or remote, in
    # specs[dep]["hash"].
    hash_and_devel_hash = specs[dep]["hash"] + specs[dep].get("devel_hash", "")
    # If this package is a dev package, and it depends on another dev pkg, then
    # this package's hash shouldn't change if the other dev package was
    # changed, so that we can just rebuild this one incrementally.
    h_all(specs[dep]["hash"] if isDevelPkg else hash_and_devel_hash)
    # The deps_hash should always change, however, so we actually rebuild the
    # dependent package (even if incrementally).
    dh(hash_and_devel_hash)

  if isDevelPkg and "incremental_recipe" in spec:
    h_all(spec["incremental_recipe"])
    ih = Hasher()
    ih(spec["incremental_recipe"])
    spec["incremental_hash"] = ih.hexdigest()
  elif isDevelPkg:
    h_all(spec.get("devel_hash"))

  if considerRelocation and "relocate_paths" in spec:
    h_all("relocate:"+" ".join(sorted(spec["relocate_paths"])))

  spec["deps_hash"] = dh.hexdigest()
  spec["remote_revision_hash"] = h_default.hexdigest()
  # Store hypothetical hashes of this spec if we were building it using other
  # tags that refer to the same commit that we're actually building. These are
  # later used when fetching from the remote store. The "primary" hash should
  # be the first in the list, so it's checked first by the remote stores.
  spec["remote_hashes"] = [spec["remote_revision_hash"]] + \
    list({h.hexdigest() for _, _, h in h_alternatives} - {spec["remote_revision_hash"]})
  # The local hash must differ from the remote hash to avoid conflicts where
  # the remote has a package with the same hash as an existing local revision.
  h_all("local")
  spec["local_revision_hash"] = h_default.hexdigest()
  spec["local_hashes"] = [spec["local_revision_hash"]] + \
    list({h.hexdigest() for _, _, h, in h_alternatives} - {spec["local_revision_hash"]})


def better_tarball(spec, old, new):
  """Return which tarball we should prefer to reuse."""
  if not old: return new
  if not new: return old
  old_rev, old_hash, _ = old
  new_rev, new_hash, _ = new
  old_is_local, new_is_local = old_rev.startswith("local"), new_rev.startswith("local")
  # If one is local and one is remote, return the remote one.
  if old_is_local and not new_is_local: return new
  if new_is_local and not old_is_local: return old
  # Finally, return the one that appears in the list of hashes earlier.
  hashes = spec["local_hashes" if old_is_local else "remote_hashes"]
  return old if hashes.index(old_hash) < hashes.index(new_hash) else new


def doBuild(args, parser):
  if args.remoteStore.startswith("http"):
    syncHelper = HttpRemoteSync(args.remoteStore, args.architecture, args.workDir, args.insecure)
  elif args.remoteStore.startswith("s3://"):
    syncHelper = S3RemoteSync(args.remoteStore, args.writeStore,
                              args.architecture, args.workDir)
  elif args.remoteStore.startswith("b3://"):
    syncHelper = Boto3RemoteSync(args.remoteStore, args.writeStore,
                                 args.architecture, args.workDir)
  elif args.remoteStore:
    syncHelper = RsyncRemoteSync(args.remoteStore, args.writeStore, args.architecture, args.workDir)
  else:
    syncHelper = NoRemoteSync()

  packages = args.pkgname
  dockerImage = args.dockerImage if "dockerImage" in args else None
  specs = {}
  buildOrder = []
  workDir = abspath(args.workDir)
  prunePaths(workDir)

  if not exists(args.configDir):
    error('Cannot find %sdist recipes under directory "%s".\n'
          'Maybe you need to "cd" to the right directory or '
          'you forgot to run "%sBuild init"?',
          star(), args.configDir, star())
    return 1

  _, value = git(("symbolic-ref", "-q", "HEAD"), directory=args.configDir, check=False)
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

  os.environ["ALIBUILD_ALIDIST_HASH"] = git(("rev-parse", "HEAD"), directory=args.configDir)

  debug("Building for architecture %s", args.architecture)
  debug("Number of parallel builds: %d", args.jobs)
  debug("Using %sBuild from %sbuild@%s recipes in %sdist@%s",
        star(), star(), __version__, star(), os.environ["ALIBUILD_ALIDIST_HASH"])

  install_wrapper_script("git", workDir)

  with DockerRunner(dockerImage, ["--network=host"]) as getstatusoutput_docker:
    my_gzip = "pigz" if getstatusoutput_docker("which pigz")[0] == 0 else "gzip"
    my_tar = ("tar --ignore-failed-read"
              if getstatusoutput_docker("tar --ignore-failed-read -cvvf "
                                        "/dev/null /dev/zero")[0] == 0
              else "tar")
    systemPackages, ownPackages, failed, validDefaults = \
      getPackageList(packages                = packages,
                     specs                   = specs,
                     configDir               = args.configDir,
                     preferSystem            = args.preferSystem,
                     noSystem                = args.noSystem,
                     architecture            = args.architecture,
                     disable                 = args.disable,
                     force_rebuild           = args.force_rebuild,
                     defaults                = args.defaults,
                     performPreferCheck      = lambda pkg, cmd: getstatusoutput_docker(cmd),
                     performRequirementCheck = lambda pkg, cmd: getstatusoutput_docker(cmd),
                     performValidateDefaults = lambda spec: validateDefaults(spec, args.defaults),
                     overrides               = overrides,
                     taps                    = taps,
                     log                     = debug)

  if validDefaults and args.defaults not in validDefaults:
    error("Specified default `%s' is not compatible with the packages you want to build.\n"
          "Valid defaults:\n\n- %s", args.defaults, "\n- ".join(sorted(validDefaults)))
    return 1

  if failed:
    error("The following packages are system requirements and could not be found:\n\n- %s\n\n"
          "Please run:\n\n\t%sDoctor --defaults %s %s\n\nto get a full diagnosis.",
          "\n- ".join(sorted(list(failed))), star(), args.defaults, args.pkgname.pop())
    return 1

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
  develPkgs = []
  if not args.forceTracked:
    develCandidates = [basename(d) for d in glob("*") if os.path.isdir(d)]
    develCandidatesUpper = [basename(d).upper() for d in glob("*") if os.path.isdir(d)]
    develPkgs = [p for p in buildOrder
                 if p in develCandidates and p not in args.noDevel]
    develPkgsUpper = [(p, p.upper()) for p in buildOrder
                      if p.upper() in develCandidatesUpper and p not in args.noDevel]
    if set(develPkgs) != {x for x, _ in develPkgsUpper}:
      error("The following development packages have the wrong spelling: %s.\n"
            "Please check your local checkout and adapt to the correct one indicated.",
            ", ".join({x.strip() for x, _ in develPkgsUpper} - set(develPkgs)))
      return 1

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
  update_git_repos(args, specs, buildOrder, develPkgs)

  # Resolve the tag to the actual commit ref
  for p in buildOrder:
    spec = specs[p]
    spec["commit_hash"] = "0"
    develPackageBranch = ""
    if "source" in spec:
      # Tag may contain date params like %(year)s, %(month)s, %(day)s, %(hour).
      spec["tag"] = resolve_tag(spec)
      # First, we try to resolve the "tag" as a branch name, and use its tip as
      # the commit_hash. If it's not a branch, it must be a tag or a raw commit
      # hash, so we use it directly. Finally if the package is a development
      # one, we use the name of the branch as commit_hash.
      assert "git_refs" in spec
      try:
        spec["commit_hash"] = spec["git_refs"]["refs/heads/" + spec["tag"]]
      except KeyError:
        spec["commit_hash"] = spec["tag"]
      # We are in development mode, we need to rebuild if the commit hash is
      # different or if there are extra changes on top.
      if spec["package"] in develPkgs:
        # Devel package: we get the commit hash from the checked source, not from remote.
        out = git(("rev-parse", "HEAD"), directory=spec["source"])
        spec["commit_hash"] = out.strip()
        cmd = "cd %s && git diff -r HEAD && git status --porcelain" % spec["source"]
        h = Hasher()
        err = execute(cmd, lambda s, *a: h(s % a))
        debug("Command %s returned %d", cmd, err)
        dieOnError(err, "Unable to detect source code changes.")
        spec["devel_hash"] = spec["commit_hash"] + h.hexdigest()
        out = git(("rev-parse", "--abbrev-ref", "HEAD"), directory=spec["source"])
        if out == "HEAD":
          out = git(("rev-parse", "HEAD"), directory=spec["source"])[:10]
        develPackageBranch = out.replace("/", "-")
        spec["tag"] = args.develPrefix if "develPrefix" in args else develPackageBranch
        spec["commit_hash"] = "0"

    # Version may contain date params like tag, plus %(commit_hash)s,
    # %(short_hash)s and %(tag)s.
    spec["version"] = resolve_version(spec, args.defaults, branch_basename, branch_stream)

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
    banner("Nothing to be done.")
    return 0
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

  # Use the selected plugin to build, instead of the default behaviour, if a
  # plugin was selected.
  if args.plugin != "legacy":
    return importlib.import_module("alibuild_helpers.%s_plugin" % args.plugin) \
                    .build_plugin(specs, args, buildOrder)

  debug("We will build packages in the following order: %s", " ".join(buildOrder))
  if args.dryRun:
    info("--dry-run / -n specified. Not building.")
    return 0

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
      error("Too many attempts at building %s. Something wrong with the repository?",
            spec["package"])
      return 1
    p = buildOrder[0]
    spec = specs[p]
    if args.debug:
      printedVersion = mainHash == spec["tag"] and mainHash or mainHash[0:8]
      logger_handler.setFormatter(
          LogFormatter("%%(asctime)s:%%(levelname)s:%s:%s:%s: %%(message)s" %
                       (mainPackage, p, args.develPrefix if "develPrefix" in args else printedVersion)))

    # Calculate the hashes. We do this in build order so that we can guarantee
    # that the hashes of the dependencies are calculated first. Do this inside
    # the main build loop to make sure that our dependencies have been assigned
    # a single, definitive hash.
    debug("Calculating hash.")
    debug("spec = %r", spec)
    debug("develPkgs = %r", develPkgs)
    storeHashes(p, specs, isDevelPkg=p in develPkgs,
                considerRelocation=args.architecture.startswith("osx"))
    debug("Hashes for recipe %s are %s (remote); %s (local)", p,
          ", ".join(spec["remote_hashes"]), ", ".join(spec["local_hashes"]))

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

    candidate = None
    busyRevisions = set()
    # We can tell that the remote store is read-only if it has an empty or
    # no writeStore property. See below for explanation of why we need this.
    revisionPrefix = "" if getattr(syncHelper, "writeStore", "") else "local"
    for symlink in packages:
      realPath = readlink(symlink)
      matcher = format("../../%(a)s/store/[0-9a-f]{2}/([0-9a-f]*)/%(p)s-%(v)s-((?:local)?[0-9]*).%(a)s.tar.gz$",
                       a=args.architecture,
                       p=spec["package"],
                       v=spec["version"])
      match = re.match(matcher, realPath)
      if not match:
        warning("Symlink %s -> %s couldn't be parsed", symlink, realPath)
        continue
      rev_hash, revision = match.groups()

      if not (("local" in revision and rev_hash in spec["local_hashes"]) or
              ("local" not in revision and rev_hash in spec["remote_hashes"])):
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
        debug("Skipping revision %s because we want to upload later", revision)
        continue

      # If we have an hash match, we use the old revision for the package
      # and we do not need to build it. Because we prefer reusing remote
      # revisions, only store a local revision if there is no other candidate
      # for reuse yet.
      candidate = better_tarball(spec, candidate, (revision, rev_hash, symlink))

    try:
      revision, rev_hash, symlink = candidate
    except TypeError:  # raised if candidate is still None
      # If we can't reuse an existing revision, assign the next free revision
      # to this package. If we're not uploading it, name it localN to avoid
      # interference with the remote store -- in case this package is built
      # somewhere else, the next revision N might be assigned there, and would
      # conflict with our revision N.
      # The code finding busyRevisions above already ensures that revision
      # numbers start with revisionPrefix, and has left us plain ints.
      spec["revision"] = revisionPrefix + str(
        min(set(range(1, max(busyRevisions) + 2)) - busyRevisions)
        if busyRevisions else 1)
    else:
      spec["revision"] = revision
      # Remember what hash we're actually using.
      spec["local_revision_hash" if revision.startswith("local")
           else "remote_revision_hash"] = rev_hash
      if spec["package"] in develPkgs and "incremental_recipe" in spec:
        spec["obsolete_tarball"] = symlink
      else:
        debug("Package %s with hash %s is already found in %s. Not building.",
              p, rev_hash, symlink)
        getstatusoutput(
          "ln -snf {v}-{r} {w}/{a}/{p}/latest-{bf};"
          "ln -snf {v}-{r} {w}/{a}/{p}/latest".format(
            v=spec["version"], r=spec["revision"], w=workDir,
            a=args.architecture, p=spec["package"], bf=spec["build_family"]))
        info("Using cached build for %s", p)

    # Now we know whether we're using a local or remote package, so we can set
    # the proper hash and tarball directory.
    if spec["revision"].startswith("local"):
      spec["hash"] = spec["local_revision_hash"]
    else:
      spec["hash"] = spec["remote_revision_hash"]
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
      createDistLinks(spec, specs, args, syncHelper, "dist", "full_requires")
      createDistLinks(spec, specs, args, syncHelper, "dist-direct", "requires")
      createDistLinks(spec, specs, args, syncHelper, "dist-runtime", "full_runtime_requires")
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

    tar_hash_dir = os.path.join(workDir, resolve_store_path(args.architecture, spec["hash"]))
    debug("Looking for cached tarball in %s", tar_hash_dir)
    # FIXME: I should get the tar_hash_dir updated with server at this point.
    #        It does not really matter that the symlinks are ok at this point
    #        as I only used the tarballs as reusable binary blobs.
    spec["cachedTarball"] = ""
    if not spec["package"] in develPkgs:
      tarballs = glob(os.path.join(tar_hash_dir, "*gz"))
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
                 gitOptionsStatement="" if args.docker else
                   "export GIT_CLONE_SPEEDUP=" + quote(" ".join(clone_speedup_options())),
                 requires=" ".join(spec["requires"]),
                 build_requires=" ".join(spec["build_requires"]),
                 runtime_requires=" ".join(spec["runtime_requires"])
                )

    scriptDir = join(workDir, "SPECS", args.architecture, spec["package"],
                     spec["version"] + "-" + spec["revision"])

    err, out = getstatusoutput("mkdir -p %s" % scriptDir)
    dieOnError(err, "Failed to create script dir %s: %s" % (scriptDir, out))
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
      ("MY_GZIP", my_gzip),
      ("MY_TAR", my_tar),
      ("INCREMENTAL_BUILD_HASH", spec.get("incremental_hash", "0")),
      ("JOBS", str(args.jobs)),
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
      build_command = (
        "docker run --rm --network=host --entrypoint= --user $(id -u):$(id -g) "
        "-v {workdir}:/sw -v {scriptDir}/build.sh:/build.sh:ro "
        "-e GIT_REFERENCE_OVERRIDE=/mirror -e WORK_DIR_OVERRIDE=/sw "
        "{mirrorVolume} {develVolumes} {additionalEnv} {additionalVolumes} "
        "{overrideSource} {extraArgs} {image} bash -ex /build.sh"
      ).format(
        image=quote(dockerImage),
        workdir=quote(abspath(args.workDir)),
        scriptDir=quote(scriptDir),
        extraArgs=args.docker_extra_args if "docker_extra_args" in args else "",
        overrideSource="-e SOURCE0_DIR_OVERRIDE=/" if source.startswith("/") else "",
        additionalEnv=" ".join(
          "-e {}={}".format(var, quote(value)) for var, value in buildEnvironment),
        develVolumes=" ".join(
          '-v "$PWD/$(readlink {pkg} || echo {pkg})":/{pkg}:rw'.format(pkg=quote(pkg))
          for pkg in develPkgs),
        additionalVolumes=" ".join(
          "-v %s" % quote(volume) for volume in args.volumes),
        mirrorVolume=("-v %s:/mirror" % quote(dirname(spec["reference"]))
                      if "reference" in spec else ""),
      )
    else:
      os.environ.update(buildEnvironment)
      build_command = "%s -e -x %s/build.sh 2>&1" % (BASH, quote(scriptDir))

    debug("Build command: %s", build_command)
    progress = ProgressPrint("%s is being built (use --debug for full output)" % spec["package"])
    err = execute(build_command, printer=debug if args.debug or not sys.stdout.isatty() else progress)
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
  debug("Everything done")
  return 0
