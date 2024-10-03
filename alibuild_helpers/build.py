from os.path import abspath, exists, basename, dirname, join, realpath
from os import makedirs, unlink, readlink, rmdir
from alibuild_helpers import __version__
from alibuild_helpers.analytics import report_event
from alibuild_helpers.log import debug, info, banner, warning
from alibuild_helpers.log import dieOnError
from alibuild_helpers.cmd import execute, DockerRunner, BASH, install_wrapper_script
from alibuild_helpers.utilities import prunePaths, symlink, call_ignoring_oserrors, topological_sort
from alibuild_helpers.utilities import resolve_store_path
from alibuild_helpers.utilities import parseDefaults, readDefaults
from alibuild_helpers.utilities import getPackageList, asList
from alibuild_helpers.utilities import validateDefaults
from alibuild_helpers.utilities import Hasher
from alibuild_helpers.utilities import yamlDump
from alibuild_helpers.utilities import resolve_tag, resolve_version, short_commit_hash
from alibuild_helpers.git import Git, git
from alibuild_helpers.sl import Sapling
from alibuild_helpers.scm import SCMError
from alibuild_helpers.sync import remote_from_url
from alibuild_helpers.workarea import logged_scm, updateReferenceRepoSpec, checkout_sources
from alibuild_helpers.log import ProgressPrint, log_current_package
from glob import glob
from textwrap import dedent
from collections import OrderedDict
from shlex import quote

import concurrent.futures
import importlib
import json
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


def update_git_repos(args, specs, buildOrder):
    """Update and/or fetch required git repositories in parallel.

    If any repository fails to be fetched, then it is retried, while allowing the
    user to input their credentials if required.
    """

    def update_repo(package, git_prompt):
        specs[package]["scm"] = Git()
        if specs[package]["is_devel_pkg"]:
            specs[package]["source"] = os.path.join(os.getcwd(), specs[package]["package"])
            if exists(os.path.join(specs[package]["source"], ".sl")):
                specs[package]["scm"] = Sapling()
        updateReferenceRepoSpec(args.referenceSources, package, specs[package],
                                fetch=args.fetchRepos, allowGitPrompt=git_prompt)

        # Retrieve git heads
        output = logged_scm(specs[package]["scm"], package, args.referenceSources,
                            specs[package]["scm"].listRefsCmd(specs[package].get("reference", specs[package]["source"])),
                            ".", prompt=git_prompt, logOutput=False)
        specs[package]["scm_refs"] = specs[package]["scm"].parseRefs(output)

    progress = ProgressPrint("Updating repositories")
    requires_auth = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_download = {
          executor.submit(update_repo, package, git_prompt=False): package
          for package in buildOrder if "source" in specs[package]
        }
        for i, future in enumerate(concurrent.futures.as_completed(future_to_download)):
            futurePackage = future_to_download[future]
            progress("[%d/%d] Updating repository for %s",
                     i, len(future_to_download), futurePackage)
            try:
                future.result()
            except SCMError:
                # The SCM failed. Let's assume this is because the user needs
                # to supply a password.
                debug("%r requires auth; will prompt later", futurePackage)
                requires_auth.add(futurePackage)
            except Exception as exc:
                progress.end("error", error=True)
                dieOnError(True, "Error on fetching %r: %s. Aborting." %
                           (futurePackage, exc))
            else:
                debug("%r package updated: %d refs found", futurePackage,
                      len(specs[futurePackage]["scm_refs"]))
    progress.end("done")

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
              len(specs[package]["scm_refs"]))


# Creates a directory in the store which contains symlinks to the package
# and its direct / indirect dependencies
def createDistLinks(spec, specs, args, syncHelper, repoType, requiresType):
  # At the point we call this function, spec has a single, definitive hash.
  target_dir = "{work_dir}/TARS/{arch}/{repo}/{package}/{package}-{version}-{revision}" \
    .format(work_dir=args.workDir, arch=args.architecture, repo=repoType, **spec)
  shutil.rmtree(target_dir.encode("utf-8"), ignore_errors=True)
  makedirs(target_dir, exist_ok=True)
  for pkg in [spec["package"]] + list(spec[requiresType]):
    dep_tarball = "../../../../../TARS/{arch}/store/{short_hash}/{hash}/{package}-{version}-{revision}.{arch}.tar.gz" \
      .format(arch=args.architecture, short_hash=specs[pkg]["hash"][:2], **specs[pkg])
    symlink(dep_tarball, target_dir)


def storeHashes(package, specs, considerRelocation):
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

  for key in ("recipe", "version", "package"):
    h_all(spec.get(key, "none"))

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
    real_commit_hash = spec["scm_refs"]["refs/tags/" + spec["commit_hash"]]
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
  for ref, git_hash in spec.get("scm_refs", {}).items():
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

  for key in ("env", "append_path", "prepend_path"):
    if key not in spec:
      h_all("none")
    else:
      # spec["env"] is of type OrderedDict[str, str].
      # spec["*_path"] are of type OrderedDict[str, list[str]].
      assert isinstance(spec[key], OrderedDict), \
        "spec[%r] was of type %r" % (key, type(spec[key]))

      # Python 3.12 changed the string representation of OrderedDicts from
      # OrderedDict([(key, value)]) to OrderedDict({key: value}), so to remain
      # compatible, we need to emulate the previous string representation.
      h_all("OrderedDict([")
      h_all(", ".join(
        # XXX: We still rely on repr("str") being "'str'",
        # and on repr(["a", "b"]) being "['a', 'b']".
        "(%r, %r)" % (key, value)
        for key, value in spec[key].items()
      ))
      h_all("])")

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
    h_all(specs[dep]["hash"] if spec["is_devel_pkg"] else hash_and_devel_hash)
    # The deps_hash should always change, however, so we actually rebuild the
    # dependent package (even if incrementally).
    dh(hash_and_devel_hash)

  if spec["is_devel_pkg"] and "incremental_recipe" in spec:
    h_all(spec["incremental_recipe"])
    ih = Hasher()
    ih(spec["incremental_recipe"])
    spec["incremental_hash"] = ih.hexdigest()
  elif spec["is_devel_pkg"]:
    h_all(spec["devel_hash"])

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


def hash_local_changes(spec):
  """Produce a hash of all local changes in the given git repo.

  If there are untracked files, this function returns a unique hash to force a
  rebuild, and logs a warning, as we cannot detect changes to those files.
  """
  directory = spec["source"]
  scm = spec["scm"]
  untrackedFilesDirectories = []
  class UntrackedChangesError(Exception):
    """Signal that we cannot detect code changes due to untracked files."""
  h = Hasher()
  def hash_output(msg, args):
    lines = msg % args
    # `git status --porcelain` indicates untracked files using "??".
    # Lines from `git diff` never start with "??".
    if any(scm.checkUntracked(line) for line in lines.split("\n")):
      raise UntrackedChangesError()
    h(lines)
  cmd = scm.diffCmd(directory)
  try:
    err = execute(cmd, hash_output)
    debug("Command %s returned %d", cmd, err)
    dieOnError(err, "Unable to detect source code changes.")
  except UntrackedChangesError:
    untrackedFilesDirectories = [directory]
    warning("You have untracked changes in %s, so aliBuild cannot detect "
            "whether it needs to rebuild the package. Therefore, the package "
            "is being rebuilt unconditionally. Please use 'git add' and/or "
            "'git commit' to track your changes in git.", directory)
    # If there are untracked changes, always rebuild (hopefully incrementally)
    # and let CMake figure out what needs to be rebuilt. Force a rebuild by
    # changing the hash to something basically random.
    h(str(time.time()))
  return (h.hexdigest(), untrackedFilesDirectories)


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


def generate_initdotsh(package, specs, architecture, post_build=False):
  """Return the contents of the given package's etc/profile/init.sh as a string.

  If post_build is true, also generate variables pointing to the package
  itself; else, only generate variables pointing at it dependencies.
  """
  spec = specs[package]
  # Allow users to override ALIBUILD_ARCH_PREFIX if they manually source
  # init.sh. This is useful for development off CVMFS, since we have a
  # slightly different directory hierarchy there.
  lines = [': "${ALIBUILD_ARCH_PREFIX:=%s}"' % architecture]

  # Generate the part which sources the environment for all the dependencies.
  # We guarantee that a dependency is always sourced before the parts
  # depending on it, but we do not guarantee anything for the order in which
  # unrelated components are activated.
  # These variables are also required during the build itself, so always
  # generate them.
  lines.extend((
    '[ -n "${{{bigpackage}_REVISION}}" ] || '
    '. "$WORK_DIR/$ALIBUILD_ARCH_PREFIX"/{package}/{version}-{revision}/etc/profile.d/init.sh'
  ).format(
    bigpackage=dep.upper().replace("-", "_"),
    package=quote(specs[dep]["package"]),
    version=quote(specs[dep]["version"]),
    revision=quote(specs[dep]["revision"]),
  ) for dep in spec.get("requires", ()))

  if post_build:
    bigpackage = package.upper().replace("-", "_")

    # Set standard variables related to the package itself. These should only
    # be set once the build has actually completed.
    lines.extend(line.format(
      bigpackage=bigpackage,
      package=quote(spec["package"]),
      version=quote(spec["version"]),
      revision=quote(spec["revision"]),
      hash=quote(spec["hash"]),
      commit_hash=quote(spec["commit_hash"]),
    ) for line in (
      'export {bigpackage}_ROOT="$WORK_DIR/$ALIBUILD_ARCH_PREFIX"/{package}/{version}-{revision}',
      "export {bigpackage}_VERSION={version}",
      "export {bigpackage}_REVISION={revision}",
      "export {bigpackage}_HASH={hash}",
      "export {bigpackage}_COMMIT={commit_hash}",
    ))

    # Generate the part which sets the environment variables related to the
    # package itself. This can be variables set via the "env" keyword in the
    # metadata or paths which get concatenated via the "{append,prepend}_path"
    # keys. These should only be set once the build has actually completed,
    # since the paths referred to will only exist then.

    # First, output a sensible error message if types are wrong.
    for key in ("env", "append_path", "prepend_path"):
      dieOnError(not isinstance(spec.get(key, {}), dict),
                 "Tag `%s' in %s should be a dict." % (key, package))

    # Set "env" variables.
    # We only put the values in double-quotes, so that they can refer to other
    # shell variables or do command substitution (e.g. $(brew --prefix ...)).
    lines.extend('export {}="{}"'.format(key, value)
                 for key, value in spec.get("env", {}).items()
                 if key != "DYLD_LIBRARY_PATH")

    # Append paths to variables, if requested using append_path.
    # Again, only put values in double quotes so that they can refer to other variables.
    lines.extend('export {key}="${key}:{value}"'
                 .format(key=key, value=":".join(asList(value)))
                 for key, value in spec.get("append_path", {}).items()
                 if key != "DYLD_LIBRARY_PATH")

    # First convert all values to list, so that we can use .setdefault().insert() below.
    prepend_path = {key: asList(value)
                    for key, value in spec.get("prepend_path", {}).items()}
    # By default we add the .../bin directory to PATH and .../lib to LD_LIBRARY_PATH.
    # Prepend to these paths, so that our packages win against system ones.
    for key, value in (("PATH", "bin"), ("LD_LIBRARY_PATH", "lib")):
      prepend_path.setdefault(key, []).insert(0, "${}_ROOT/{}".format(bigpackage, value))
    lines.extend('export {key}="{value}${{{key}+:${key}}}"'
                 .format(key=key, value=":".join(value))
                 for key, value in prepend_path.items()
                 if key != "DYLD_LIBRARY_PATH")

  # Return string without a trailing newline, since we expect call sites to
  # append that (and the obvious way to inesrt it into the build tempate is by
  # putting the "%(initdotsh_*)s" on its own line, which has the same effect).
  return "\n".join(lines)


def create_provenance_info(package, specs, args):
  """Return a metadata record for storage in the package's install directory."""

  def spec_info(spec):
    return {
      "name": spec["package"],
      "tag": spec.get("tag"),
      "source": spec.get("source"),
      "version": spec["version"],
      "revision": spec["revision"],
      "hash": spec["hash"],
    }

  def dependency_list(key):
    return [spec_info(specs[dep]) for dep in specs[package].get(key, ())]

  return json.dumps({
    "comment": args.annotate.get(package),
    "alibuild_version": __version__,
    "alidist": {
      "commit": os.environ["ALIBUILD_ALIDIST_HASH"],
    },
    "architecture": args.architecture,
    "defaults": args.defaults,
    "package": spec_info(specs[package]),
    "dependencies": {
      "direct": {
        "build": dependency_list("build_requires"),
        "runtime": dependency_list("runtime_requires"),
      },
      "recursive": {  # includes direct deps and deps' deps
        "build": dependency_list("full_build_requires"),
        "runtime": dependency_list("full_runtime_requires"),
      },
    },
  })


def doBuild(args, parser):
  syncHelper = remote_from_url(args.remoteStore, args.writeStore, args.architecture,
                               args.workDir, getattr(args, "insecure", False))

  packages = args.pkgname
  specs = {}
  buildOrder = []
  workDir = abspath(args.workDir)
  prunePaths(workDir)

  dieOnError(not exists(args.configDir),
             'Cannot find alidist recipes under directory "%s".\n'
             'Maybe you need to "cd" to the right directory or '
             'you forgot to run "aliBuild init"?' % args.configDir)

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

  makedirs(join(workDir, "SPECS"), exist_ok=True)

  # If the alidist workdir contains a .sl directory, we use Sapling as SCM.
  # Otherwise, we default to git (without checking for the actual presence of
  # .git). We mustn't check for a .git directory, because some tests use a
  # subdirectory of the alibuild source tree as the "alidist" checkout, and
  # that won't have a .git directory.
  scm = exists("%s/.sl" % args.configDir) and Sapling() or Git()
  try:
    checkedOutCommitName = scm.checkedOutCommitName(directory=args.configDir)
  except SCMError:
    dieOnError(True, "Cannot find SCM directory in %s." % args.configDir)
  os.environ["ALIBUILD_ALIDIST_HASH"] = checkedOutCommitName # type: ignore

  debug("Building for architecture %s", args.architecture)
  debug("Number of parallel builds: %d", args.jobs)
  debug("Using aliBuild from alibuild@%s recipes in alidist@%s",
        __version__ or "unknown", os.environ["ALIBUILD_ALIDIST_HASH"])

  install_wrapper_script("git", workDir)

  with DockerRunner(args.dockerImage, args.docker_extra_args) as getstatusoutput_docker:
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

  dieOnError(validDefaults and args.defaults not in validDefaults,
             "Specified default `%s' is not compatible with the packages you want to build.\n"
             "Valid defaults:\n\n- %s" % (args.defaults, "\n- ".join(sorted(validDefaults or []))))
  dieOnError(failed,
             "The following packages are system requirements and could not be found:\n\n- %s\n\n"
             "Please run:\n\n\taliDoctor --defaults %s %s\n\nto get a full diagnosis." %
             ("\n- ".join(sorted(failed)), args.defaults, " ".join(args.pkgname)))

  for x in specs.values():
    x["requires"] = [r for r in x["requires"] if not r in args.disable]
    x["build_requires"] = [r for r in x["build_requires"] if not r in args.disable]
    x["runtime_requires"] = [r for r in x["runtime_requires"] if not r in args.disable]

  if systemPackages:
    banner("aliBuild can take the following packages from the system and will not build them:\n  %s",
           ", ".join(systemPackages))
  if ownPackages:
    banner("The following packages cannot be taken from the system and will be built:\n  %s",
           ", ".join(ownPackages))

  buildOrder = list(topological_sort(specs))

  # Check if any of the packages can be picked up from a local checkout
  if args.forceTracked:
    develPkgs = set()
  else:
    develCandidates = {basename(d) for d in glob("*") if os.path.isdir(d)} - frozenset(args.noDevel)
    develCandidatesUpper = {d.upper() for d in develCandidates}
    develPkgs = frozenset(buildOrder) & develCandidates
    develPkgsUpper = {p for p in buildOrder if p.upper() in develCandidatesUpper}
    dieOnError(develPkgs != develPkgsUpper,
               "The following development packages have the wrong spelling: %s.\n"
               "Please check your local checkout and adapt to the correct one indicated." %
               ", ".join(develPkgsUpper - develPkgs))
    del develCandidates, develCandidatesUpper, develPkgsUpper

  if buildOrder:
    if args.onlyDeps: 
      builtPackages = buildOrder[:-1]
    else:
      builtPackages = buildOrder
    if len(builtPackages) > 1:
      banner("Packages will be built in the following order:\n - %s",
             "\n - ".join(x+" (development package)" if x in develPkgs else "%s@%s" % (x, specs[x]["tag"])
                          for x in builtPackages if x != "defaults-release"))
    else:
      banner("No dependencies of package %s to build.", buildOrder[-1])


  if develPkgs:
    banner("You have packages in development mode (%s).\n"
           "This means their source code can be freely modified under:\n\n"
           "  %s/<package_name>\n\n"
           "aliBuild does not automatically update such packages to avoid work loss.\n"
           "In most cases this is achieved by doing in the package source directory:\n\n"
           "  git pull --rebase\n",
           ", ".join(develPkgs),
           os.getcwd())

  for pkg, spec in specs.items():
    spec["is_devel_pkg"] = pkg in develPkgs
    spec["scm"] = Git()
    if spec["is_devel_pkg"]:
      spec["source"] = os.path.join(os.getcwd(), pkg)
    if "source" in spec and exists(os.path.join(spec["source"], ".sl")):
      spec["scm"] = Sapling()
    reference_repo = join(os.path.abspath(args.referenceSources), pkg.lower())
    if exists(reference_repo):
      spec["reference"] = reference_repo
  del develPkgs

  # Clone/update repos
  update_git_repos(args, specs, buildOrder)
  # This is the list of packages which have untracked files in their
  # source directory, and which are rebuilt every time. We will warn
  # about them at the end of the build.
  untrackedFilesDirectories = []

  # Resolve the tag to the actual commit ref
  for p in buildOrder:
    spec = specs[p]
    spec["commit_hash"] = "0"
    develPackageBranch = ""
    # This is a development package (i.e. a local directory named like
    # spec["package"]), but there is no "source" key in its alidist recipe,
    # so there shouldn't be any code for it! Presumably, a user has
    # mistakenly named a local directory after one of our packages.
    dieOnError("source" not in spec and spec["is_devel_pkg"],
               "Found a directory called {package} here, but we're not "
               "expecting any code for the package {package}. If this is a "
               "mistake, please rename the {package} directory or use the "
               "'--no-local {package}' option. If aliBuild should pick up "
               "source code from this directory, add a 'source:' key to "
               "alidist/{recipe}.sh instead."
               .format(package=p, recipe=p.lower()))
    if "source" in spec:
      # Tag may contain date params like %(year)s, %(month)s, %(day)s, %(hour).
      spec["tag"] = resolve_tag(spec)
      # First, we try to resolve the "tag" as a branch name, and use its tip as
      # the commit_hash. If it's not a branch, it must be a tag or a raw commit
      # hash, so we use it directly. Finally if the package is a development
      # one, we use the name of the branch as commit_hash.
      assert "scm_refs" in spec
      try:
        spec["commit_hash"] = spec["scm_refs"]["refs/heads/" + spec["tag"]]
      except KeyError:
        spec["commit_hash"] = spec["tag"]
      # We are in development mode, we need to rebuild if the commit hash is
      # different or if there are extra changes on top.
      if spec["is_devel_pkg"]:
        # Devel package: we get the commit hash from the checked source, not from remote.
        out = spec["scm"].checkedOutCommitName(directory=spec["source"])
        spec["commit_hash"] = out.strip()
        local_hash, untracked = hash_local_changes(spec)
        untrackedFilesDirectories.extend(untracked)
        spec["devel_hash"] = spec["commit_hash"] + local_hash
        out = spec["scm"].branchOrRef(directory=spec["source"])
        develPackageBranch = out.replace("/", "-")
        spec["tag"] = args.develPrefix if "develPrefix" in args else develPackageBranch
        spec["commit_hash"] = "0"

    # Version may contain date params like tag, plus %(commit_hash)s,
    # %(short_hash)s and %(tag)s.
    spec["version"] = resolve_version(spec, args.defaults, branch_basename, branch_stream)

    if spec["is_devel_pkg"] and "develPrefix" in args and args.develPrefix != "ali-master":
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
    return
  mainPackage = buildOrder[-1]
  mainHash = specs[mainPackage]["commit_hash"]

  debug("Main package is %s@%s", mainPackage, mainHash)
  log_current_package(None, mainPackage, specs, getattr(args, "develPrefix", None))

  # Now that we have the main package set, we can print out Useful information
  # which we will be able to associate with this build. Also lets make sure each package
  # we need to build can be built with the current default.
  for p in buildOrder:
    spec = specs[p]
    if "source" in spec:
      debug("Commit hash for %s@%s is %s", spec["source"], spec["tag"], spec["commit_hash"])

  # We recursively calculate the full set of requires "full_requires"
  # including build_requires and the subset of them which are needed at
  # runtime "full_runtime_requires". Do this in build order, so that we can
  # rely on each spec's dependencies already having their full_*_requires
  # properties populated.
  for p in buildOrder:
    spec = specs[p]
    for key in ("requires", "runtime_requires", "build_requires"):
      full_key = "full_" + key
      spec[full_key] = set()
      for dep in spec.get(key, ()):
        spec[full_key].add(dep)
        # Runtime deps of build deps should count as build deps.
        spec[full_key] |= specs[dep]["full_requires" if key == "build_requires" else full_key]
    # Propagate build deps of runtime deps, so that they are not added into
    # the generated modulefile by alibuild-generate-module.
    for dep in spec["runtime_requires"]:
      spec["full_build_requires"] |= specs[dep]["full_build_requires"]
    # If something requires or runtime_requires a package, then it's not a
    # pure build_requires only anymore, so we drop it from the list.
    spec["full_build_requires"] -= spec["full_runtime_requires"]

  # Use the selected plugin to build, instead of the default behaviour, if a
  # plugin was selected.
  if args.plugin != "legacy":
    return importlib.import_module("alibuild_helpers.%s_plugin" % args.plugin) \
                    .build_plugin(specs, args, buildOrder)

  debug("We will build packages in the following order: %s", " ".join(buildOrder))
  if args.dryRun:
    info("--dry-run / -n specified. Not building.")
    return

  # We now iterate on all the packages, making sure we build correctly every
  # single one of them. This is done this way so that the second time we run we
  # can check if the build was consistent and if it is, we bail out.
  report_event("install", "{p} disabled={dis} devel={dev} system={sys} own={own} deps={deps}".format(
    p=args.pkgname,
    dis=",".join(sorted(args.disable)),
    dev=",".join(sorted(spec["package"] for spec in specs.values() if spec["is_devel_pkg"])),
    sys=",".join(sorted(systemPackages)),
    own=",".join(sorted(ownPackages)),
    deps=",".join(buildOrder[:-1]),
  ), args.architecture)

  # If we are building only the dependencies, the last package in
  # the build order can be considered done.
  if args.onlyDeps and len(buildOrder) > 1:
    mainPackage = buildOrder.pop()
    warning("Not rebuilding %s because --only-deps option provided.", mainPackage)

  while buildOrder:
    p = buildOrder[0]
    spec = specs[p]
    log_current_package(p, mainPackage, specs, getattr(args, "develPrefix", None))

    # Calculate the hashes. We do this in build order so that we can guarantee
    # that the hashes of the dependencies are calculated first. Do this inside
    # the main build loop to make sure that our dependencies have been assigned
    # a single, definitive hash.
    debug("Calculating hash.")
    debug("spec = %r", spec)
    debug("develPkgs = %r", sorted(spec["package"] for spec in specs.values() if spec["is_devel_pkg"]))
    storeHashes(p, specs, considerRelocation=args.architecture.startswith("osx"))
    debug("Hashes for recipe %s are %s (remote); %s (local)", p,
          ", ".join(spec["remote_hashes"]), ", ".join(spec["local_hashes"]))

    if spec["is_devel_pkg"] and getattr(syncHelper, "writeStore", None):
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
    syncHelper.fetch_symlinks(spec)

    # Decide how it should be called, based on the hash and what is already
    # available.
    debug("Checking for packages already built.")

    # Make sure this regex broadly matches the regex below that parses the
    # symlink's target. Overly-broadly matching the version, for example, can
    # lead to false positives that trigger a warning below.
    links_regex = re.compile(r"{package}-{version}-(?:local)?[0-9]+\.{arch}\.tar\.gz".format(
      package=re.escape(spec["package"]),
      version=re.escape(spec["version"]),
      arch=re.escape(args.architecture),
    ))
    symlink_dir = join(workDir, "TARS", args.architecture, spec["package"])
    try:
      packages = [join(symlink_dir, symlink_path)
                  for symlink_path in os.listdir(symlink_dir)
                  if links_regex.fullmatch(symlink_path)]
    except OSError:
      # If symlink_dir does not exist or cannot be accessed, return an empty
      # list of packages.
      packages = []
    del links_regex, symlink_dir

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
    if spec["is_devel_pkg"]:
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
    for symlink_path in packages:
      realPath = readlink(symlink_path)
      matcher = "../../{arch}/store/[0-9a-f]{{2}}/([0-9a-f]+)/{package}-{version}-((?:local)?[0-9]+).{arch}.tar.gz$" \
        .format(arch=args.architecture, **spec)
      match = re.match(matcher, realPath)
      if not match:
        warning("Symlink %s -> %s couldn't be parsed", symlink_path, realPath)
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
      candidate = better_tarball(spec, candidate, (revision, rev_hash, symlink_path))

    try:
      revision, rev_hash, symlink_path = candidate
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
      if spec["is_devel_pkg"] and "incremental_recipe" in spec:
        spec["obsolete_tarball"] = symlink_path
      else:
        debug("Package %s with hash %s is already found in %s. Not building.",
              p, rev_hash, symlink_path)
        # Ignore errors here, because the path we're linking to might not
        # exist (if this is the first run through the loop). On the second run
        # through, the path should have been created by the build process.
        call_ignoring_oserrors(symlink, "{version}-{revision}".format(**spec),
                               "{wd}/{arch}/{package}/latest-{build_family}".format(wd=workDir, arch=args.architecture, **spec))
        call_ignoring_oserrors(symlink, "{version}-{revision}".format(**spec),
                               "{wd}/{arch}/{package}/latest".format(wd=workDir, arch=args.architecture, **spec))

    # Now we know whether we're using a local or remote package, so we can set
    # the proper hash and tarball directory.
    if spec["revision"].startswith("local"):
      spec["hash"] = spec["local_revision_hash"]
    else:
      spec["hash"] = spec["remote_revision_hash"]
    spec["old_devel_hash"] = readHashFile(join(
      workDir, "BUILD", spec["hash"], spec["package"], ".build_succeeded"))

    # Recreate symlinks to this development package builds.
    if spec["is_devel_pkg"]:
      debug("Creating symlinks to builds of devel package %s", spec["package"])
      # Ignore errors here, because the path we're linking to might not exist
      # (if this is the first run through the loop). On the second run
      # through, the path should have been created by the build process.
      call_ignoring_oserrors(symlink, spec["hash"], join(workDir, "BUILD", spec["package"] + "-latest"))
      if develPrefix:
        call_ignoring_oserrors(symlink, spec["hash"], join(workDir, "BUILD", spec["package"] + "-latest-" + develPrefix))
      # Last package built gets a "latest" mark.
      call_ignoring_oserrors(symlink, "{version}-{revision}".format(**spec),
                             join(workDir, args.architecture, spec["package"], "latest"))
      # Latest package built for a given devel prefix gets a "latest-<family>" mark.
      if spec["build_family"]:
        call_ignoring_oserrors(symlink, "{version}-{revision}".format(**spec),
                               join(workDir, args.architecture, spec["package"], "latest-" + spec["build_family"]))

    # Check if this development package needs to be rebuilt.
    if spec["is_devel_pkg"]:
      debug("Checking if devel package %s needs rebuild", spec["package"])
      if spec["devel_hash"]+spec["deps_hash"] == spec["old_devel_hash"]:
        info("Development package %s does not need rebuild", spec["package"])
        buildOrder.pop(0)
        continue

    # Now that we have all the information about the package we want to build, let's
    # check if it wasn't built / unpacked already.
    hashPath= "%s/%s/%s/%s-%s" % (workDir,
                                  args.architecture,
                                  spec["package"],
                                  spec["version"],
                                  spec["revision"])
    hashFile = hashPath + "/.build-hash"
    # If the folder is a symlink, we consider it to be to CVMFS and
    # take the hash for good.
    if os.path.islink(hashPath):
      fileHash = spec["hash"]
    else:
      fileHash = readHashFile(hashFile)
    # Development packages have their own rebuild-detection logic above.
    # spec["hash"] is only useful here for regular packages.
    if fileHash == spec["hash"] and not spec["is_devel_pkg"]:
      # If we get here, we know we are in sync with whatever remote store.  We
      # can therefore create a directory which contains all the packages which
      # were used to compile this one.
      debug("Package %s was correctly compiled. Moving to next one.", spec["package"])
      # If using incremental builds, next time we execute the script we need to remove
      # the placeholders which avoid rebuilds.
      if spec["is_devel_pkg"] and "incremental_recipe" in spec:
        unlink(hashFile)
      if "obsolete_tarball" in spec:
        unlink(realpath(spec["obsolete_tarball"]))
        unlink(spec["obsolete_tarball"])
      buildOrder.pop(0)
      # We can now delete the INSTALLROOT and BUILD directories,
      # assuming the package is not a development one. We also can
      # delete the SOURCES in case we have aggressive-cleanup enabled.
      if not spec["is_devel_pkg"] and args.autoCleanup:
        cleanupDirs = [join(workDir, "BUILD", spec["hash"]),
                       join(workDir, "INSTALLROOT", spec["hash"])]
        if args.aggressiveCleanup:
          cleanupDirs.append(join(workDir, "SOURCES", spec["package"]))
        debug("Cleaning up:\n%s", "\n".join(cleanupDirs))

        for d in cleanupDirs:
          shutil.rmtree(d.encode("utf8"), True)
        try:
          unlink(join(workDir, "BUILD", spec["package"] + "-latest"))
          if "develPrefix" in args:
            unlink(join(workDir, "BUILD", spec["package"] + "-latest-" + args.develPrefix))
        except:
          pass
        try:
          rmdir(join(workDir, "BUILD"))
          rmdir(join(workDir, "INSTALLROOT"))
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
    spec["cachedTarball"] = ""
    if not spec["is_devel_pkg"]:
      syncHelper.fetch_tarball(spec)
      tarballs = glob(os.path.join(tar_hash_dir, "*gz"))
      spec["cachedTarball"] = tarballs[0] if len(tarballs) else ""
      debug("Found tarball in %s" % spec["cachedTarball"]
            if spec["cachedTarball"] else "No cache tarballs found")

    # The actual build script.
    debug("spec = %r", spec)

    cmd_raw = ""
    try:
      fp = open(dirname(realpath(__file__))+'/build_template.sh', 'r')
      cmd_raw = fp.read()
      fp.close()
    except:
      from pkg_resources import resource_string
      cmd_raw = resource_string("alibuild_helpers", 'build_template.sh')

    if args.docker:
      cachedTarball = re.sub("^" + workDir, "/sw", spec["cachedTarball"])
    else:
      cachedTarball = spec["cachedTarball"]

    if not cachedTarball:
      checkout_sources(spec, workDir, args.referenceSources, args.docker)

    scriptDir = join(workDir, "SPECS", args.architecture, spec["package"],
                     spec["version"] + "-" + spec["revision"])

    makedirs(scriptDir, exist_ok=True)
    writeAll("%s/%s.sh" % (scriptDir, spec["package"]), spec["recipe"])
    writeAll("%s/build.sh" % scriptDir, cmd_raw % {
      "provenance": create_provenance_info(spec["package"], specs, args),
      "initdotsh_deps": generate_initdotsh(p, specs, args.architecture, post_build=False),
      "initdotsh_full": generate_initdotsh(p, specs, args.architecture, post_build=True),
      "develPrefix": develPrefix,
      "workDir": workDir,
      "configDir": abspath(args.configDir),
      "incremental_recipe": spec.get("incremental_recipe", ":"),
      "requires": " ".join(spec["requires"]),
      "build_requires": " ".join(spec["build_requires"]),
      "runtime_requires": " ".join(spec["runtime_requires"]),
    })

    # Define the environment so that it can be passed up to the
    # actual build script
    buildEnvironment = [
      ("ARCHITECTURE", args.architecture),
      ("BUILD_REQUIRES", " ".join(spec["build_requires"])),
      ("CACHED_TARBALL", cachedTarball),
      ("CAN_DELETE", args.aggressiveCleanup and "1" or ""),
      ("COMMIT_HASH", short_commit_hash(spec)),
      ("DEPS_HASH", spec.get("deps_hash", "")),
      ("DEVEL_HASH", spec.get("devel_hash", "")),
      ("DEVEL_PREFIX", develPrefix),
      ("BUILD_FAMILY", spec["build_family"]),
      ("GIT_COMMITTER_NAME", "unknown"),
      ("GIT_COMMITTER_EMAIL", "unknown"),
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
    ]
    # Add the extra environment as passed from the command line.
    buildEnvironment += [e.partition('=')[::2] for e in args.environment]

    # In case the --docker options is passed, we setup a docker container which
    # will perform the actual build. Otherwise build as usual using bash.
    if args.docker:
      build_command = (
        "docker run --rm --entrypoint= --user $(id -u):$(id -g) "
        "-v {workdir}:/sw -v {scriptDir}/build.sh:/build.sh:ro "
        "{mirrorVolume} {develVolumes} {additionalEnv} {additionalVolumes} "
        "-e WORK_DIR_OVERRIDE=/sw {extraArgs} {image} bash -ex /build.sh"
      ).format(
        image=quote(args.dockerImage),
        workdir=quote(abspath(args.workDir)),
        scriptDir=quote(scriptDir),
        extraArgs=" ".join(map(quote, args.docker_extra_args)),
        additionalEnv=" ".join(
          "-e {}={}".format(var, quote(value)) for var, value in buildEnvironment),
        # Used e.g. by O2DPG-sim-tests to find the O2DPG repository.
        develVolumes=" ".join(
          '-v "$PWD/$(readlink {pkg} || echo {pkg})":/{pkg}:rw'.format(pkg=quote(spec["package"]))
          for spec in specs.values() if spec["is_devel_pkg"]),
        additionalVolumes=" ".join(
          "-v %s" % quote(volume) for volume in args.volumes),
        mirrorVolume=("-v %s:/mirror" % quote(dirname(spec["reference"]))
                      if "reference" in spec else ""),
      )
    else:
      os.environ.update(buildEnvironment)
      build_command = "%s -e -x %s/build.sh 2>&1" % (BASH, quote(scriptDir))

    debug("Build command: %s", build_command)
    progress = ProgressPrint(
      ("Unpacking %s@%s" if cachedTarball else
       "Compiling %s@%s (use --debug for full output)") %
      (spec["package"],
       args.develPrefix if "develPrefix" in args and spec["is_devel_pkg"] else spec["version"])
    )
    err = execute(build_command, printer=progress)
    progress.end("failed" if err else "done", err)
    report_event("BuildError" if err else "BuildSuccess", spec["package"], " ".join((
      args.architecture,
      spec["version"],
      spec["commit_hash"],
      os.environ["ALIBUILD_ALIDIST_HASH"][:10],
    )))

    updatablePkgs = [dep for dep in spec["requires"] if specs[dep]["is_devel_pkg"]]
    if spec["is_devel_pkg"]:
      updatablePkgs.append(spec["package"])

    buildErrMsg = dedent("""\
    Error while executing {sd}/build.sh on `{h}'.
    Log can be found in {w}/BUILD/{p}-latest{devSuffix}/log
    Please upload it to CERNBox/Dropbox if you intend to request support.
    Build directory is {w}/BUILD/{p}-latest{devSuffix}/{p}.
    """).format(
      h=socket.gethostname(),
      sd=scriptDir,
      w=abspath(args.workDir),
      p=spec["package"],
      devSuffix="-" + args.develPrefix
      if "develPrefix" in args and spec["is_devel_pkg"]
      else "",
    )
    if updatablePkgs:
      buildErrMsg += dedent("""
      Note that you have packages in development mode.
      Devel sources are not updated automatically, you must do it by hand.\n
      This problem might be due to one or more outdated devel sources.
      To update all development packages required for this build it is usually sufficient to do:
      """)
      buildErrMsg += "".join("\n  ( cd %s && git pull --rebase )" % dp for dp in updatablePkgs)

    dieOnError(err, buildErrMsg.strip())

    # We need to create 2 sets of links, once with the full requires,
    # once with only direct dependencies, since that's required to
    # register packages in Alien.
    createDistLinks(spec, specs, args, syncHelper, "dist", "full_requires")
    createDistLinks(spec, specs, args, syncHelper, "dist-direct", "requires")
    createDistLinks(spec, specs, args, syncHelper, "dist-runtime", "full_runtime_requires")

    # Make sure not to upload local-only packages! These might have been
    # produced in a previous run with a read-only remote store.
    if not spec["revision"].startswith("local"):
      syncHelper.upload_symlinks_and_tarball(spec)

  if not args.onlyDeps:
      banner("Build of %s successfully completed on `%s'.\n"
             "Your software installation is at:"
             "\n\n  %s\n\n"
             "You can use this package by loading the environment:"
             "\n\n  alienv enter %s/latest-%s",
             mainPackage, socket.gethostname(),
             abspath(join(args.workDir, args.architecture)),
             mainPackage, mainBuildFamily)
  else:
      banner("Successfully built dependencies for package %s on `%s'.\n",
             mainPackage, socket.gethostname()
            )
  for spec in specs.values():
    if spec["is_devel_pkg"]:
      banner("Build directory for devel package %s:\n%s/BUILD/%s-latest%s/%s",
             spec["package"], abspath(args.workDir), spec["package"],
             ("-" + args.develPrefix) if "develPrefix" in args else "",
             spec["package"])
  if untrackedFilesDirectories:
    banner("Untracked files in the following directories resulted in a rebuild of "
           "the associated package and its dependencies:\n%s\n\nPlease commit or remove them to avoid useless rebuilds.", "\n".join(untrackedFilesDirectories))
  debug("Everything done")
