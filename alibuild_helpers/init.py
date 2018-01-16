from alibuild_helpers.cmd import execute
from alibuild_helpers.utilities import format
from alibuild_helpers.utilities import parseRecipe, getPackageList, getRecipeReader, parseDefaults, readDefaults, validateDefaults
from alibuild_helpers.log import debug, error, warning, banner, info
from alibuild_helpers.log import dieOnError
from alibuild_helpers.workarea import updateReferenceRepoSpec

from os.path import abspath, basename, join
import os.path as path
import os
try:
  from collections import OrderedDict
except ImportError:
  from ordereddict import OrderedDict

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
         "--dry-run / -n specified. Doing nothing." % ",".join(x["name"] for x in pkgs))
    exit(0)
  try:
    path.exists(args.develPrefix) or os.mkdir(args.develPrefix)
    path.exists(args.referenceSources) or os.makedirs(args.referenceSources)
  except OSError as e:
    error(str(e))
    exit(1)

  # Fetch recipes first if necessary
  if path.exists(args.configDir):
    warning("using existing recipes from %s" % args.configDir)
  else:
    cmd = format("git clone %(repo)s%(branch)s %(cd)s",
                 repo=args.dist["repo"] if ":" in args.dist["repo"] else "https://github.com/%s" % args.dist["repo"],
                 branch=" -b "+args.dist["ver"] if args.dist["ver"] else "",
                 cd=args.configDir)
    debug(cmd)
    err = execute(cmd)
    dieOnError(err!=0, "cannot clone recipes")

  # Use standard functions supporting overrides and taps. Ignore all disables
  # and system packages as they are irrelevant in this context
  specs = {}
  defaultsReader = lambda: readDefaults(args.configDir, args.defaults, error)
  (err, overrides, taps) = parseDefaults([], defaultsReader, debug)
  (_,_,_,validDefaults) = getPackageList(packages=[ p["name"] for p in pkgs ],
                                         specs=specs,
                                         configDir=args.configDir,
                                         preferSystem=False,
                                         noSystem=True,
                                         architecture="",
                                         disable=[],
                                         defaults=args.defaults,
                                         dieOnError=lambda *x, **y: None,
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
    dieOnError(spec is None, "cannot find recipe for package %s" % p["name"])
    dest = join(args.develPrefix, spec["package"])
    writeRepo = spec.get("write_repo", spec.get("source"))
    dieOnError(not writeRepo, "package %s has no source field and cannot be developed" % spec["package"])
    if path.exists(dest):
      warning("not cloning %s since it already exists" % spec["package"])
      continue
    p["ver"] = p["ver"] if p["ver"] else spec.get("tag", spec["version"])
    debug("cloning %s%s for development" % (spec["package"], " version "+p["ver"] if p["ver"] else ""))

    updateReferenceRepoSpec(args.referenceSources, spec["package"], spec, True)
    cmd = format("git clone %(readRepo)s%(branch)s --reference %(refSource)s %(cd)s && " +
                 "cd %(cd)s && git remote set-url --push origin %(writeRepo)s",
                 readRepo=spec["source"],
                 writeRepo=writeRepo,
                 branch=" -b "+p["ver"] if p["ver"] else "",
                 refSource=join(args.referenceSources, spec["package"].lower()),
                 cd=dest)
    debug(cmd)
    err = execute(cmd)
    dieOnError(err!=0, "cannot clone %s%s" %
                       (spec["package"], " version "+p["ver"] if p["ver"] else ""))
  banner(format("Development directory %(d)s created%(pkgs)s",
         pkgs=" for "+", ".join([ x["name"].lower() for x in pkgs ]) if pkgs else "",
         d=args.develPrefix))
