#!/usr/bin/env python
import subprocess, re, yaml
import pkg_resources  # part of setuptools
from commands import getstatusoutput
from os.path import dirname, exists
import platform

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
    return doDetectArch(hasOsRelease, osReleaseLines, platformTuple, platformSystem, platformProcessor)
  except:
    return None

def getVersion():
  try:
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

def getPackageList(packages, specs, configDir, preferSystem, noSystem,
                   architecture, disable, defaults, dieOnError, performPreferCheck, performRequirementCheck):
  systemPackages = set()
  ownPackages = set()
  failedRequirements = set()
  testCache = {}
  requirementsCache = {}
  while packages:
    p = packages.pop(0)
    if p in specs:
      continue
    try:
      d = open("%s/%s.sh" % (configDir, p.lower())).read()
    except IOError,e:
      dieOnError(True, str(e))
    header, recipe = d.split("---", 1)
    spec = yaml.safe_load(header)
    dieOnError(spec["package"].lower() != p.lower(),
               "%s.sh has different package field: %s" % (p, spec["package"]))
    # If --always-prefer-system is passed or if prefer_system is set to true
    # inside the recipe, use the script specified in the prefer_system_check
    # stanza to see if we can use the system version of the package.
    if not noSystem and (preferSystem or re.match(spec.get("prefer_system", "(?!.*)"), architecture)):
      cmd = spec.get("prefer_system_check", "false")
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
    dieOnError(not isinstance(spec["version"], basestring),
               "In recipe \"%s\": version must be a string" % p)
    spec["tag"] = spec.get("tag", spec["version"])
    spec["version"] = spec["version"].replace("/", "_")
    spec["recipe"] = recipe.strip("\n")
    specs[spec["package"]] = spec
    packages += spec["requires"]
  return (systemPackages, ownPackages, failedRequirements)
