import argparse
from alibuild_helpers.utilities import format, detectArch
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

# Default workdir: fall back on "sw" if env is not set or empty
DEFAULT_WORK_DIR = os.environ.get("ALIBUILD_WORK_DIR") or os.environ.get("ALICE_WORK_DIR") or "sw"

# cd to this directory before start
DEFAULT_CHDIR = os.environ.get("ALIBUILD_CHDIR") or "."


# This is syntactic sugar for the --dist option (which should really be called
# --dist-tag). It can be either:
# - A tag name
# - A repository spec in the for org/repo@tag
def alidist_string(s, star):
  repo, have_repo_spec, ver = s.partition("@")
  if not have_repo_spec:
    repo, ver = "alisw/%sdist" % star, s
  return {"repo": repo, "ver": ver}


def doParseArgs(star):
  detectedArch = detectArch()
  parser = argparse.ArgumentParser(epilog="""\
  For help about each option, specify --help after the option itself. For
  complete documentation please refer to https://alisw.github.io/alibuild.
  """)

  parser.add_argument("-d", "--debug", dest="debug", action="store_true", help="Enable debug log output")
  parser.add_argument("-n", "--dry-run", dest="dryRun", action="store_true",
                      help="Print what would happen, without actually doing it.")

  subparsers = parser.add_subparsers(dest="action")
  analytics_parser = subparsers.add_parser("analytics", help="turn on / off analytics",
                                           description="Control analytics state.")
  subparsers.add_parser("architecture", help="display detected architecture",
                        description="Display the detected architecture.")
  build_parser = subparsers.add_parser("build", help="build a package",
                                       description="Build a package.")
  clean_parser = subparsers.add_parser("clean", help="clean up build area",
                                       description="Clean up the build area.")
  deps_parser = subparsers.add_parser("deps", help="generate a dependency graph for a given package",
                                      description="Generate a dependency graph for a given package.")
  doctor_parser = subparsers.add_parser("doctor", help="verify status of your system",
                                        description="Verify the status of your system.")
  init_parser = subparsers.add_parser("init", help="initialise local packages",
                                      description="Initialise development packages.")
  version_parser = subparsers.add_parser("version", help="display %(prog)s version",
                                         description="Display %(prog)s and architecture.")

  # Options for the analytics command
  analytics_parser.add_argument("state", choices=["on", "off"], help="Whether to report analytics or not")

  # Options for the build command
  build_parser.add_argument("pkgname", metavar="PACKAGE", nargs="+",
                            help="One of the packages in CONFIGDIR. May be specified multiple times.")

  build_parser.add_argument("--defaults", dest="defaults", default="o2", metavar="DEFAULT",
                            help="Use defaults from CONFIGDIR/defaults-%(metavar)s.sh.")
  build_parser.add_argument("-a", "--architecture", dest="architecture", metavar="ARCH", default=detectedArch,
                            help=("Build as if on the specified architecture. When used with --docker, build "
                                  "inside a Docker image for the specified architecture. Default is the current "
                                  "system architecture, which is '%(default)s'."))
  build_parser.add_argument("--force-unknown-architecture", dest="forceUnknownArch", action="store_true",
                            help="Build on this system, even if it doesn't have a supported architecture.")
  build_parser.add_argument("-z", "--devel-prefix", nargs="?", dest="develPrefix", default=argparse.SUPPRESS,
                            help="Version name to use for development packages. Defaults to branch name.")
  build_parser.add_argument("-e", dest="environment", action="append", default=[],
                            help="KEY=VALUE binding to add to the build environment. May be specified multiple times.")
  build_parser.add_argument("-j", "--jobs", dest="jobs", type=int, default=multiprocessing.cpu_count(),
                            help=("The number of parallel compilation processes to run. "
                                  "Default for this system: %(default)d."))
  build_parser.add_argument("-u", "--fetch-repos", dest="fetchRepos", action="store_true",
                            help=("Fetch updates to repositories in MIRRORDIR. Required but nonexistent "
                                  "repositories are always cloned, even if this option is not given."))

  build_parser.add_argument("--no-local", dest="noDevel", metavar="PACKAGE", default=[], action="append",
                            help=("Do not pick up the following packages from a local checkout. "
                                  "You can specify this option multiple times or separate "
                                  "multiple arguments with commas."))
  build_parser.add_argument("--force-tracked", dest="forceTracked", default=False, action="store_true",
                            help=("Do not pick up any packages from a local checkout. "))
  build_parser.add_argument("--plugin", dest="plugin", default="legacy", help=("Plugin to use to do the actual build. "))
  build_parser.add_argument("--disable", dest="disable", default=[], metavar="PACKAGE", action="append",
                            help=("Do not build %(metavar)s and all its (unique) dependencies. "
                                  "You can specify this option multiple times or separate "
                                  "multiple arguments with commas."))
  build_parser.add_argument("--force-rebuild", default=[], metavar="PACKAGE", action="append",
                            help=("Always rebuild the following packages from scratch, even if "
                                  "they were built before. Specifying a package here has the "
                                  "same effect as adding 'force_rebuild: true' to its recipe "
                                  "in CONFIGDIR. You can specify this option multiple times or "
                                  "separate multiple arguments with commas."))

  build_docker = build_parser.add_argument_group(title="Build inside a container", description="""\
  Builds can be done inside a Docker container, to make it easier to get a
  common, usable environment. The Docker daemon must be installed and running
  on your system. By default, images from alisw/<platform>-builder:latest will
  be used, e.g. alisw/slc8-builder:latest. They will be fetched if unavailable.
  """)
  build_docker.add_argument("--docker", dest="docker", action="store_true",
                            help="Build inside a Docker container.")
  build_docker.add_argument("--docker-image", dest="dockerImage", metavar="IMAGE", default=argparse.SUPPRESS,
                            help=("The Docker image to build inside of. Implies --docker. "
                                  "By default, an image is chosen based on the architecture."))
  build_docker.add_argument("--docker-extra-args", metavar="ARGLIST", default="",
                            help=("Command-line arguments to pass to 'docker run'. "
                                  "Passed through verbatim -- separate multiple arguments "
                                  "with spaces, and make sure quoting is correct! Implies --docker."))
  build_docker.add_argument("-v", dest="volumes", action="append", default=[],
                            help=("Additional volume to be mounted inside the Docker container, if one is used. "
                                  "May be specified multiple times. Passed verbatim to 'docker run'."))

  build_remote = build_parser.add_argument_group(title="Re-use prebuilt tarballs", description="""\
  Reusing prebuilt tarballs saves compilation time, as common packages need not
  be rebuilt from scratch. rsync://, https://, b3:// and s3:// remote stores
  are recognised. Some of these require credentials: s3:// remotes require an
  ~/.s3cfg; b3:// remotes require AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY
  environment variables. A useful remote store is
  'https://s3.cern.ch/swift/v1/alibuild-repo'. It requires no credentials and
  provides tarballs for the most common supported architectures.
  """)
  build_remote.add_argument("--no-remote-store", action="store_true",
                            help="Disable the use of the remote store, even if it is enabled by default.")
  build_remote.add_argument("--remote-store", dest="remoteStore", metavar="STORE", default="",
                            help="""\
                            Where to find prebuilt tarballs to reuse. See above for available remote stores.
                            End with ::rw if you want to upload (in that case, ::rw is stripped and --write-store
                            is set to the same value). Implies --no-system. May be set to a default store on some
                            architectures; use --no-remote-store to disable it in that case.
                            """)
  build_remote.add_argument("--write-store", dest="writeStore", metavar="STORE", default="",
                            help=("Where to upload newly built packages. Same syntax as --remote-store, "
                                  "except ::rw is not recognised. Implies --no-system."))
  build_remote.add_argument("--insecure", dest="insecure", action="store_true",
                            help="Don't validate TLS certificates when connecting to an https:// remote store.")

  build_dirs = build_parser.add_argument_group(title="Customise %sBuild directories" % star)
  build_dirs.add_argument("-C", "--chdir", metavar="DIR", dest="chdir", default=DEFAULT_CHDIR,
                          help=("Change to the specified directory before building. "
                                "Alternatively, set ALIBUILD_CHDIR. Default '%(default)s'."))
  build_dirs.add_argument("-w", "--work-dir", dest="workDir", default=DEFAULT_WORK_DIR,
                          help=("The toplevel directory under which builds should be done and build results "
                                "should be installed. Default '%(default)s'."))
  build_dirs.add_argument("-c", "--config-dir", dest="configDir", default="%sdist" % star,
                          help="The directory containing build recipes. Default '%(default)s'.")
  build_dirs.add_argument("--reference-sources", dest="referenceSources", metavar="MIRRORDIR",
                          default="%(workDir)s/MIRROR",
                          help=("The directory where reference git repositories will be cloned. "
                                "'%%(workDir)s' will be substituted by WORKDIR. Default '%(default)s'."))

  build_cleanup = build_parser.add_argument_group(title="Cleaning up after building")
  build_cleanup.add_argument("--aggressive-cleanup", dest="aggressiveCleanup", action="store_true",
                             help="Delete as much build data as possible when cleaning up.")
  build_cleanup.add_argument("--no-auto-cleanup", dest="autoCleanup", action="store_false",
                             help="Do not clean up build directories automatically after a build.")

  build_system = build_parser.add_mutually_exclusive_group()
  build_system.add_argument("--always-prefer-system", dest="preferSystem", action="store_true",
                            help="Always use system packages when compatible.")
  build_system.add_argument("--no-system", dest="noSystem", action="store_true",
                            help="Never use system packages, even if compatible.")

  # Options for clean subcommand
  clean_parser.add_argument("-a", "--architecture", dest="architecture", metavar="ARCH", default=detectedArch,
                            help=("Clean up build results for this architecture. Default is the current system "
                                  "architecture, which is '%(default)s'."))
  clean_parser.add_argument("--aggressive-cleanup", dest="aggressiveCleanup", action="store_true",
                            help="Delete as much build data as possible when cleaning up.")
  clean_dirs = clean_parser.add_argument_group(title="Customise %sBuild directories" % star)
  clean_dirs.add_argument("-C", "--chdir", metavar="DIR", dest="chdir", default=DEFAULT_CHDIR,
                          help=("Change to the specified directory before cleaning up. "
                                "Alternatively, set ALIBUILD_CHDIR. Default '%(default)s'."))
  clean_dirs.add_argument("-w", "--work-dir", dest="workDir", default=DEFAULT_WORK_DIR,
                          help="The toplevel directory used in previous builds. Default '%(default)s'.")

  # Options for the deps subcommand
  deps_parser.add_argument("package", metavar="PACKAGE",
                           help="Calculate dependency tree for %(metavar)s.")

  deps_parser.add_argument("-a", "--architecture", dest="architecture", metavar="ARCH", default=detectedArch,
                           help=("Resolve dependencies as if on the specified architecture. When used with "
                                 "--docker, use a Docker image for the specified architecture. Default is "
                                 "the current system architecture, which is '%(default)s'."))
  deps_parser.add_argument("--defaults", dest="defaults", default="o2", metavar="DEFAULT",
                           help="Use defaults from CONFIGDIR/defaults-%(metavar)s.sh.")
  deps_parser.add_argument("--disable", dest="disable", default=[], metavar="PACKAGE", action="append",
                           help=("Assume we're not building %(metavar)s and all its (unique) dependencies. "
                                 "You can specify this option multiple times or separate multiple arguments "
                                 "with commas."))

  deps_graph = deps_parser.add_argument_group(title="Customise graph output")
  deps_graph.add_argument("--neat", dest="neat", action="store_true",
                          help="Produce a graph with transitive reduction.")
  deps_graph.add_argument("--outdot", dest="outdot", metavar="FILE",
                          help="Keep intermediate Graphviz dot file in %(metavar)s.")
  deps_graph.add_argument("--outgraph", dest="outgraph", metavar="FILE",
                          help="Store final output PDF file in %(metavar)s.")

  deps_docker = deps_parser.add_argument_group(title="Use a Docker container", description="""\
  If you're planning to build inside a Docker container, e.g. using aliBuild
  build's --docker option, it may be useful to resolve dependencies inside that
  container as well, as which system packages are picked up may differ.
  """)
  deps_docker.add_argument("--docker", dest="docker", action="store_true",
                           help="Check for available system packages inside a Docker container.")
  deps_docker.add_argument("--docker-image", dest="dockerImage", metavar="IMAGE",
                           help=("The Docker image to use. Implies --docker. By default, an image "
                                 "is chosen based on the current or selected architecture."))
  deps_docker.add_argument("--docker-extra-args", default="", metavar="ARGLIST",
                           help=("Command-line arguments to pass to 'docker run'. "
                                 "Passed through verbatim -- separate multiple arguments "
                                 "with spaces, and make sure quoting is correct! Implies --docker."))

  deps_parser.add_argument_group(title="Customise %sBuild directories" % star) \
             .add_argument("-c", "--config-dir", dest="configDir", default="%sdist" % star,
                           help="The directory containing build recipes. Default '%(default)s'.")

  deps_system = deps_parser.add_mutually_exclusive_group()
  deps_system.add_argument("--always-prefer-system", dest="preferSystem", action="store_true",
                           help="Always use system packages when compatible.")
  deps_system.add_argument("--no-system", dest="noSystem", action="store_true",
                           help="Never use system packages, even if compatible.")

  # Options for the doctor subcommand
  doctor_parser.add_argument("packages", metavar="PACKAGE", nargs="+",
                             help=("Check whether all system requirements of %(metavar)s are satisfied. "
                                   "May be specified multiple times."))
  doctor_parser.add_argument("-a", "--architecture", dest="architecture", metavar="ARCH", default=detectedArch,
                             help=("Resolve requirements as if on the specified architecture. When used with "
                                   "--docker, use a Docker image for the specified architecture. Default is "
                                   "the current system architecture, which is '%(default)s'."))
  doctor_parser.add_argument("--defaults", dest="defaults", default="o2", metavar="DEFAULT",
                             help="Use defaults from CONFIGDIR/defaults-%(metavar)s.sh.")
  doctor_parser.add_argument("--disable", dest="disable", default=[], metavar="PACKAGE", action="append",
                             help=("Assume we're not building %(metavar)s and all its (unique) dependencies. "
                                   "You can specify this option multiple times or separate multiple arguments "
                                   "with commas."))

  doctor_system = doctor_parser.add_mutually_exclusive_group()
  doctor_system.add_argument("--always-prefer-system", dest="preferSystem", action="store_true",
                             help="Always use system packages when compatible.")
  doctor_system.add_argument("--no-system", dest="noSystem", action="store_true",
                             help="Never use system packages, even if compatible.")

  doctor_docker = doctor_parser.add_argument_group(title="Use a Docker container", description="""\
  If you're planning to build inside a Docker container, e.g. using aliBuild
  build's --docker option, it may be useful to resolve dependencies inside that
  container as well, as which system packages are picked up may differ.
  """)
  doctor_docker.add_argument("--docker", dest="docker", action="store_true",
                             help="Check for available system packages inside a Docker container.")
  doctor_docker.add_argument("--docker-image", dest="dockerImage", metavar="IMAGE",
                             help=("The Docker image to use. Implies --docker. By default, an image "
                                   "is chosen based on the current or selected architecture."))

  doctor_dirs = doctor_parser.add_argument_group(title="Customise %sBuild directories" % star)
  doctor_dirs.add_argument("-C", "--chdir", metavar="DIR", dest="chdir", default=DEFAULT_CHDIR,
                           help=("Change to the specified directory before doing anything. "
                                 "Alternatively, set ALIBUILD_CHDIR. Default '%(default)s'."))
  doctor_dirs.add_argument("-w", "--work-dir", dest="workDir", default=DEFAULT_WORK_DIR,  # TODO: previous default was "workDir".
                           help=("The toplevel directory under which builds should be done and build results "
                                 "should be installed. Default '%(default)s'."))
  doctor_dirs.add_argument("-c", "--config", dest="configDir", default="%sdist" % star,
                           help="The directory containing build recipes. Default '%(default)s'.")

  # Options for the init subcommand
  init_parser.add_argument("pkgname", nargs="?", default="", metavar="PACKAGE",
                           help="Package to clone locally. One of the packages in CONFIGDIR.")
  init_parser.add_argument("-a", "--architecture", dest="architecture", metavar="ARCH", default=detectedArch,
                           help=("Parse defaults using the specified architecture. Default is "
                                 "the current system architecture, which is '%(default)s'."))

  init_parser.add_argument("--defaults", dest="defaults", default="o2", metavar="DEFAULT",
                           help="Use defaults from CONFIGDIR/defaults-%(metavar)s.sh.")
  init_parser.add_argument("-z", "--devel-prefix", dest="develPrefix", default=".",
                           help=("Directory under which to clone the repository of build recipes. "
                                 "See also: -c/--config-dir. Default '%(default)s'."))

  init_parser.add_argument("--dist", metavar="[USER/REPO@]BRANCH", dest="dist", default="",
                           type=lambda x: alidist_string(x, star),
                           help=("Download the given repository containing build recipes into "
                                 "CONFIGDIR. Syntax: [user/repo@]branch or [url@]branch. The "
                                 "default repo is 'alisw/%sdist; the default branch is the "
                                 "repository's main branch." % star))

  init_dirs = init_parser.add_argument_group(title="Customise %sBuild directories" % star)
  init_dirs.add_argument("-C", "--chdir", metavar="DIR", dest="chdir", default=DEFAULT_CHDIR,
                         help=("Change to the specified directory before doing anything. "
                               "Alternatively, set ALIBUILD_CHDIR. Default '%(default)s'."))
  init_dirs.add_argument("-w", "--work-dir", dest="workDir", default=DEFAULT_WORK_DIR,
                         help=("The toplevel directory under which builds should be done and "
                               "build results should be installed. Default '%(default)s'."))
  init_dirs.add_argument("-c", "--config-dir", dest="configDir", default="%%(prefix)s%sdist" % star,
                         help=("The directory where build recipes will be placed. '%%(prefix)s' will "
                               "be replaced with 'DEVELPREFIX/'. Default '%(default)s'."))
  init_dirs.add_argument("--reference-sources", dest="referenceSources", metavar="MIRRORDIR",
                         default="%(workDir)s/MIRROR",
                         help=("The directory where reference git repositories will be cloned. "
                               "'%%(workDir)s' will be substituted by WORKDIR. Default '%(default)s'."))

  # Options for the version subcommand
  version_parser.add_argument("-a", "--architecture", dest="architecture", metavar="ARCH", default=detectedArch,
                              help=("Display the specified architecture next to the version number. Default is "
                                    "the current system architecture, which is '%(default)s'."))

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

VALID_ARCHS_RE = "^slc[5-9]_(x86-64|ppc64|aarch64)$|^(ubuntu|ubt|osx|fedora)[0-9]*_(x86-64|arm64)$"

def matchValidArch(architecture):
  return bool(re.match(VALID_ARCHS_RE, architecture))

ARCHITECTURE_TABLE = """\
On Linux, x86-64:
   RHEL6 / SLC6 compatible: slc6_x86-64
   RHEL7 / CC7 compatible: slc7_x86-64
   RHEL8 / CC8 compatible: slc8_x86-64
   Ubuntu 18.04 compatible: ubuntu1804_x86-64
   Ubuntu 20.04 compatible: ubuntu2004_x86-64
   Fedora 33 compatible: fedora33_x86-64
   Fedora 34 compatible: fedora34_x86-64

On Linux, POWER8 / PPC64 (little endian):
   RHEL7 / CC7 compatible: slc7_ppc64

On Mac, x86-64:
   Yosemite to Big Sur: osx_x86-64
   Big Sur: osx_arm64
"""

S3_SUPPORTED_ARCHS = "slc7_x86-64", "slc8_x86-64", "ubuntu2004_x86-64"

def finaliseArgs(args, parser, star):

  # Nothing to finalise for version or analytics
  if args.action in ["version", "analytics", "architecture"]:
    return args

  # --architecture can be specified in both clean and build.
  if args.action in ["build", "clean"] and not args.architecture:
    parser.error("Cannot determine architecture. Please pass it explicitly.\n\n"
                 + ARCHITECTURE_TABLE)

  if args.action == "build" and not args.forceUnknownArch and not matchValidArch(args.architecture):
    parser.error("Unknown / unsupported architecture: {architecture}.\n\n{table}"
                 "Alternatively, you can use the `--force-unknown-architecture' option."
                 .format(table=ARCHITECTURE_TABLE, architecture=args.architecture))

  if "noDevel" in args:
    args.noDevel = normalise_multiple_options(args.noDevel)
  if "disable" in args:
    args.disable = normalise_multiple_options(args.disable)
  if "force_rebuild" in args:
    args.force_rebuild = normalise_multiple_options(args.force_rebuild)

  if args.action in ["build", "init"]:
    args.referenceSources = format(args.referenceSources, workDir=args.workDir)

  if args.action == "build":
    args.configDir = args.configDir

    # On selected platforms, caching is active by default
    if args.architecture in S3_SUPPORTED_ARCHS and not args.preferSystem and not args.no_remote_store:
      args.noSystem = True
      if not args.remoteStore:
        args.remoteStore = "https://s3.cern.ch/swift/v1/alibuild-repo"
    elif args.no_remote_store:
      args.remoteStore = ""

    if args.remoteStore or args.writeStore:
      args.noSystem = True

    if "dockerImage" in args or args.docker_extra_args:
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
