import argparse
from alibuild_helpers.utilities import format, detectArch
from alibuild_helpers.doctor import doctorArgParser
from alibuild_helpers.utilities import normalise_multiple_options
import multiprocessing

import re
import os

try:
  import commands
except ImportError:
  import subprocess as commands
from os.path import abspath, dirname, basename
import sys

# Default workdir: fall back on "sw" if env is not set
DEFAULT_WORK_DIR = os.environ.get("ALIBUILD_WORK_DIR", os.environ.get("ALICE_WORK_DIR", "sw"))

# cd to this directory before start
DEFAULT_CHDIR = os.environ.get("ALIBUILD_CHDIR", ".")

def csv_list(s):
  return s.split(',')


# This is syntactic sugar for the --dist option (which should really be called
# --dist-tag). It can be either:
# - A tag name
# - A repository spec in the for org/repo@tag
def alidist_string(s, star):
  expanded = s if "@" in s else "alisw/%sdist@%s" % (star, s)
  return dict(zip(["repo","ver"], expanded.split("@", 1)))

def doParseArgs(star):
  detectedArch = detectArch()
  parser = argparse.ArgumentParser(epilog="For help about each option, specify --help after the option itself.\nFor complete documentation please refer to https://alisw.github.io/alibuild")

  parser.add_argument("-d", "--debug", dest="debug", action="store_true", default=False, help="Enable debug log output")
  parser.add_argument("-n", "--dry-run", dest="dryRun", default=False,
                      action="store_true", help="Prints what would happen, without actually doing it.")

  subparsers = parser.add_subparsers(dest='action')
  analytics_parser = subparsers.add_parser("analytics", help="turn on / off analytics")
  architecture_parser = subparsers.add_parser("architecture", help="display detected architecture")
  build_parser = subparsers.add_parser("build", help="build a package")
  clean_parser = subparsers.add_parser("clean", help="cleanup build area")
  deps_parser = subparsers.add_parser("deps", help="generate a dependency graph for a given package")
  doctor_parser = subparsers.add_parser("doctor", help="verify status of your system")
  init_parser = subparsers.add_parser("init", help="initialise local packages")
  version_parser = subparsers.add_parser("version", help="display %(prog)s version")

  # Options for the analytics command
  analytics_parser.add_argument("state", choices=["on", "off"], help="Whether to report analytics or not")

  # Options for the build command
  build_parser.add_argument("pkgname", nargs="+", help="One (or more) of the packages in `alidist'")

  build_parser.add_argument("--config-dir", "-c", dest="configDir", default="%%(prefix)s%sdist" % star)
  build_parser.add_argument("--no-local", dest="noDevel", default="", type=csv_list,
                      help="Do not pick up the following packages from a local checkout.")
  build_parser.add_argument("--docker", dest="docker", action="store_true", default=False)
  build_parser.add_argument("--docker-image", dest="dockerImage", default=argparse.SUPPRESS,
                            help="Image to use in case you build with docker (implies --docker)")
  build_parser.add_argument("--work-dir", "-w", dest="workDir", default=DEFAULT_WORK_DIR)
  build_parser.add_argument("--architecture", "-a", dest="architecture",
                      default=detectedArch)
  build_parser.add_argument("-e", dest="environment", action='append', default=[])
  build_parser.add_argument("-v", dest="volumes", action='append', default=[],
                      help="Specify volumes to be used in Docker")
  build_parser.add_argument("--jobs", "-j", dest="jobs", type=int, default=multiprocessing.cpu_count())
  build_parser.add_argument("--reference-sources", dest="referenceSources", default="%(workDir)s/MIRROR")
  build_parser.add_argument("--remote-store", dest="remoteStore", default="",
                            help="Where to find packages already built for reuse."
                                 "Use ssh:// in front for remote store. End with ::rw if you want to upload.")
  build_parser.add_argument("--write-store", dest="writeStore", default="",
                            help="Where to upload the built packages for reuse."
                                 "Use ssh:// in front for remote store.")
  build_parser.add_argument("--disable", dest="disable", default=[],
                            metavar="PACKAGE", action="append",
                            help="Do not build PACKAGE and all its (unique) dependencies.")
  build_parser.add_argument("--defaults", dest="defaults", default="release",
                            metavar="FILE", help="Specify which defaults to use")
  build_parser.add_argument("--force-unknown-architecture", dest="forceUnknownArch", default=False,
                            action="store_true", help="Do not check for valid architecture")
  build_parser.add_argument("--insecure", dest="insecure", default=False,
                            action="store_true", help="Do not check for valid certificates")
  build_parser.add_argument("--aggressive-cleanup", dest="aggressiveCleanup", default=False,
                            action="store_true", help="Perform additional cleanups")
  build_parser.add_argument("--chdir", "-C", help="Change to the specified directory first",
                            metavar="DIR", dest="chdir", default=DEFAULT_CHDIR)
  build_parser.add_argument("--no-auto-cleanup", help="Do not cleanup build by products automatically",
                      dest="autoCleanup", action="store_false", default=True)
  build_parser.add_argument("--devel-prefix", "-z", nargs="?", help="Version name to use for development packages. Defaults to branch name.",
                      dest="develPrefix", default=argparse.SUPPRESS)
  build_parser.add_argument("--fetch-repos", "-u", dest="fetchRepos", default=False,
                            action="store_true", help="Fetch repository updates")

  group = build_parser.add_mutually_exclusive_group()
  group.add_argument("--always-prefer-system", dest="preferSystem", default=False,
                     action="store_true", help="Always use system packages when compatible")
  group.add_argument("--no-system", dest="noSystem", default=False,
                     action="store_true", help="Never use system packages")

  # Options for clean subcommand
  clean_parser.add_argument("--architecture", "-a", dest="architecture",
                            default=detectedArch)
  clean_parser.add_argument("--force-unknown-architecture", dest="forceUnknownArch", default=False,
                            action="store_true", help="Do not check for valid architecture")
  clean_parser.add_argument("--work-dir", "-w", dest="workDir", default=DEFAULT_WORK_DIR)
  clean_parser.add_argument("--aggressive-cleanup", dest="aggressiveCleanup", default=False,
                            action="store_true", help="Perform additional cleanups")
  clean_parser.add_argument("--disable", dest="disable", default=[],
                            metavar="PACKAGE", action="append",
                            help="Do not build PACKAGE and all its (unique) dependencies.")
  clean_parser.add_argument("--reference-sources", dest="referenceSources", default="%(workDir)s/MIRROR")
  clean_parser.add_argument("--chdir", "-C", help="Change to the specified directory first",
                            metavar="DIR", dest="chdir", default=DEFAULT_CHDIR)

  # Options for the deps subcommand
  deps_parser.add_argument("package",
                           help="Calculate dependency tree for that package")
  deps_parser.add_argument("--neat", dest="neat", action="store_true", default=False,
                           help="Neat graph with transitive reduction")
  deps_parser.add_argument("--outdot", dest="outdot",
                           help="Keep intermediate Graphviz dot file with this name")
  deps_parser.add_argument("--outgraph", dest="outgraph",
                           help="Output file (PDF)")
  deps_parser.add_argument("-c", "--config", dest="configDir", default="alidist",
                           help="Path to alidist")
  deps_parser.add_argument("--defaults", dest="defaults", default="release",
                           help="Specify which defaults to use")
  deps_parser.add_argument("--disable", dest="disable", default=[], metavar="PKG", action="append",
                           help="Do not build PACKAGE and all its (unique) dependencies")
  deps_parser.add_argument("--docker", dest="docker", action="store_true", default=False)
  deps_parser.add_argument("--docker-image", dest="dockerImage",
                           help="Image to use in case you build with docker (implies --docker-image)")
  deps_parser.add_argument("--architecture", "-a", dest="architecture", default=detectedArch,
                           help="Architecture")
  deps_group = deps_parser.add_mutually_exclusive_group()
  deps_group.add_argument("--always-prefer-system", dest="preferSystem", default=False,
                     action="store_true", help="Always use system packages when compatible")
  deps_group.add_argument("--no-system", dest="noSystem", default=False,
                     action="store_true", help="Never use system packages")

  # Options for the doctor subcommand
  doctor_parser = doctorArgParser(doctor_parser)

  # Options for the init subcommand
  init_parser.add_argument("pkgname", nargs="?", default="", help="One (or more) of the packages in `alidist'")
  init_parser.add_argument("--architecture", "-a", dest="architecture",
                            default=detectedArch)
  init_parser.add_argument("--work-dir", "-w", dest="workDir", default=DEFAULT_WORK_DIR)
  init_parser.add_argument("--devel-prefix", "-z", nargs="?", default=".", help="Version name to use for development packages. Defaults to branch name.",
                           dest="develPrefix")
  init_parser.add_argument("--config-dir", "-c", dest="configDir", default="%%(prefix)s%sdist" % star)
  init_parser.add_argument("--reference-sources", dest="referenceSources", default="%(workDir)s/MIRROR")
  init_parser.add_argument("--dist", dest="dist", default="", type=lambda x : alidist_string(x, star),
                           help="Prepare development mode by downloading the given recipes set ([user/repo@]branch)")
  init_parser.add_argument("--defaults", dest="defaults", default="release",
                            metavar="FILE", help="Specify which defaults to use")
  init_parser.add_argument("--chdir", "-C", help="Change to the specified directory first",
                           metavar="DIR", dest="chdir", default=DEFAULT_CHDIR)

  # Options for the version subcommand
  version_parser.add_argument("--architecture", "-a", dest="architecture",
                      default=detectedArch)

  # Make sure old option ordering behavior is actually still working
  prog = sys.argv[0]
  rest = sys.argv[1:]
  def optionOrder(x):
    if x in ["--debug", "-d", "-n", "--dry-run"]:
      return 0
    if x in ["build", "init", "clean", "analytics", "doctor", "deps"]:
      return 1
    return 2
  rest.sort(key=optionOrder)
  sys.argv = [prog] + rest
  args = finaliseArgs(parser.parse_args(), parser, star)
  return (args, parser)

VALID_ARCHS_RE = ["slc[5-9]+_(x86-64|ppc64)",
                  "(ubuntu|ubt|osx|fedora)[0-9]*_x86-64",
                 ]

def matchValidArch(architecture):
  return [x for x in VALID_ARCHS_RE if re.match(x, architecture)]

ARCHITECTURE_TABLE = [
           "On Linux, x86-64:\n"
           "   RHEL5 / SLC5 compatible: slc5_x86-64\n"
           "   RHEL6 / SLC6 compatible: slc6_x86-64\n"
           "   RHEL7 / CC7 compatible: slc7_x86-64\n"
           "   Ubuntu 14.04 compatible: ubuntu1404_x86-64\n"
           "   Ubuntu 15.04 compatible: ubuntu1504_x86-64\n"
           "   Ubuntu 15.10 compatible: ubuntu1510_x86-64\n"
           "   Ubuntu 16.04 compatible: ubuntu1604_x86-64\n"
           "   Fedora 25 compatible: fedora25_x86-64\n"
           "   Fedora 26 compatible: fedora26_x86-64\n\n"
           "On Linux, POWER8 / PPC64 (little endian):\n"
           "   RHEL7 / CC7 compatible: slc7_ppc64\n\n"
           "On Mac, x86-64:\n"
           "   Yosemite and El-Captain: osx_x86-64\n\n"
      ]

def finaliseArgs(args, parser, star):

  # Nothing to finalise for version or analytics
  if args.action in ["version", "analytics", "architecture"]:
    return args

  # --architecture can be specified in both clean and build.
  if args.action in  ["build", "clean"]:
    if not args.architecture:
      parser.error(format("Cannot determine architecture. "
                   "Please pass it explicitly.\n\n%s" % ARCHITECTURE_TABLE[0]))
    if not args.forceUnknownArch and not matchValidArch(args.architecture):
      parser.error(format("Unknown / unsupported architecture: %(architecture)s.\n\n"
                  "%(table)s"
                  "Alternatively, you can use the `--force-unknown-architecture' option.",
                  table=ARCHITECTURE_TABLE[0],
                  architecture=args.architecture))

    args.disable = normalise_multiple_options(args.disable)

  if args.action in ["build", "clean", "init"]:
    args.referenceSources = format(args.referenceSources, workDir=args.workDir)

  if args.action == "build":
    args.configDir = format(args.configDir, prefix="")

    # On selected platforms, caching is active by default
    if args.architecture == "slc7_x86-64" and not args.preferSystem:
      args.noSystem = True
      if not args.remoteStore:
        args.remoteStore = "https://s3.cern.ch/swift/v1/alibuild-repo"

    if args.remoteStore or args.writeStore:
      args.noSystem = True

    if "dockerImage" in args:
      args.docker = True

    if args.docker and args.architecture.startswith("osx"):
      parser.error("cannot use `-a %s` and --docker" % args.architecture)

    if args.docker and commands.getstatusoutput("which docker")[0]:
      parser.error("cannot use --docker as docker executable is not found")

    # If specified, used the docker image requested, otherwise, if running
    # in docker the docker image is given by the first part of the
    # architecture we want to build for.
    if args.docker and not "dockerImage" in args:
      args.dockerImage = "alisw/%s-builder" % args.architecture.split("_")[0]

    if args.remoteStore.endswith("::rw") and args.writeStore:
      parser.error("cannot specify ::rw and --write-store at the same time")

    if args.remoteStore.endswith("::rw"):
      args.remoteStore = args.remoteStore[0:-4]
      args.writeStore = args.remoteStore

  if args.action in ["build", "init"]:
    if "develPrefix" in args and args.develPrefix == None:
      if "chdir" in args:
        args.develPrefix = basename(abspath(args.chdir))
      else:
        args.develPrefix = basename(dirname(abspath(args.configDir)))
    if "dockerImage" in args:
      args.develPrefix = "%s-%s" % (args.develPrefix, args.architecture) if "develPrefix" in args else args.architecture

  if args.action == "init":
    args.configDir = format(args.configDir, prefix=args.develPrefix+"/")
  elif args.action == "build":
    pass
  elif args.action == "clean":
    pass
  else:
    pass
  return args
