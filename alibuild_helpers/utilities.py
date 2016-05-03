#!/usr/bin/env python
import subprocess

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
