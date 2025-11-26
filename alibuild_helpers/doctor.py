#!/usr/bin/env python3
import os
import re
import sys
from os.path import exists, abspath, expanduser
import logging
from alibuild_helpers.log import debug, error, banner, info, success, warning
from alibuild_helpers.log import logger
from alibuild_helpers.utilities import getPackageList, parseDefaults, readDefaults, validateDefaults
from alibuild_helpers.cmd import getstatusoutput, DockerRunner
import tempfile

def prunePaths(workDir) -> None:
  for x in ["PATH", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"]:
    if x not in os.environ:
      continue
    workDirEscaped = re.escape("%s" % workDir) + "[^:]*:?"
    os.environ[x] = re.sub(workDirEscaped, "", os.environ[x])

def checkPreferSystem(spec, cmd, homebrew_replacement, getstatusoutput_docker):
    if cmd == "false":
      debug("Package %s can only be managed via alibuild.", spec["package"])
      return (1, "")
    cmd = homebrew_replacement + cmd
    with tempfile.TemporaryDirectory(prefix=f"alibuild_prefer_check_{spec['package']}_") as temp_dir:
        err, out = getstatusoutput_docker(cmd, cwd=temp_dir)
    if not err:
      success("Package %s will be picked up from the system.", spec["package"])
      for x in out.split("\n"):
        debug("%s: %s", spec["package"], x)
      return (err, "")

    warning("Package %s cannot be picked up from the system and will be built by aliBuild.\n"
            "This is due to the fact the following script fails:\n\n%s\n\n"
            "with the following output:\n\n%s\n",
            spec["package"], cmd, "\n".join("%s: %s" % (spec["package"], x) for x in out.split("\n")))
    return (err, "")

def checkRequirements(spec, cmd, homebrew_replacement, getstatusoutput_docker):
    if cmd == "false":
      debug("Package %s is not a system requirement.", spec["package"])
      return (0, "")
    cmd = homebrew_replacement + cmd
    with tempfile.TemporaryDirectory(prefix=f"alibuild_prefer_check_{spec['package']}_") as temp_dir:
        err, out = getstatusoutput_docker(cmd, cwd=temp_dir)
    if not err:
      success("Required package %s will be picked up from the system.", spec["package"])
      debug("%s", cmd)
      for x in out.split("\n"):
        debug("%s: %s", spec["package"], x)
      return (0, "")
    error("Package %s is a system requirement and cannot be found.\n"
          "This is due to the fact that the following script fails:\n\n%s\n"
          "with the following output:\n\n%s\n%s\n",
          spec["package"], cmd,
          "\n".join("%s: %s" % (spec["package"], x) for x in out.split("\n")),
          spec.get("system_requirement_missing"))
    return (err, "")

def systemInfo() -> None:
  _,out = getstatusoutput("env")
  debug("Environment:\n%s", out)
  _,out = getstatusoutput("uname -a")
  debug("uname -a: %s", out)
  _,out = getstatusoutput("mount")
  debug("Mounts:\n%s", out)
  _,out = getstatusoutput("df")
  debug("Disk free:\n%s", out)
  for f in ["/etc/lsb-release", "/etc/redhat-release", "/etc/os-release"]:
    err,out = getstatusoutput("cat "+f)
    if not err:
      debug("%s:\n%s", f, out)

def doDoctor(args, parser):
  if not exists(args.configDir):
    parser.error("Wrong path to alidist specified: %s" % args.configDir)

  prunePaths(abspath(args.workDir))

  if exists(expanduser("~/.rootlogon.C")):
    warning("You have a ~/.rootlogon.C notice that this might"
            " interfere with your environment in hidden ways.\n"
            "Please review it an make sure you are not force loading any library"
            " which might interphere with the rest of the setup.")
  # Decide if we can use homebrew. If not, we replace it with "true" so
  # that we do not get spurious messages on linux
  homebrew_replacement = ""

  extra_env = {"ALIBUILD_CONFIG_DIR": "/alidist" if args.docker else os.path.abspath(args.configDir)}
  extra_env.update(dict([e.partition('=')[::2] for e in args.environment]))

  with DockerRunner(args.dockerImage, args.docker_extra_args, extra_env=extra_env, extra_volumes=[f"{os.path.abspath(args.configDir)}:/alidist:ro"] if args.docker else []) as getstatusoutput_docker:
    err, output = getstatusoutput_docker("type c++")
  if err:
    warning("Unable to find system compiler.\n"
            "%s\n"
            "Please follow prerequisites:\n"
            "* On RHEL9 compatible systems (e.g. Alma9): https://alice-doc.github.io/alice-analysis-tutorial/building/prereq-alma9.html\n"
            "* On Fedora compatible systems: https://alice-doc.github.io/alice-analysis-tutorial/building/prereq-fedora.html\n"
            "* On Ubuntu compatible systems: https://alice-doc.github.io/alice-analysis-tutorial/building/prereq-ubuntu.html\n"
            "* On macOS: https://alice-doc.github.io/alice-analysis-tutorial/building/prereq-macos.html\n",
            output)
  err, output = getstatusoutput("type git")
  if err:
    error("Unable to find git.\n"
          "%s\n"
          "Please follow prerequisites:\n"
          "* On RHEL9 compatible systems (e.g. Alma9): https://alice-doc.github.io/alice-analysis-tutorial/building/prereq-alma9.html\n"
          "* On Fedora compatible systems: https://alice-doc.github.io/alice-analysis-tutorial/building/prereq-fedora.html\n"
          "* On Ubuntu compatible systems: https://alice-doc.github.io/alice-analysis-tutorial/building/prereq-ubuntu.html\n"
          "* On macOS: https://alice-doc.github.io/alice-analysis-tutorial/building/prereq-macos.html\n",
          output)
  # Decide if we can use homebrew. If not, we replace it with "true" so
  # that we do not get spurious messages on linux
  homebrew_replacement = ""
  err, output = getstatusoutput("which brew")
  if err:
    homebrew_replacement = "brew() { true; }; "

  logger.setLevel(logging.BANNER)
  if args.debug:
    logger.setLevel(logging.DEBUG)

  specs = {}
  packages = []
  exitcode = 0
  for p in args.packages:
    path = "%s/%s.sh" % (args.configDir, p.lower())
    if not exists(path):
      error("Cannot find recipe %s for package %s.", path, p)
      exitcode = 1
      continue
    packages.append(p)
  systemInfo()

  specs = {}
  defaultsReader = lambda : readDefaults(args.configDir, args.defaults, parser.error, args.architecture)
  (err, overrides, taps) = parseDefaults(args.disable, defaultsReader, info)
  if err:
    error("%s", err)
    sys.exit(1)

  def performValidateDefaults(spec):
    (ok,msg,valid) = validateDefaults(spec, args.defaults)
    if not ok:
      error("%s", msg)
    return (ok,msg,valid)

  extra_env = {"ALIBUILD_CONFIG_DIR": "/alidist" if args.docker else os.path.abspath(args.configDir)}
  extra_env.update(dict([e.partition('=')[::2] for e in args.environment]))
  
  with DockerRunner(args.dockerImage, args.docker_extra_args, extra_env=extra_env, extra_volumes=[f"{os.path.abspath(args.configDir)}:/alidist:ro"] if args.docker else []) as getstatusoutput_docker:
    fromSystem, own, failed, validDefaults = \
      getPackageList(packages                = packages,
                     specs                   = specs,
                     configDir               = args.configDir,
                     preferSystem            = args.preferSystem,
                     noSystem                = args.noSystem,
                     architecture            = args.architecture,
                     disable                 = args.disable,
                     defaults                = args.defaults,
                     performPreferCheck      = lambda pkg, cmd: checkPreferSystem(pkg, cmd, homebrew_replacement, getstatusoutput_docker),
                     performRequirementCheck = lambda pkg, cmd: checkRequirements(pkg, cmd, homebrew_replacement, getstatusoutput_docker),
                     performValidateDefaults = performValidateDefaults,
                     overrides               = overrides,
                     taps                    = taps,
                     log                     = info)

  alwaysBuilt = set(x for x in specs) - fromSystem - own - failed
  if alwaysBuilt:
    banner("The following packages will be built by aliBuild because\n"
           " usage of a system version of it is not allowed or supported, by policy:\n\n- %s",
           " \n- ".join(alwaysBuilt))
  if fromSystem:
    banner("The following packages will be picked up from the system:\n\n- %s\n\n"
           "If this is not you want, you have to uninstall / unload them.",
           "\n- ".join(fromSystem))
  if own:
    banner("The following packages will be built by aliBuild because they couldn't be picked up from the system:\n\n"
           "- %s\n\n"
           "This is not a real issue, but it might take longer the first time you invoke aliBuild.\n"
           "Look at the error messages above to get hints on what packages you need to install separately.",
           "\n- ".join(own))
  if failed:
    banner("The following packages are system dependencies and could not be found:\n\n- %s\n\n"
           "Look at the error messages above to get hints on what packages you need to install separately.",
           "\n- ".join(failed))
    exitcode = 1
  if validDefaults and args.defaults not in validDefaults:
    banner("The list of packages cannot be built with the defaults you have specified.\n"
           "List of valid defaults:\n\n- %s\n\n"
           "Use the `--defaults' switch to specify one of them.",
           "\n- ".join(validDefaults))
    exitcode = 2
  if validDefaults is None:
    banner("No valid defaults combination was found for the given list of packages, check your recipes!")
    exitcode = 3
  if exitcode:
    error("There were errors: build cannot be performed if they are not resolved. Check the messages above.")
  sys.exit(exitcode)

