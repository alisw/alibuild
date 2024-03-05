from alibuild_helpers.git import git, Git
from alibuild_helpers.utilities import getPackageList, parseDefaults, readDefaults, validateDefaults
from alibuild_helpers.log import debug, error, warning, banner, info
from alibuild_helpers.log import dieOnError
from alibuild_helpers.workarea import cleanup_git_log, updateReferenceRepoSpec

from os.path import join
import os.path as path
import os, sys

def parsePackagesDefinition(pkgname):
  return [ dict(zip(["name","ver"], y.split("@")[0:2]))
           for y in [ x+"@" for x in list(filter(lambda y: y, pkgname.split(","))) ] ]

def doInit(args):
  assert(args.pkgname != None)
  assert(type(args.dist) == dict)
  assert(sorted(args.dist.keys()) == ["repo", "ver"])
  pkgs = parsePackagesDefinition(args.pkgname)
  assert(type(pkgs) == list)
  if args.dryRun:
    info("This will initialise local checkouts for %s\n"
         "--dry-run / -n specified. Doing nothing.", ",".join(x["name"] for x in pkgs))
    sys.exit(0)
  try:
    path.exists(args.develPrefix) or os.mkdir(args.develPrefix)
    path.exists(args.referenceSources) or os.makedirs(args.referenceSources)
  except OSError as e:
    error("%s", e)
    sys.exit(1)

  # Fetch recipes first if necessary
  if path.exists(args.configDir):
    warning("using existing recipes from %s", args.configDir)
  else:
    cmd = ["clone", "--origin", "upstream",
           args.dist["repo"] if ":" in args.dist["repo"] else "https://github.com/" + args.dist["repo"]]
    if args.dist["ver"]:
      cmd.extend(["-b", args.dist["ver"]])
    cmd.append(args.configDir)
    git(cmd)

  # Use standard functions supporting overrides and taps. Ignore all disables
  # and system packages as they are irrelevant in this context
  specs = {}
  defaultsReader = lambda: readDefaults(args.configDir, args.defaults, lambda msg: error("%s", msg), args.architecture)
  (err, overrides, taps) = parseDefaults([], defaultsReader, debug)
  (_,_,_,validDefaults) = getPackageList(packages=[ p["name"] for p in pkgs ],
                                         specs=specs,
                                         configDir=args.configDir,
                                         preferSystem=False,
                                         noSystem=True,
                                         architecture="",
                                         disable=[],
                                         defaults=args.defaults,
                                         performPreferCheck=lambda *x, **y: (1, ""),
                                         performRequirementCheck=lambda *x, **y: (0, ""),
                                         performValidateDefaults=lambda spec : validateDefaults(spec, args.defaults),
                                         overrides=overrides,
                                         taps=taps,
                                         log=debug)
  dieOnError(validDefaults and args.defaults not in validDefaults,
             "Specified default `%s' is not compatible with the packages you want to build.\n" % args.defaults +
             "Valid defaults:\n\n- " +
             "\n- ".join(sorted(validDefaults)))

  for p in pkgs:
    spec = specs.get(p["name"])
    spec["is_devel_pkg"] = False
    spec["scm"] = Git()
    dieOnError(spec is None, "cannot find recipe for package %s" % p["name"])
    dest = join(args.develPrefix, spec["package"])
    writeRepo = spec.get("write_repo", spec.get("source"))
    dieOnError(not writeRepo, "package %s has no source field and cannot be developed" % spec["package"])
    if path.exists(dest):
      warning("not cloning %s since it already exists", spec["package"])
      continue
    p["ver"] = p["ver"] if p["ver"] else spec.get("tag", spec["version"])
    debug("cloning %s%s for development", spec["package"], " version "+p["ver"] if p["ver"] else "")

    updateReferenceRepoSpec(args.referenceSources, spec["package"], spec, True, False)

    cmd = ["clone", "--origin", "upstream", spec["source"],
           "--reference", join(args.referenceSources, spec["package"].lower())]
    if p["ver"]:
      cmd.extend(["-b", p["ver"]])
    cmd.append(dest)
    git(cmd)
    git(("remote", "set-url", "--push", "upstream", writeRepo), directory=dest)

    # Make it point relatively to the mirrors for relocation: as per Git specifics, the path has to
    # be relative to the repository's `.git` directory. Don't do it if no common path is found
    repoObjects = os.path.join(os.path.realpath(dest), ".git", "objects")
    refObjects = os.path.join(os.path.realpath(args.referenceSources),
                              spec["package"].lower(), "objects")
    repoAltConf = os.path.join(repoObjects, "info", "alternates")
    if len(os.path.commonprefix([repoObjects, refObjects])) > 1:
      with open(repoAltConf, "w") as fil:
        fil.write(os.path.relpath(refObjects, repoObjects) + "\n")

  banner("Development directory %s created%s", args.develPrefix,
         " for "+", ".join(x["name"].lower() for x in pkgs) if pkgs else "")
