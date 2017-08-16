from alibuild_helpers.cmd import execute
from alibuild_helpers.utilities import format
from alibuild_helpers.utilities import parseRecipe, getPackageList, getRecipeReader, parseDefaults, readDefaults
from alibuild_helpers.log import debug, error, warning, banner, info
from alibuild_helpers.log import dieOnError
from alibuild_helpers.workarea import updateReferenceRepos

from os.path import basename, join
import os.path as path
import os
try:
  from collections import OrderedDict
except ImportError:
  from ordereddict import OrderedDict

def parsePackagesDefinition(pkgname):
  return [ dict(zip(["name","ver"], y.split("@")[0:2]))
           for y in [ x+"@" for x in list(filter(lambda y: y, pkgname.split(","))) ] ]

def doInit(setdir, configDir, pkgname, referenceSources, dist, defaults, dryRun):
  assert(pkgname != None)
  assert(type(dist) == dict)
  assert(sorted(dist.keys()) == ["repo", "ver"])
  pkgs = parsePackagesDefinition(pkgname)
  assert(type(pkgs) == list)
  if dryRun:
    info("This will initialise local checkouts for %s\n"
         "--dry-run / -n specified. Doing nothing." % ",".join(x["name"] for x in pkgs))
    exit(0)
  try:
    path.exists(setdir) or os.mkdir(setdir)
    path.exists(referenceSources) or os.makedirs(referenceSources)
  except OSError as e:
    error(str(e))
    exit(1)

  # Fetch recipes first if necessary
  if path.exists(configDir):
    warning("using existing recipes from %s" % configDir)
  else:
    cmd = format("git clone %(repo)s%(branch)s %(cd)s",
                 repo=dist["repo"] if ":" in dist["repo"] else "https://github.com/%s" % dist["repo"],
                 branch=" -b "+dist["ver"] if dist["ver"] else "",
                 cd=configDir)
    debug(cmd)
    err = execute(cmd)
    dieOnError(err!=0, "cannot clone recipes")

  # Use standard functions supporting overrides and taps. Ignore all disables
  # and system packages as they are irrelevant in this context
  specs = {}
  defaultsReader = lambda: readDefaults(configDir, defaults, error)
  (err, overrides, taps) = parseDefaults([], defaultsReader, debug)
  getPackageList(packages=[ p["name"] for p in pkgs ],
                 specs=specs,
                 configDir=configDir,
                 preferSystem=False,
                 noSystem=True,
                 architecture="",
                 disable=[],
                 defaults=defaults,
                 dieOnError=lambda *x, **y: None,
                 performPreferCheck=lambda *x, **y: (1, ""),
                 performRequirementCheck=lambda *x, **y: (0, ""),
                 overrides=overrides,
                 taps=taps,
                 log=debug)

  for p in pkgs:
    spec = specs.get(p["name"])
    dieOnError(spec is None, "cannot find recipe for package %s" % p["name"])
    dest = join(setdir, spec["package"])
    writeRepo = spec.get("write_repo", spec.get("source"))
    dieOnError(not writeRepo, "package %s has no source field and cannot be developed" % spec["package"])
    if path.exists(dest):
      warning("not cloning %s since it already exists" % spec["package"])
      continue
    p["ver"] = p["ver"] if p["ver"] else spec.get("tag", spec["version"])
    debug("cloning %s%s for development" % (spec["package"], " version "+p["ver"] if p["ver"] else ""))
    updateReferenceRepos(referenceSources, spec["package"], spec)
    cmd = format("git clone %(readRepo)s%(branch)s --reference %(refSource)s %(cd)s && " +
                 "cd %(cd)s && git remote set-url --push origin %(writeRepo)s",
                 readRepo=spec["source"],
                 writeRepo=writeRepo,
                 branch=" -b "+p["ver"] if p["ver"] else "",
                 refSource=join(referenceSources, spec["package"].lower()),
                 cd=dest)
    debug(cmd)
    err = execute(cmd)
    dieOnError(err!=0, "cannot clone %s%s" %
                       (spec["package"], " version "+p["ver"] if p["ver"] else ""))
  banner(format("Development directory %(d)s created%(pkgs)s",
         pkgs=" for "+", ".join([ x["name"].lower() for x in pkgs ]) if pkgs else "",
         d=setdir))
