from collections import OrderedDict
import concurrent.futures
from glob import glob
import importlib
import json
import os
from os import makedirs, unlink, readlink, rmdir
from os.path import abspath, exists, basename, dirname, join, realpath
import re
from shlex import quote
import shutil
import socket
import sys
from textwrap import dedent
import time
import yaml

from alibuild_helpers import __version__
from alibuild_helpers.analytics import report_event
from alibuild_helpers.cmd import execute, DockerRunner, BASH, install_wrapper_script
from alibuild_helpers.git import git, clone_speedup_options, Git
from alibuild_helpers.log import debug, info, banner, warning, dieOnError
from alibuild_helpers.log import log_current_package, ProgressPrint
from alibuild_helpers.scm import SCMError
from alibuild_helpers.sl import Sapling
from alibuild_helpers.sync import remote_from_url
from alibuild_helpers.utilities import Hasher, getPackageList, asList, yamlDump, prunePaths
from alibuild_helpers.utilities import call_ignoring_oserrors, symlink
from alibuild_helpers.utilities import parseDefaults, readDefaults, validateDefaults
from alibuild_helpers.utilities import resolve_store_path, resolve_tag, resolve_version
from alibuild_helpers.workarea import update_refs, updateReferenceRepoSpec


def devel_package_branch(spec):
    try:
        package_source = spec["source"]
    except KeyError:
        return ""
    if not exists(package_source):
        return ""
    return spec["scm"].branchOrRef(directory=package_source).replace("/", "-")


def parallel_scm_wrapper(specs, function, *extra_args):
    """Run FUNCTION, which performs an SCM operation, in parallel.

    If any operation fails with an SCMError, then it is retried, while
    allowing the user to input their credentials if required.

    FUNCTION must take a spec as a first argument, then any number of
    EXTRA_ARGS, and finally a allow_prompt= kwarg which indicates whether user
    interaction is allowed.
    """
    progress = ProgressPrint("Updating repositories")
    requires_auth = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_package = {
          executor.submit(function, spec, *extra_args, allow_prompt=False):
          spec["package"]
          for spec in specs.values()
        }
        for i, future in enumerate(concurrent.futures.as_completed(future_to_package)):
            fetched_pkg = future_to_package[future]
            progress("[%d/%d] Updating repo for %s", i,
                     len(future_to_package) + len(requires_auth), fetched_pkg)
            try:
                future.result()
            except SCMError:
                # The SCM failed. Let's assume this is because the user needs
                # to supply a password.
                debug("%r requires auth; will prompt later", fetched_pkg)
                requires_auth.add(fetched_pkg)
            except Exception as exc:
                raise RuntimeError("Error on fetching %r. Aborting." %
                                   fetched_pkg) from exc

    # Now execute git commands for private packages one-by-one, so the user can
    # type their username and password without multiple prompts interfering.
    for i, package in enumerate(requires_auth):
        progress("[%d/%d] Updating repo for %s", len(future_to_package) + i,
                 len(future_to_package) + len(requires_auth), package)
        banner("If prompted now, enter your username and password for %s below\n"
               "If you are prompted too often, see: "
               "https://alisw.github.io/alibuild/troubleshooting.html"
               "#alibuild-keeps-asking-for-my-password",
               specs[package]["source"])
        function(specs[package], *extra_args, allow_prompt=True)

    progress.end("done")


# Creates a directory in the store which contains symlinks to the package
# and its direct / indirect dependencies
def create_dist_links(spec, specs, architecture, work_dir, repo_type, requires_type):
    # At the point we call this function, spec has a single, definitive hash.
    target_dir = "{work_dir}/TARS/{arch}/{repo}/{package}/{package}-{version}-{revision}" \
        .format(work_dir=work_dir, arch=architecture, repo=repo_type, **spec)
    shutil.rmtree(target_dir.encode("utf-8"), ignore_errors=True)
    makedirs(target_dir, exist_ok=True)
    for pkg in [spec["package"]] + list(spec[requires_type]):
        dep_tarball = "../../../../../TARS/{arch}/store/{short_hash}/{hash}/{package}-{version}-{revision}.{arch}.tar.gz" \
            .format(arch=architecture, short_hash=specs[pkg]["hash"][:2], **specs[pkg])
        symlink(dep_tarball, target_dir)


def store_hashes(package, specs, consider_relocation):
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
    if sys.version_info[0] < 3 and key in spec and isinstance(spec[key], OrderedDict):
      # Python 2: use YAML dict order to prevent changing hashes
      h_all(str(yaml.safe_load(yamlDump(spec[key]))))
    elif key not in spec:
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
    h_all(specs[dep]["hash"] if spec.get("is_devel_pkg", False) else hash_and_devel_hash)
    # The deps_hash should always change, however, so we actually rebuild the
    # dependent package (even if incrementally).
    dh(hash_and_devel_hash)

  if spec.get("is_devel_pkg", False) and "incremental_recipe" in spec:
    h_all(spec["incremental_recipe"])
    ih = Hasher()
    ih(spec["incremental_recipe"])
    spec["incremental_hash"] = ih.hexdigest()
  elif spec.get("is_devel_pkg", False):
    h_all(spec["devel_hash"])

  if consider_relocation and "relocate_paths" in spec:
    h_all("relocate:" + " ".join(sorted(spec["relocate_paths"])))

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
  if not old:
      return new
  if not new:
      return old
  old_rev, old_hash, _ = old
  new_rev, new_hash, _ = new
  old_is_local, new_is_local = old_rev.startswith("local"), new_rev.startswith("local")
  # If one is local and one is remote, return the remote one.
  if old_is_local and not new_is_local:
      return new
  if new_is_local and not old_is_local:
      return old
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


def topological_sort(nodes, edges):
    """Sort NODES (a list of package names) topologically, according to dependencies in EDGES.

    EDGES is a list of (package, dependency) pairs, one for each dependency.
    """
    # Algorithm adapted from:
    # http://www.stoimen.com/blog/2012/10/01/computer-algorithms-topological-sort-of-a-graph/
    leaves = [pkg for pkg in nodes if not any(other == pkg for other, _ in edges)]
    sorted_nodes = []
    while leaves:
        current_pkg = leaves.pop(0)
        sorted_nodes.append(current_pkg)
        # Find every package that depended on the current one.
        new_leaves = {pkg for pkg, dep in edges if dep == current_pkg}
        # Stop blocking packages that depend on the current one...
        edges = [(pkg, dep) for pkg, dep in edges if dep != current_pkg]
        # ...but keep blocking those that still depend on other stuff!
        has_predecessors = {m for pkg, _ in edges for m in new_leaves if pkg == m}
        leaves.extend(new_leaves - has_predecessors)
    return sorted_nodes


def prepare_builds(args, parser, remote):
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

    err, overrides, taps = parseDefaults(
      args.disable,
      lambda: readDefaults(args.configDir, args.defaults, parser.error, args.architecture),
      debug,
    )
    dieOnError(err, err)

    specDir = join(workDir, "SPECS")
    makedirs(specDir, exist_ok=True)

    # If the alidist workdir contains a .sl directory, we use Sapling as SCM;
    # otherwise we default to git (without checking for the actual presence of
    # .git).
    # We do it this way, because one unit test uses an embedded folder in the
    # alibuild source, which therefore does not contain a .git directory and
    # falls back to the alibuild git commit.
    scm = exists("%s/.sl" % args.configDir) and Sapling() or Git()
    try:
        checkedOutCommitName = scm.checkedOutCommitName(directory=args.configDir)
    except SCMError:
        dieOnError(True, "Cannot find SCM directory in %s." % args.configDir)
    os.environ["ALIBUILD_ALIDIST_HASH"] = checkedOutCommitName

    debug("Building for architecture %s", args.architecture)
    debug("Number of parallel builds: %d", args.jobs)
    debug("Using aliBuild from alibuild@%s recipes in alidist@%s",
          __version__ or "unknown", os.environ["ALIBUILD_ALIDIST_HASH"])

    install_wrapper_script("git", workDir)

    specs = {}   # getPackageList mutates this variable
    with DockerRunner(args.dockerImage, args.docker_extra_args) as getstatusoutput_docker:
      systemPackages, ownPackages, failed, validDefaults = getPackageList(
          packages=args.pkgname,
          specs=specs,
          configDir=args.configDir,
          preferSystem=args.preferSystem,
          noSystem=args.noSystem,
          architecture=args.architecture,
          disable=args.disable,
          force_rebuild=args.force_rebuild,
          defaults=args.defaults,
          performPreferCheck=lambda pkg, cmd: getstatusoutput_docker(cmd),
          performRequirementCheck=lambda pkg, cmd: getstatusoutput_docker(cmd),
          performValidateDefaults=lambda spec: validateDefaults(spec, args.defaults),
          overrides=overrides,
          taps=taps,
          log=debug,
      )

    dieOnError(validDefaults and args.defaults not in validDefaults,
               "Specified default `%s' is not compatible with the packages you want to build.\n"
               "Valid defaults:\n\n- %s" % (args.defaults, "\n- ".join(sorted(validDefaults))))
    dieOnError(failed,
               "The following packages are system requirements and could not be found:\n\n- %s\n\n"
               "Please run:\n\n\taliDoctor --defaults %s %s\n\nto get a full diagnosis." %
               ("\n- ".join(sorted(list(failed))), args.defaults, " ".join(args.pkgname)))

    for x in specs.values():
      x["requires"] = [r for r in x["requires"] if r not in args.disable]
      x["build_requires"] = [r for r in x["build_requires"] if r not in args.disable]
      x["runtime_requires"] = [r for r in x["runtime_requires"] if r not in args.disable]

    if systemPackages:
      banner("aliBuild can take the following packages from the system and will not build them:\n  %s",
             ", ".join(systemPackages))
    if ownPackages:
      banner("The following packages cannot be taken from the system and will be built:\n  %s",
             ", ".join(ownPackages))

    # Do topological sort to have the correct build order even in the
    # case of non-tree like dependencies.
    buildOrder = topological_sort(
      [p["package"] for p in specs.values()],
      [(p["package"], d) for p in specs.values() for d in p["requires"]],
    )

    # Check if any of the packages can be picked up from a local checkout
    develPkgs = []
    if not args.forceTracked:
      develCandidates = [basename(d) for d in glob("*") if os.path.isdir(d)]
      develCandidatesUpper = [basename(d).upper() for d in glob("*") if os.path.isdir(d)]
      develPkgs = [p for p in buildOrder
                   if p in develCandidates and p not in args.noDevel]
      develPkgsUpper = [(p, p.upper()) for p in buildOrder
                        if p.upper() in develCandidatesUpper and p not in args.noDevel]
      dieOnError(set(develPkgs) != {x for x, _ in develPkgsUpper},
                 "The following development packages have the wrong spelling: " +
                 ", ".join({x.strip() for x, _ in develPkgsUpper} - set(develPkgs)) +
                 ".\nPlease check your local checkout and adapt to the correct one indicated.")

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

    # Fetch remote scm_refs for all repos, so we know what needs updating.
    parallel_scm_wrapper(specs, update_refs, args.referenceSources, args.fetchRepos)

    # This is the list of packages which have untracked files in their
    # source directory, and which are rebuilt every time. We will warn
    # about them at the end of the build.
    untrackedFilesDirectories = []

    # Resolve the tag to the actual commit ref
    for p in buildOrder:
      spec = specs[p]
      spec["commit_hash"] = "0"
      # This is a development package (i.e. a local directory named like
      # spec["package"]), but there is no "source" key in its alidist recipe,
      # so there shouldn't be any code for it! Presumably, a user has
      # mistakenly named a local directory after one of our packages.
      dieOnError("source" not in spec and spec["package"] in develPkgs,
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
        if spec["package"] in develPkgs:
          # Devel package: we get the commit hash from the checked source, not from remote.
          spec["commit_hash"] = spec["scm"].checkedOutCommitName(directory=spec["source"]).strip()
          local_hash, untracked = hash_local_changes(spec)
          untrackedFilesDirectories.extend(untracked)
          spec["devel_hash"] = spec["commit_hash"] + local_hash
          spec["tag"] = args.develPrefix if "develPrefix" in args else devel_package_branch(spec)
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
      return {}, [], []    # do nothing

    log_current_package(None, buildOrder[-1], specs, getattr(args, "develPrefix", None))
    debug("Main package is %s@%s", buildOrder[-1], specs[buildOrder[-1]]["commit_hash"])

    # Now that we have the main package set, we can print out Useful information
    # which we will be able to associate with this build. Also lets make sure each package
    # we need to build can be built with the current default.
    for spec in (specs[pkg] for pkg in buildOrder):
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
      info("--dry-run / -n specified. Not building.")
      return {}, [], []   # do nothing

    report_event("install", "{p} disabled={dis} devel={dev} system={sys} own={own} deps={deps}".format(
      p=args.pkgname,
      dis=",".join(sorted(args.disable)),
      dev=",".join(sorted(develPkgs)),
      sys=",".join(sorted(systemPackages)),
      own=",".join(sorted(ownPackages)),
      deps=",".join(buildOrder[:-1])
    ), args.architecture)

    return specs, buildOrder, untrackedFilesDirectories


def find_revision_number(spec, architecture, defaults, work_dir, devel_prefix, for_upload,
                         assign_new_as_fallback=False):
    """"""
    # Decide how it should be called, based on the hash and what is already
    # available.
    debug("Checking for packages already built.")

    # Make sure this regex broadly matches the regex below that parses the
    # symlink's target. Overly-broadly matching the version, for example, can
    # lead to false positives that trigger a warning below.
    links_regex = re.compile(r"{package}-{version}-(?:local)?[0-9]+\.{arch}\.tar\.gz".format(
      package=re.escape(spec["package"]),
      version=re.escape(spec["version"]),
      arch=re.escape(architecture),
    ))
    symlink_dir = join(work_dir, "TARS", architecture, spec["package"])
    try:
      packages = [join(symlink_dir, link)
                  for link in os.listdir(symlink_dir)
                  if links_regex.fullmatch(link)]
    except OSError:
      # If symlink_dir does not exist or cannot be accessed, return an empty
      # list of packages.
      packages = []
    del links_regex, symlink_dir

    # In case there is no installed software, revision is 1
    # If there is already an installed package:
    # - Remove it if we do not know its hash
    # - Use the latest number in the version, to decide its revision
    debug("%d packages already built using this version:\n%s",
          len(packages), "\n".join(packages))

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
    possibleDevelPrefix = devel_prefix if devel_prefix is not None else \
        devel_package_branch(spec)
    if spec["is_devel_pkg"]:
        spec["devel_prefix"] = possibleDevelPrefix
    else:
        spec["devel_prefix"] = ""

    if possibleDevelPrefix:
      spec["build_family"] = "%s-%s" % (possibleDevelPrefix, defaults)
    else:
      spec["build_family"] = defaults

    candidate = None
    busyRevisions = set()
    revisionPrefix = "" if for_upload else "local"
    matcher = re.compile(r"\.\./\.\./{a}/store/[0-9a-f]{{2}}/([0-9a-f]*)/{p}-{v}-((?:local)?[0-9]*).{a}.tar.gz$".format(
        a=architecture,
        p=spec["package"],
        v=spec["version"],
    ))
    for link in packages:
      match = matcher.match(readlink(link))
      if not match:
        warning("Symlink %s -> %s couldn't be parsed", link, readlink(link))
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
      if for_upload and "local" in revision:
        debug("Skipping revision %s because we want to upload later", revision)
        continue

      # If we have an hash match, we use the old revision for the package
      # and we do not need to build it. Because we prefer reusing remote
      # revisions, only store a local revision if there is no other candidate
      # for reuse yet.
      candidate = better_tarball(spec, candidate, (revision, rev_hash, link))

    if candidate:
      spec["revision"], rev_hash, link = candidate
      # Remember what hash we're actually using.
      spec["local_revision_hash" if spec["revision"].startswith("local")
           else "remote_revision_hash"] = rev_hash
      if spec["is_devel_pkg"] and "incremental_recipe" in spec:
        spec["obsolete_tarball"] = link
      else:
        debug("Package %s with hash %s is already found in %s. Not building.",
              spec["package"], rev_hash, link)
    elif assign_new_as_fallback:
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


def assign_revision_number(p, specs, syncHelper, work_dir, architecture, defaults, devel_prefix):
    spec = specs[p]

    # Calculate the hashes. We must do this in build order so that we can
    # guarantee that the hashes of the dependencies are calculated first.
    debug("Calculating hash.")
    debug("spec = %r", spec)
    store_hashes(p, specs, consider_relocation=architecture.startswith("osx"))
    debug("Hashes for recipe %s are %s (remote); %s (local)", p,
          ", ".join(spec["remote_hashes"]), ", ".join(spec["local_hashes"]))

    if spec["is_devel_pkg"] and getattr(syncHelper, "writeStore", None):
        warning("Disabling remote write store from now since %s is a development package.", spec["package"])
        syncHelper.writeStore = ""

    # To speed things up, first see if we can get a matching revision number
    # from any of the symlinks we already have locally.
    find_revision_number(spec, architecture, defaults, work_dir, devel_prefix,
                         # We can tell that the remote store is read-only if
                         # it has an empty or no writeStore property.
                         for_upload=getattr(syncHelper, "writeStore", ""),
                         assign_new_as_fallback=False)

    # If we didn't find any matching revision number from the symlinks we
    # already have locally, then fetch symlinks from the remote and try again.
    if "revision" not in spec:
        debug("Fetching symlinks from remote store")
        syncHelper.fetch_symlinks(spec)
        find_revision_number(spec, architecture, defaults, work_dir, devel_prefix,
                             for_upload=getattr(syncHelper, "writeStore", ""),
                             assign_new_as_fallback=True)

    # Now we know whether we're using a local or remote package, so we can set
    # the proper hash and tarball directory.
    if spec["revision"].startswith("local"):
        spec["hash"] = spec["local_revision_hash"]
    else:
        spec["hash"] = spec["remote_revision_hash"]


def symlink_build(spec, specs, architecture, work_dir):
    # Recreate symlinks to this package build.
    if spec["is_devel_pkg"]:
      debug("Creating symlinks to builds of devel package %s", spec["package"])
      symlink(spec["hash"], f"{work_dir}/BUILD/{spec['package']}-latest")
      if spec["devel_prefix"]:
          symlink(spec["hash"], f"{work_dir}/BUILD/{spec['package']}-latest-{spec['devel_prefix']}")
    # Last package built gets a "latest" mark.
    symlink(f"{spec['version']}-{spec['revision']}",
            join(work_dir, architecture, spec["package"], "latest"))
    # Latest package built for a given devel prefix gets a "latest-%(family)s" mark.
    if spec["build_family"]:
        symlink(f"{spec['version']}-{spec['revision']}",
                join(work_dir, architecture, spec["package"], "latest-" + spec["build_family"]))
    # We need to create 2 sets of links, once with the full requires,
    # once with only direct dependencies, since that's required to
    # register packages in Alien.
    create_dist_links(spec, specs, architecture, work_dir, "dist", "full_requires")
    create_dist_links(spec, specs, architecture, work_dir, "dist-direct", "requires")
    create_dist_links(spec, specs, architecture, work_dir, "dist-runtime", "full_runtime_requires")


def cleanup_after_build(spec, work_dir, devel_prefix=None, aggressive=False):
    if "obsolete_tarball" in spec:
        unlink(realpath(spec["obsolete_tarball"]))
        unlink(spec["obsolete_tarball"])
    cleanupDirs = [join(work_dir, "BUILD", spec["hash"]),
                   join(work_dir, "INSTALLROOT", spec["hash"])]
    if aggressive:
        cleanupDirs.append(join(work_dir, "SOURCES", spec["package"]))
    debug("Cleaning up:\n%s", "\n".join(cleanupDirs))

    for d in cleanupDirs:
        shutil.rmtree(d.encode("utf8"), True)
    call_ignoring_oserrors(unlink, "{w}/BUILD/{p}-latest".format(w=work_dir, p=spec["package"]))
    if devel_prefix:
        call_ignoring_oserrors(unlink, "{w}/BUILD/{p}-latest-{dp}".format(w=work_dir, p=spec["package"], dp=devel_prefix))
    call_ignoring_oserrors(rmdir, join(work_dir, "BUILD"))
    call_ignoring_oserrors(rmdir, join(work_dir, "INSTALLROOT"))


def final_installation_dir(spec, architecture, work_dir):
    return "%s/%s/%s/%s-%s" % (
        work_dir,
        architecture,
        spec["package"],
        spec["version"],
        spec["revision"],
    )


def is_already_built(spec, is_devel_pkg, architecture, work_dir):
    """Return whether the given package has been built and installed before with the same hash."""
    def read_hash_file(*file_name_parts):
        try:
            with open(join(*file_name_parts)) as fp:
                return fp.read().strip("\n")
        except IOError:
            return "0"

    if is_devel_pkg:
        return spec["devel_hash"] + spec["deps_hash"] == read_hash_file(
            work_dir, "BUILD", spec["hash"], spec["package"], ".build_succeeded",
        )

    prev_build_hash = read_hash_file(
        final_installation_dir(spec, architecture, work_dir), ".build-hash",
    )
    if prev_build_hash == spec["hash"]:
        return True
    if prev_build_hash != "0":
        debug("Mismatch between local area (%s) and the one which I should build (%s). Redoing.",
              prev_build_hash, spec["hash"])
    return False


def build_or_unpack_package(package, specs, args):
    spec = specs[package]

    # shutil.rmtree under Python 2 fails when hashFile is unicode and the
    # directory contains files with non-ASCII names, e.g. Golang/Boost.
    shutil.rmtree(final_installation_dir(spec, args.architecture, args.workDir).encode("utf-8"), True)

    # The actual build script.
    reference_statement = ""
    if "reference" in spec:
      reference_statement = "export GIT_REFERENCE=${GIT_REFERENCE_OVERRIDE:-%s}/%s" % (dirname(spec["reference"]), basename(spec["reference"]))

    debug("spec = %r", spec)

    try:
      with open(join(dirname(realpath(__file__)), "build_template.sh"), "r") as fp:
        cmd_raw = fp.read()
    except OSError:
      from pkg_resources import resource_string
      cmd_raw = resource_string("alibuild_helpers", "build_template.sh")

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
        cachedTarball = re.sub("^" + re.escape(args.workDir), "/sw", spec["cachedTarball"])
    else:
        cachedTarball = spec["cachedTarball"]

    scriptDir = join(args.workDir, "SPECS", args.architecture, spec["package"],
                     spec["version"] + "-" + spec["revision"])
    makedirs(scriptDir, exist_ok=True)
    with open("%s/%s.sh" % (scriptDir, spec["package"]), "w") as recipe_f:
        recipe_f.write(spec["recipe"])
    with open("%s/build.sh" % scriptDir, "w") as build_script_f:
        build_script_f.write(cmd_raw % {
            "provenance": create_provenance_info(spec["package"], specs, args),
            "initdotsh_deps": generate_initdotsh(package, specs, args.architecture, post_build=False),
            "initdotsh_full": generate_initdotsh(package, specs, args.architecture, post_build=True),
            "workDir": args.workDir,
            "configDir": abspath(args.configDir),
            "incremental_recipe": spec.get("incremental_recipe", ":"),
            "sourceDir": (dirname(source) + "/") if source else "",
            "sourceName": basename(source) if source else "",
            "referenceStatement": reference_statement,
            "gitOptionsStatement": "" if args.docker else
            "export GIT_CLONE_SPEEDUP=" + quote(" ".join(clone_speedup_options())),
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
        ("COMMIT_HASH", commit_hash),
        ("DEPS_HASH", spec.get("deps_hash", "")),
        ("DEVEL_HASH", spec.get("devel_hash", "")),
        ("DEVEL_PREFIX", getattr(args, "develPrefix", "")),
        ("BUILD_FAMILY", spec["build_family"]),
        ("GIT_COMMITTER_NAME", "unknown"),
        ("GIT_COMMITTER_EMAIL", "unknown"),
        ("GIT_TAG", spec["tag"]),
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
            "docker run --rm --entrypoint= --user $(id -u):$(id -g) "
            "-v {workdir}:/sw -v {scriptDir}/build.sh:/build.sh:ro "
            "-e GIT_REFERENCE_OVERRIDE=/mirror -e WORK_DIR_OVERRIDE=/sw "
            "{mirrorVolume} {develVolumes} {additionalEnv} {additionalVolumes} "
            "{overrideSource} {extraArgs} {image} bash -ex /build.sh"
        ).format(
            image=quote(args.dockerImage),
            workdir=quote(abspath(args.workDir)),
            scriptDir=quote(abspath(scriptDir)),
            extraArgs=" ".join(map(quote, args.docker_extra_args)),
            overrideSource="-e SOURCE0_DIR_OVERRIDE=/" if source.startswith("/") else "",
            additionalEnv=" ".join(
                "-e {}={}".format(var, quote(value)) for var, value in buildEnvironment),
            # Used e.g. by O2DPG-sim-tests to find the O2DPG repository.
            develVolumes=" ".join(
                '-v "$PWD/$(readlink {pkg} || echo {pkg})":/{pkg}:rw'.format(pkg=quote(pkg))
                for pkg, spec in specs.items() if spec["is_devel_pkg"]
            ),
            additionalVolumes=" ".join("-v %s" % quote(volume) for volume in args.volumes),
            mirrorVolume=("-v %s:/mirror" % quote(dirname(spec["reference"]))
                          if "reference" in spec else ""),
        )
    else:
        os.environ.update(buildEnvironment)
        build_command = "%s -e -x %s/build.sh 2>&1" % (BASH, quote(scriptDir))

    debug("Build command: %s", build_command)
    progress = ProgressPrint("%s %s@%s (use --debug for full output)" % (
        "Unpacking tarball for" if cachedTarball else "Compiling", spec["package"],
        args.develPrefix if "develPrefix" in args and spec["is_devel_pkg"] else spec["version"],
    ))
    err = execute(build_command, printer=progress)
    progress.end("failed" if err else "done", err)
    report_event("BuildError" if err else "BuildSuccess", spec["package"], " ".join((
        args.architecture,
        spec["version"],
        spec["commit_hash"],
        os.environ["ALIBUILD_ALIDIST_HASH"][0:10],
    )))

    updatable_pkgs = [pkg for pkg in spec["requires"] if specs[pkg]["is_devel_pkg"]]
    if spec["is_devel_pkg"]:
        updatable_pkgs.append(spec["package"])

    build_error_msg = dedent("""\
    Error while executing {script_dir}/build.sh on `{hostname}'.
    Log can be found in {work_dir}/BUILD/{package}-latest{dev_suffix}/log
    Please upload it to CERNBox/Dropbox if you intend to request support.
    Build directory is {work_dir}/BUILD/{package}-latest{dev_suffix}/{package}.
    """).format(
        hostname=socket.gethostname(),
        script_dir=scriptDir,
        work_dir=abspath(args.workDir),
        package=spec["package"],
        dev_suffix=("-" + args.develPrefix) if "develPrefix" in args and spec["is_devel_pkg"] else "",
    )
    if updatable_pkgs:
        build_error_msg += dedent("""

        Note that you have packages in development mode.
        Devel sources are not updated automatically, you must do it by hand.
        This problem might be due to one or more outdated devel sources.
        To update all development packages required for this build,
        it is usually sufficient to do:
        """)
        build_error_msg += "".join("\n  ( cd %s && git pull --rebase )" % dp
                                   for dp in updatable_pkgs)

    dieOnError(err, build_error_msg)
    debug("Package %s was correctly compiled. Moving to next one.", package)


def doBuild(args, parser):
    devel_prefix = getattr(args, "develPrefix", None)
    remote = remote_from_url(args.remoteStore, args.writeStore, args.architecture,
                             args.workDir, getattr(args, "insecure", False))

    specs, build_order, repos_with_untracked_files = prepare_builds(args, parser, remote)

    # Use the selected plugin to build, instead of the default behaviour, if a
    # plugin was selected.
    if args.plugin != "legacy":
        return importlib.import_module("alibuild_helpers.%s_plugin" % args.plugin) \
                        .build_plugin(specs, args, build_order)

    if not build_order:
        banner("Nothing to be done.")
        return 0
    main_package = build_order[-1]
    log_current_package(None, main_package, specs, devel_prefix)

    # Each package needs its dependencies' hashes to be set, so iterate in build order.
    progress = ProgressPrint("Looking for packages to reuse")
    for i, package in enumerate(build_order):
        progress("[%d/%d] Resolving hash and symlinks", i, len(build_order))
        assign_revision_number(package, specs, remote, args.workDir, args.architecture,
                               args.defaults, devel_prefix)
    progress.end("done")

    # Now that we have all the information about each package we need, detect
    # any of them that have already been built and/or unpacked and skip them.
    for spec in specs.values():
        log_current_package(spec["package"], main_package, specs, devel_prefix)
        if is_already_built(spec, spec["is_devel_pkg"], args.architecture, args.workDir):
            if spec["is_devel_pkg"]:
                info("Development package %s does not need rebuild", spec["package"])
            build_order.remove(spec["package"])

    if not build_order:
        banner("Nothing to be done.")
        return 0

    # Now that we know which packages we still need to build or unpack,
    # download tarballs for as many of them as possible. Doing this after the
    # above block means we skip the download for anything we already have
    # installed.
    for package in build_order:
        specs[package]["cachedTarball"] = ""
        if specs[package]["is_devel_pkg"]:
            continue
        log_current_package(package, main_package, specs, devel_prefix)
        remote.fetch_tarball(specs[package])
        tar_hash_dir = os.path.join(args.workDir, resolve_store_path(args.architecture, specs[package]["hash"]))
        debug("Looking for cached tarball in %s", tar_hash_dir)
        tarballs = glob(os.path.join(tar_hash_dir, "*gz"))
        if tarballs:
            specs[package]["cachedTarball"] = tarballs[0]
            debug("Found tarball in %s", specs[package]["cachedTarball"])
        else:
            debug("No cached tarball found")

    def describe_package(package):
        spec = specs[package]
        action = "Compile"
        ver_suffix = ""
        if "tag" in spec:
            ver_suffix = "@ " + spec["tag"]
        if spec["cachedTarball"]:
            action = "Unpack"
        if spec["is_devel_pkg"]:
            ver_suffix = "(development package)"
        return "- %s %s %s" % (action, package, ver_suffix)

    banner("The following will be done, in order:\n%s\n",
           "\n".join(describe_package(pkg) for pkg in build_order if pkg != "defaults-release"))

    debug("Development packages are: %r",
          [spec["package"] for spec in specs.values() if spec["is_devel_pkg"]])
    if any(spec["is_devel_pkg"] for spec in specs.values()):
        banner("You have packages in development mode.\n"
               "This means their source code can be freely modified under:\n\n"
               "  %s/<package_name>\n\n"
               "aliBuild does not automatically update such packages to avoid work loss.\n"
               "In most cases this is achieved by doing in the package source directory:\n\n"
               "  git pull --rebase\n",
               os.getcwd())

    log_current_package(None, main_package, specs, devel_prefix)
    # Clone git repo if it doesn't exist, or update it if requested.
    # Only clone repos for the packages that we're actually going to compile.
    # If we'll just unpack a tarball, we don't need the git repo.
    parallel_scm_wrapper({
        pkg: spec for pkg, spec in specs.items()
        if pkg in build_order and not spec["cachedTarball"]
    }, lambda spec, allow_prompt: updateReferenceRepoSpec(
        args.referenceSources, spec["package"], spec, fetch=args.fetchRepos,
        usePartialClone=not args.docker, allowGitPrompt=allow_prompt,
    ))

    for package in build_order:
        log_current_package(package, main_package, specs, devel_prefix)
        build_or_unpack_package(package, specs, args)

        if args.autoCleanup:
            cleanup_after_build(specs[package], args.workDir, devel_prefix,
                                args.aggressiveCleanup)

        # Make sure not to upload local-only packages! These might have been
        # produced in a previous run with a read-only remote store.
        if not specs[package]["revision"].startswith("local"):
            remote.syncToRemote(package, specs[package])

    # Create "latest" symlinks to every package we built or used.
    for package in specs:
        log_current_package(package, main_package, specs, devel_prefix)
        symlink_build(specs[package], specs, args.architecture, args.workDir)

    log_current_package(None, main_package, specs, devel_prefix)
    banner("Build of %s successfully completed on `%s'.\n"
           "Your software installation is at:"
           "\n\n  %s\n\n"
           "You can use this package by loading the environment:"
           "\n\n  alienv enter %s/latest-%s",
           main_package, socket.gethostname(),
           abspath(join(args.workDir, args.architecture)),
           main_package, specs[main_package]["build_family"])

    for spec in specs.values():
        if spec["is_devel_pkg"]:
            banner("Build directory for devel package %s:\n%s/BUILD/%s-latest%s/%s",
                   spec["package"], abspath(args.workDir), spec["package"],
                   ("-" + devel_prefix) if devel_prefix is not None else "",
                   spec["package"])

    if repos_with_untracked_files:
        banner("Untracked files in the following directories resulted in a rebuild of "
               "the associated package and its dependencies:\n%s\n\n"
               "Please commit or remove them to avoid useless rebuilds.",
               "\n".join(repos_with_untracked_files))
    debug("Everything done")
    return 0
