#!/usr/bin/env python
import subprocess, re, yaml
try:
  from commands import getstatusoutput
except ImportError:
  from subprocess import getstatusoutput
from os.path import dirname, exists
import platform
import base64
from glob import glob
from os.path import basename

class SpecError(Exception):
  pass

def validateSpec(spec):
  if not spec:
    raise SpecError("Empty recipe.")
  if type(spec) != dict:
    raise SpecError("Not a YAML key / value.")
  if not "package" in spec:
    raise SpecError("Missing package field in header.")

def format(s, **kwds):
  return s % kwds

def doDetectArch(hasOsRelease, osReleaseLines, platformTuple, platformSystem, platformProcessor):
  if platformSystem == "Darwin":
    return "osx_x86-64"
  distribution, version, flavour = platformTuple
  # If platform.dist does not return something sensible,
  # let's try with /etc/os-release
  if distribution not in ["Ubuntu", "redhat", "centos"] and hasOsRelease:
    for x in osReleaseLines:
      if not "=" in x:
        continue
      key, val = x.split("=", 1)
      val = val.strip("\n \"")
      if key == "ID":
        distribution = val
      if key == "VERSION_ID":
        version = val

  if distribution.lower() == "ubuntu":
    version = version.split(".")
    version = version[0] + version[1]
  elif distribution.lower() == "debian":
    # http://askubuntu.com/questions/445487/which-ubuntu-version-is-equivalent-to-debian-squeeze
    debian_ubuntu = { "7": "1204",
                      "8": "1404" }
    if version in debian_ubuntu:
      distribution = "ubuntu"
      version = debian_ubuntu[version]
  elif distribution in ["redhat", "centos"]:
    distribution = distribution.replace("centos","slc").replace("redhat","slc").lower()

  processor = platformProcessor
  if not processor:
    # Sometimes platform.processor returns an empty string
    p = subprocess.Popen(["uname", "-m"], stdout=subprocess.PIPE)
    processor = p.stdout.read().strip()

  return format("%(d)s%(v)s_%(c)s",
                d=distribution.lower(),
                v=version.split(".")[0],
                c=processor.replace("_", "-"))

# Try to guess a good platform. This does not try to cover all the
# possibly compatible linux distributions, but tries to get right the
# common one, obvious one. If you use a Unknownbuntu which is compatible
# with Ubuntu 15.10 you will still have to give an explicit platform
# string. 
#
# FIXME: we should have a fallback for lsb_release, since platform.dist
# is going away.
def detectArch():
  hasOsRelease = exists("/etc/os-release")
  osReleaseLines = open("/etc/os-release").readlines() if hasOsRelease else []
  try:
    import platform
    platformTuple = platform.dist()
    platformSystem = platform.system()
    platformProcessor = platform.processor()
    if " " in platformProcessor:
      platformProcessor = platform.machine()
    return doDetectArch(hasOsRelease, osReleaseLines, platformTuple, platformSystem, platformProcessor)
  except:
    return None

def getVersion():
  try:
    import pkg_resources  # part of setuptools
    return pkg_resources.require("alibuild")[0].version
  except:
    cmd = "GIT_DIR=\'%s/.git\' git describe --tags" % dirname(dirname(__file__))
    err, version = getstatusoutput(cmd)
    return version if not err else "Unknown version."

def filterByArchitecture(arch, requires):
  for r in requires:
    require, matcher = ":" in r and r.split(":", 1) or (r, ".*")
    if re.match(matcher, arch):
      yield require

def readDefaults(configDir, defaults, error):
  defaultsFilename = "%s/defaults-%s.sh" % (configDir, defaults)
  if not exists(defaultsFilename):
    viableDefaults = ["- " + basename(x).replace("defaults-","").replace(".sh", "")
                      for x in glob("%s/defaults-*.sh" % configDir)]
    error(format("Default `%(d)s' does not exists. Viable options:\n%(v)s",
                 d=defaults or "<no defaults specified>",
                 v="\n".join(viableDefaults)))
  err, defaultsMeta, defaultsBody = parseRecipe(getRecipeReader(defaultsFilename))
  if err:
    error(err)
    exit(1)
  return (defaultsMeta, defaultsBody)

# Get the appropriate recipe reader depending on th filename
def getRecipeReader(url, dist=None):
  m = re.search(r'^dist:(.*)@([^@]+)$', url)
  if m and dist:
    return GitReader(url, dist)
  else:
    return FileReader(url)

# Read a recipe from a file
class FileReader(object):
  def __init__(self, url):
    self.url = url
  def __call__(self):
    return open(self.url).read()

# Read a recipe from a git repository using git show.
class GitReader(object):
  def __init__(self, url, configDir):
    self.url, self.configDir = url, configDir
  def __call__(self):
    m = re.search(r'^dist:(.*)@([^@]+)$', self.url)
    fn,gh = m.groups()
    err,d = getstatusoutput(format("GIT_DIR=%(dist)s/.git git show %(gh)s:%(fn)s.sh",
                                   dist=distdir, gh=gh, fn=fn.lower()))
    if err:
      raise RuntimeError(format("Cannot read recipe %(fn)s from reference %(gh)s.\n" +
                                "Make sure you run first (this will not alter your recipes):\n" +
                                "  cd %(dist)s && git remote update -p && git fetch --tags",
                                dist=self.configDir, gh=gh, fn=fn))
    warning("Overriding %s from reference %s" % (fn,gh))
    return d

def parseRecipe(reader):
  assert(reader.__call__)
  try:
    d = reader()
    err, spec, recipe = (None, None, None)
    header,recipe = d.split("---", 1)
    spec = yaml.safe_load(header)
    validateSpec(spec)
  except RuntimeError as e:
    err = str(e)
  except IOError as e:
    err = str(e)
  except SpecError as e:
    err = "Malformed header for %s\n%s" % (reader.url, str(e))
  except yaml.scanner.ScannerError as e:
    err = "Unable to parse %s\n%s" % (reader.url, str(e))
  except yaml.parser.ParserError as e:
    err = "Unable to parse %s\n%s" % (reader.url, str(e))
  except ValueError as e:
    err = "Unable to parse %s. Header missing." % reader.url
  return err, spec, recipe

# (Almost pure part of the defaults parsing)
# Override defaultsGetter for unit tests.
def parseDefaults(disable, defaultsGetter, log):
  defaultsMeta, defaultsBody = defaultsGetter()
  # Defaults are actually special packages. They can override metadata
  # of any other package and they can disable other packages. For
  # example they could decide to switch from ROOT 5 to ROOT 6 and they
  # could disable alien for O2. For this reason we need to parse their
  # metadata early and extract the override and disable data.
  defaultsDisable = defaultsMeta.get("disable", [])
  if type(defaultsDisable) == str:
    defaultsDisable = [defaultsDisable]
  for x in defaultsDisable:
    log("Package %s has been disabled by current default." % x)
  disable.extend(defaultsDisable)
  if type(defaultsMeta.get("overrides", {})) != dict:
    return ("overrides should be a dictionary", None, None)
  overrides = {}
  taps = {}
  for k, v in defaultsMeta.get("overrides", {}).items():
    f = k.split("@", 1)[0].lower()
    if "@" in k:
      taps[f] = "dist:"+k
    overrides[f] = v
  return (None, overrides, taps)

def getPackageList(packages, specs, configDir, preferSystem, noSystem,
                   architecture, disable, defaults, dieOnError, performPreferCheck, performRequirementCheck,
                   overrides, taps, log):
  systemPackages = set()
  ownPackages = set()
  failedRequirements = set()
  testCache = {}
  requirementsCache = {}
  while packages:
    p = packages.pop(0)
    if p in specs:
      continue
    lowerPkg = p.lower()
    filename = taps.get(lowerPkg, "%s/%s.sh" % (configDir, lowerPkg))
    err, spec, recipe = parseRecipe(getRecipeReader(filename, configDir))
    dieOnError(err, err)
    dieOnError(spec["package"].lower() != lowerPkg,
               "%s.sh has different package field: %s" % (p, spec["package"]))

    # If the package has overrides, we apply them.
    if lowerPkg in overrides:
      log("Overrides for package %s: %s" % (spec["package"], overrides[lowerPkg]))
      spec.update(overrides.get(lowerPkg, {}) or {})

    # If --always-prefer-system is passed or if prefer_system is set to true
    # inside the recipe, use the script specified in the prefer_system_check
    # stanza to see if we can use the system version of the package.
    if not noSystem and (preferSystem or re.match(spec.get("prefer_system", "(?!.*)"), architecture)):
      cmd = spec.get("prefer_system_check", "false").strip()
      if not spec["package"] in testCache:
        testCache[spec["package"]] = performPreferCheck(spec, cmd.strip())

      err, output = testCache[spec["package"]]

      if not err:
        systemPackages.update([spec["package"]])
        disable.append(spec["package"])
      else:
        ownPackages.update([spec["package"]])

    dieOnError(("system_requirement" in spec) and recipe.strip("\n\t "),
               "System requirements %s cannot have a recipe" % spec["package"])
    if re.match(spec.get("system_requirement", "(?!.*)"), architecture):
      cmd = spec.get("system_requirement_check", "false")
      if not spec["package"] in requirementsCache:
        requirementsCache[spec["package"]] = performRequirementCheck(spec, cmd.strip())

      err, output = requirementsCache[spec["package"]]
      if err:
        failedRequirements.update([spec["package"]])
        spec["version"] = "failed"
      else:
        disable.append(spec["package"])

    if spec["package"] in disable:
      continue

    # For the moment we treat build_requires just as requires.
    fn = lambda what: filterByArchitecture(architecture, spec.get(what, []))
    spec["requires"] = [x for x in fn("requires") if not x in disable]
    spec["build_requires"] = [x for x in fn("build_requires") if not x in disable]
    if spec["package"] != "defaults-" + defaults:
      spec["build_requires"].append("defaults-" + defaults)
    spec["runtime_requires"] = spec["requires"]
    spec["requires"] = spec["runtime_requires"] + spec["build_requires"]
    # Check that version is a string
    dieOnError(not isinstance(spec["version"], str),
               "In recipe \"%s\": version must be a string" % p)
    spec["tag"] = spec.get("tag", spec["version"])
    spec["version"] = spec["version"].replace("/", "_")
    spec["recipe"] = recipe.strip("\n")
    specs[spec["package"]] = spec
    packages += spec["requires"]
  return (systemPackages, ownPackages, failedRequirements)

def dockerStatusOutput(cmd, dockerImage=None, executor=getstatusoutput):
  if dockerImage:
    DOCKER_WRAPPER = """docker run %(di)s bash -c 'eval "$(echo %(c)s | base64 --decode)"'"""
    cmd = format(DOCKER_WRAPPER,
                 di=dockerImage,
                 c=base64.b64encode(cmd))
  return executor(cmd)
