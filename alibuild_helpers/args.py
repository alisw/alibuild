import argparse
from alibuild_helpers.utilities import detectArch, normalise_multiple_options, default_builder_image
from alibuild_helpers.workarea import cleanup_git_log
import multiprocessing

import re
import os
import shlex

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
def alidist_string(s):
  repo, have_repo_spec, ver = s.partition("@")
  if not have_repo_spec:
    repo, ver = "alisw/alidist", s
  return {"repo": repo, "ver": ver}


def doParseArgs():
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
  install_parser = subparsers.add_parser(
    "install", help="install a prebuilt package from a reapi:// store",
    description="Install a prebuilt package and its runtime closure straight "
                "from a reapi:// Action Cache + CAS, without recipes or a build.")
  reconstruct_parser = subparsers.add_parser(
    "reconstruct", help="reconstruct missing CAS tarballs from the Action Cache",
    description="Walk the build closure of a package in a reapi:// Action Cache, "
                "find tarballs missing from the CAS, and materialise the archived "
                "recipes so they can be rebuilt and the CAS repopulated.")
  migrate_parser = subparsers.add_parser(
    "migrate", help="migrate legacy tarballs into a reapi:// store",
    description="Migrate legacy (action-addressed) release tarballs into a "
                "reapi:// CAS + Action Cache, using each tarball's embedded "
                ".meta.json provenance and the recorded alidist commit.")
  version_parser = subparsers.add_parser("version", help="display %(prog)s version",
                                         description="Display %(prog)s and architecture.")
  completion_parser = subparsers.add_parser("completion", help="output shell completion code",
                                            description="Output shell completion code for bash or zsh.")
  completion_parser.add_argument("shell", choices=["bash", "zsh"],
                                 help="Shell type to generate completions for.")

  # Options for the analytics command
  analytics_parser.add_argument("state", choices=["on", "off"], help="Whether to report analytics or not")

  # Options for the install command
  install_parser.add_argument("package", metavar="PACKAGE", help="Package to install.")
  install_parser.add_argument("--version", required=True, metavar="VERSION",
                              help="Version of the package to install.")
  install_parser.add_argument("--revision", default=None, metavar="REVISION",
                              help="Revision to install. Defaults to the highest "
                                   "available for the version.")
  install_parser.add_argument("-a", "--architecture", dest="architecture", metavar="ARCH",
                              default=detectedArch,
                              help="Architecture to install for. Default '%(default)s'.")
  install_parser.add_argument("--remote-store", dest="remoteStore", metavar="STORE",
                              default="", required=True,
                              help="reapi:// store to install from.")
  install_parser.add_argument("--insecure", dest="insecure", action="store_true",
                              help="Use http instead of https for the reapi:// endpoint.")
  install_parser.add_argument("--ac-store", dest="acStore", default="", metavar="STORE",
                              help="Separate reapi:// ledger store for the Action Cache "
                                   "+ reconstruction inputs. Defaults to --remote-store.")
  install_parser.add_argument("-w", "--work-dir", dest="workDir", default=DEFAULT_WORK_DIR,
                              help="Default install prefix if --prefix is not given. "
                                   "Default '%(default)s'.")
  install_parser.add_argument("--prefix", dest="prefix", default=None, metavar="DIR",
                              help="Directory to install into. Defaults to the work dir.")

  # Options for the reconstruct command
  reconstruct_parser.add_argument("package", metavar="PACKAGE", help="Package to reconstruct.")
  reconstruct_parser.add_argument("--version", required=True, metavar="VERSION",
                                  help="Version of the package to reconstruct.")
  reconstruct_parser.add_argument("--revision", default=None, metavar="REVISION",
                                  help="Revision to reconstruct. Defaults to the highest "
                                       "available for the version.")
  reconstruct_parser.add_argument("-a", "--architecture", dest="architecture", metavar="ARCH",
                                  default=detectedArch,
                                  help="Architecture to reconstruct for. Default '%(default)s'.")
  reconstruct_parser.add_argument("--remote-store", dest="remoteStore", metavar="STORE",
                                  default="", required=True,
                                  help="reapi:// store to reconstruct from / into.")
  reconstruct_parser.add_argument("--insecure", dest="insecure", action="store_true",
                                  help="Use http instead of https for the reapi:// endpoint.")
  reconstruct_parser.add_argument("--ac-store", dest="acStore", default="", metavar="STORE",
                                  help="Separate reapi:// ledger store (Action Cache + "
                                       "reconstruction inputs). Defaults to --remote-store.")
  reconstruct_parser.add_argument("-w", "--work-dir", dest="workDir", default=DEFAULT_WORK_DIR,
                                  help="Work directory. Default '%(default)s'.")
  reconstruct_parser.add_argument("--output-config", dest="outputConfig", default=None, metavar="DIR",
                                  help="Where to materialise the recipes. Defaults to "
                                       "WORKDIR/reconstruct-PACKAGE.")

  # Options for the migrate command
  migrate_parser.add_argument("tarballs", metavar="TARBALL", nargs="+",
                              help="Legacy tarball(s) to migrate: local paths, or "
                                   "PACKAGE/VERSION-REVISION specs when --read-store "
                                   "is given.")
  migrate_parser.add_argument("--read-store", dest="read_store", default=None, metavar="URL",
                              help="Read-only http(s) old store to fetch tarballs from "
                                   "(e.g. https://s3.cern.ch/swift/v1/alibuild-repo). "
                                   "The old store is never written to.")
  migrate_parser.add_argument("--alidist", required=True, metavar="DIR",
                              help="Path to an alidist git checkout/mirror from which "
                                   "to recover recipes at the recorded commits.")
  migrate_parser.add_argument("-a", "--architecture", dest="architecture", metavar="ARCH",
                              default=detectedArch,
                              help="Architecture being migrated. Default '%(default)s'.")
  migrate_parser.add_argument("--remote-store", dest="remoteStore", metavar="STORE",
                              default="", required=True,
                              help="reapi:// store to migrate into.")
  migrate_parser.add_argument("--insecure", dest="insecure", action="store_true",
                              help="Use http instead of https for the reapi:// endpoint.")
  migrate_parser.add_argument("--ac-store", dest="acStore", default="", metavar="STORE",
                              help="Separate reapi:// ledger store (Action Cache + "
                                   "reconstruction inputs). Defaults to --remote-store.")
  migrate_parser.add_argument("-w", "--work-dir", dest="workDir", default=DEFAULT_WORK_DIR,
                              help="Work directory. Default '%(default)s'.")
  migrate_parser.add_argument("--container", dest="container", default=None, metavar="IMAGE",
                              help="Container image to record for the migrated builds "
                                   "(marked as assumed). Defaults to the architecture's "
                                   "default builder.")
  migrate_parser.add_argument("--storage", dest="storage", choices=("ephemeral", "permanent"),
                              default="ephemeral",
                              help="Retention for migrated tarball blobs: 'ephemeral' (default) "
                                   "or 'permanent' (pinned; use for real production releases).")
  migrate_parser.add_argument("--no-verify", dest="no_verify", action="store_true",
                              help="Skip the structural self-check of recovered recipes.")
  migrate_parser.add_argument("--closure", dest="closure", action="store_true",
                              help="Treat each TARBALL as a top package (PACKAGE/VERSION-"
                                   "REVISION) and migrate its whole build closure, read "
                                   "from the old store's dist tree. Requires --read-store.")
  migrate_parser.add_argument("-j", "--jobs", dest="jobs", type=int, default=1,
                              help="Migrate this many packages in parallel (overlaps the "
                                   "downloads/uploads). Peak disk scales with the number of "
                                   "jobs. Default %(default)d.")
  migrate_parser.add_argument("--snapshot-sources", dest="snapshot_sources", action="store_true",
                              help="Also archive each release's git source into the CAS "
                                   "(clones upstream once per package), so migrated releases "
                                   "become offline-reconstructible.")
  migrate_parser.add_argument("--source-mirror", dest="source_mirror", default=None, metavar="DIR",
                              help="Where to cache source clones for --snapshot-sources. "
                                   "Defaults to WORKDIR/MIRROR-migrate.")

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
  build_parser.add_argument("--annotate", default=[], action="append", metavar="PACKAGE=COMMENT",
                            help=("Store COMMENT in the build metadata for PACKAGE. This option "
                                  "can be given multiple times, if you want to store comments "
                                  "in multiple packages. The comment will only be stored if "
                                  "PACKAGE is compiled or downloaded during this run; if it "
                                  "already exists, this does not happen."))
  build_parser.add_argument("--only-deps", dest="onlyDeps", default=False, action="store_true",
                            help="Only build dependencies, not the main package (e.g. for caching)")

  build_docker = build_parser.add_argument_group(title="Build inside a container", description="""\
  Builds can be done inside a Docker container, to make it easier to get a
  common, usable environment. The Docker daemon must be installed and running
  on your system. By default, images from alisw/<platform>-builder:latest will
  be used, e.g. alisw/slc8-builder:latest. They will be fetched if unavailable.
  """)
  build_docker.add_argument("--docker", dest="docker", action="store_true",
                            help="Build inside a Docker container.")
  build_docker.add_argument("--docker-image", dest="dockerImage", metavar="IMAGE", default=None,
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
  build_remote.add_argument("--ac-store", dest="acStore", metavar="STORE", default="",
                            help=("For reapi:// stores, a separate ledger store for the "
                                  "Action Cache and reconstruction inputs (recipe/source/refs), "
                                  "which are kept while the artifact tarballs are deletable. "
                                  "Same ::rw syntax as --remote-store. Defaults to --remote-store."))
  build_remote.add_argument("--storage", dest="storage", choices=("ephemeral", "permanent"),
                            default="ephemeral",
                            help=("Retention for uploaded reapi:// tarball blobs: 'ephemeral' "
                                  "(default; LRU-expired by the bucket lifecycle, refreshed on "
                                  "use) or 'permanent' (pinned; also promotes any ephemeral blob "
                                  "it reuses). Use 'permanent' for production builds."))

  build_dirs = build_parser.add_argument_group(title="Customise aliBuild directories")
  build_dirs.add_argument("-C", "--chdir", metavar="DIR", dest="chdir", default=DEFAULT_CHDIR,
                          help=("Change to the specified directory before building. "
                                "Alternatively, set ALIBUILD_CHDIR. Default '%(default)s'."))
  build_dirs.add_argument("-w", "--work-dir", dest="workDir", default=DEFAULT_WORK_DIR,
                          help=("The toplevel directory under which builds should be done and build results "
                                "should be installed. Default '%(default)s'."))
  build_dirs.add_argument("-c", "--config-dir", dest="configDir", default="alidist",
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
  build_system.add_argument("--no-system", dest="noSystem", nargs="?", const="*", default=None, metavar="PACKAGES",
                            help="Never use system packages for the provided, command separated, PACKAGES, even if compatible.")

  # Options for clean subcommand
  clean_parser.add_argument("-a", "--architecture", dest="architecture", metavar="ARCH", default=detectedArch,
                            help=("Clean up build results for this architecture. Default is the current system "
                                  "architecture, which is '%(default)s'."))
  clean_parser.add_argument("--aggressive-cleanup", dest="aggressiveCleanup", action="store_true",
                            help="Delete as much build data as possible when cleaning up.")
  clean_dirs = clean_parser.add_argument_group(title="Customise aliBuild directories")
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
  deps_parser.add_argument("-e", dest="environment", action="append", default=[],
                           help="KEY=VALUE binding to add to the environment. May be specified multiple times.")
  deps_parser.add_argument("--output,-o", dest="output", metavar="FILE",
                           help="Save output to %(metavar)s.")

  deps_docker = deps_parser.add_argument_group(title="Use a Docker container", description="""\
  If you're planning to build inside a Docker container, e.g. using aliBuild
  build's --docker option, it may be useful to resolve dependencies inside that
  container as well, as which system packages are picked up may differ.
  """)
  deps_docker.add_argument("--docker", dest="docker", action="store_true",
                           help="Check for available system packages inside a Docker container.")
  deps_docker.add_argument("--docker-image", dest="dockerImage", metavar="IMAGE", default=None,
                           help=("The Docker image to use. Implies --docker. By default, an image "
                                 "is chosen based on the current or selected architecture."))
  deps_docker.add_argument("--docker-extra-args", default="", metavar="ARGLIST",
                           help=("Command-line arguments to pass to 'docker run'. "
                                 "Passed through verbatim -- separate multiple arguments "
                                 "with spaces, and make sure quoting is correct! Implies --docker."))

  deps_parser.add_argument_group(title="Customise aliBuild directories") \
             .add_argument("-c", "--config-dir", dest="configDir", default="alidist",
                           help="The directory containing build recipes. Default '%(default)s'.")

  deps_system = deps_parser.add_mutually_exclusive_group()
  deps_system.add_argument("--always-prefer-system", dest="preferSystem", action="store_true",
                           help="Always use system packages when compatible.")
  deps_system.add_argument("--no-system", dest="noSystem", nargs="?", const="*", default=None, metavar="PACKAGES",
                           help="Never use system packages for PACKAGES, even if compatible.")

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
  doctor_parser.add_argument("-e", dest="environment", action="append", default=[],
                            help="KEY=VALUE binding to add to the build environment. May be specified multiple times.")

  doctor_system = doctor_parser.add_mutually_exclusive_group()
  doctor_system.add_argument("--always-prefer-system", dest="preferSystem", action="store_true",
                             help="Always use system packages when compatible.")
  doctor_system.add_argument("--no-system", dest="noSystem", nargs="?", const="*", default=None, metavar="PACKAGES",
                             help="Never use system packages for the provided, command separated, PACKAGES, even if compatible.")

  doctor_docker = doctor_parser.add_argument_group(title="Use a Docker container", description="""\
  If you're planning to build inside a Docker container, e.g. using aliBuild
  build's --docker option, it may be useful to resolve dependencies inside that
  container as well, as which system packages are picked up may differ.
  """)
  doctor_docker.add_argument("--docker", dest="docker", action="store_true",
                             help="Check for available system packages inside a Docker container.")
  doctor_docker.add_argument("--docker-image", dest="dockerImage", metavar="IMAGE", default=None,
                             help=("The Docker image to use. Implies --docker. By default, an image "
                                   "is chosen based on the current or selected architecture."))
  doctor_docker.add_argument("--docker-extra-args", metavar="ARGLIST", default="",
                             help=("Command-line arguments to pass to 'docker run'. "
                                   "Passed through verbatim -- separate multiple arguments "
                                   "with spaces, and make sure quoting is correct! Implies --docker."))

  doctor_remote = doctor_parser.add_argument_group(title="Re-use prebuilt tarballs", description="""\
  Reusing prebuilt tarballs saves compilation time, as common packages need not
  be rebuilt from scratch. rsync://, https://, b3:// and s3:// remote stores
  are recognised. Some of these require credentials: s3:// remotes require an
  ~/.s3cfg; b3:// remotes require AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY
  environment variables. A useful remote store is
  'https://s3.cern.ch/swift/v1/alibuild-repo'. It requires no credentials and
  provides tarballs for the most common supported architectures.
  """)
  doctor_remote.add_argument("--no-remote-store", action="store_true",
                            help="Disable the use of the remote store, even if it is enabled by default.")
  doctor_remote.add_argument("--remote-store", dest="remoteStore", metavar="STORE", default="", help="""\
  Where to find prebuilt tarballs to reuse. See above for available remote stores.
  End with ::rw if you want to upload (in that case, ::rw is stripped and --write-store
  is set to the same value). Implies --no-system. May be set to a default store on some
  architectures; use --no-remote-store to disable it in that case.
  """)
  doctor_remote.add_argument("--write-store", dest="writeStore", metavar="STORE", default="",
                            help=("Where to upload newly built packages. Same syntax as --remote-store, "
                                  "except ::rw is not recognised. Implies --no-system."))
  doctor_remote.add_argument("--insecure", dest="insecure", action="store_true",
                            help="Don't validate TLS certificates when connecting to an https:// remote store.")

  doctor_dirs = doctor_parser.add_argument_group(title="Customise aliBuild directories")
  doctor_dirs.add_argument("-C", "--chdir", metavar="DIR", dest="chdir", default=DEFAULT_CHDIR,
                           help=("Change to the specified directory before doing anything. "
                                 "Alternatively, set ALIBUILD_CHDIR. Default '%(default)s'."))
  doctor_dirs.add_argument("-w", "--work-dir", dest="workDir", default=DEFAULT_WORK_DIR,  # TODO: previous default was "workDir".
                           help=("The toplevel directory under which builds should be done and build results "
                                 "should be installed. Default '%(default)s'."))
  doctor_dirs.add_argument("-c", "--config", dest="configDir", default="alidist",
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
                           type=alidist_string,
                           help=("Download the given repository containing build recipes into "
                                 "CONFIGDIR. Syntax: [user/repo@]branch or [url@]branch. The "
                                 "default repo is 'alisw/alidist; the default branch is the "
                                 "repository's main branch."))

  init_dirs = init_parser.add_argument_group(title="Customise aliBuild directories")
  init_dirs.add_argument("-C", "--chdir", metavar="DIR", dest="chdir", default=DEFAULT_CHDIR,
                         help=("Change to the specified directory before doing anything. "
                               "Alternatively, set ALIBUILD_CHDIR. Default '%(default)s'."))
  init_dirs.add_argument("-w", "--work-dir", dest="workDir", default=DEFAULT_WORK_DIR,
                         help=("The toplevel directory under which builds should be done and "
                               "build results should be installed. Default '%(default)s'."))
  init_dirs.add_argument("-c", "--config-dir", dest="configDir", default="%(prefix)salidist",
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
    if x in ["build", "init", "clean", "analytics", "doctor", "deps", "completion", "install", "reconstruct", "migrate"]:
      return 1
    return 2
  rest.sort(key=optionOrder)
  sys.argv = [prog] + rest
  args = finaliseArgs(parser.parse_args(), parser)
  return (args, parser)

VALID_ARCHS_RE = "^slc[5-9]_(x86-64|ppc64|aarch64)$|^(ubuntu|ubt|osx|fedora)[0-9]*_(x86-64|arm64)$"

def matchValidArch(architecture):
  return bool(re.match(VALID_ARCHS_RE, architecture))

ARCHITECTURE_TABLE = """\
On Linux, x86-64:
   RHEL6 / SLC6 compatible: slc6_x86-64
   RHEL7 / CC7 compatible: slc7_x86-64
   RHEL8 / CC8 compatible: slc8_x86-64
   RHEL9 / ALMA9 compatible: slc9_x86-64
   Ubuntu 20.04 compatible: ubuntu2004_x86-64
   Ubuntu 22.04 compatible: ubuntu2204_x86-64
   Ubuntu 24.04 compatible: ubuntu2404_x86-64
   Fedora 33 compatible: fedora33_x86-64
   Fedora 34 compatible: fedora34_x86-64

On Linux, ARM:
   RHEL9 / ALMA9 compatible: slc9_aarch64

On Linux, POWER8 / PPC64 (little endian):
   RHEL7 / CC7 compatible: slc7_ppc64

On Mac, 1-2 latest supported OSX versions:
   Intel: osx_x86-64
   Apple Silicon: osx_arm64
"""

# When updating this variable, also update docs/docs/user.md!
S3_SUPPORTED_ARCHS = "slc7_x86-64", "slc8_x86-64", "ubuntu2004_x86-64", "ubuntu2204_x86-64", "ubuntu2404_x86-64", "slc9_x86-64", "slc9_aarch64"

def finaliseArgs(args, parser):

  # Nothing to finalise for version, analytics, or completion
  if args.action in ["version", "analytics", "architecture", "completion"]:
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
    args.referenceSources = args.referenceSources % {"workDir": args.workDir}
    # Do this cleanup as early as possible to avoid false positives due to
    # stale git logs from previous invocations.
    cleanup_git_log(args.referenceSources)

  if args.action in ("build", "doctor", "deps"):
    if args.dockerImage or args.docker_extra_args:
      args.docker = True
    # In case we build with docker / containers, we add a special
    # devel prefix (if not already present) so that we do not pollute
    # the namespace of the current architecture
    if args.docker and getattr(args, "develPrefix", None):
      args.develPrefix = args.architecture

    args.docker_extra_args = shlex.split(args.docker_extra_args)

    if args.docker and args.architecture.startswith("osx"):
      parser.error("cannot use `-a %s` and --docker" % args.architecture)

    if args.docker and commands.getstatusoutput("which docker")[0] and commands.getstatusoutput("which container")[0]:
      parser.error("cannot use --docker as no container runtime (docker or container) was found")

    # If specified, used the docker image requested, otherwise, if running
    # in docker the docker image is given by the first part of the
    # architecture we want to build for.
    if args.docker and not args.dockerImage:
      args.dockerImage = default_builder_image(args.architecture)

  if "annotate" in args:
    for comment_assignment in args.annotate:
      if "=" not in comment_assignment:
        parser.error("--annotate takes arguments of the form PACKAGE=COMMENT")
    args.annotate = {
      package: comment
      for package, _, comment
      in (assignment.partition("=") for assignment in args.annotate)
    }

  if args.action in ("build", "doctor"):
    args.configDir = args.configDir

    # On selected platforms, caching is active by default
    if args.architecture in S3_SUPPORTED_ARCHS and not args.preferSystem and not args.no_remote_store:
      args.noSystem = "*"
      if not args.remoteStore:
        args.remoteStore = "https://s3.cern.ch/swift/v1/alibuild-repo"
    elif args.no_remote_store:
      args.remoteStore = ""

    if args.remoteStore or args.writeStore:
      args.noSystem = "*"

    if args.remoteStore.endswith("::rw") and args.writeStore:
      parser.error("cannot specify ::rw and --write-store at the same time")

    if args.remoteStore.endswith("::rw"):
      args.remoteStore = args.remoteStore[0:-4]
      args.writeStore = args.remoteStore

    # The optional ledger store mirrors --remote-store's ::rw semantics.
    args.acWriteStore = ""
    if getattr(args, "acStore", "").endswith("::rw"):
      args.acStore = args.acStore[0:-4]
      args.acWriteStore = args.acStore

  if args.action in ["build", "init"]:
    if "develPrefix" in args and args.develPrefix is None:
      if "chdir" in args:
        args.develPrefix = basename(abspath(args.chdir))
      else:
        args.develPrefix = basename(dirname(abspath(args.configDir)))
    if getattr(args, "docker", False):
      args.develPrefix = f"{args.develPrefix}-{args.architecture}" if "develPrefix" in args else args.architecture

  if args.action == "init":
    args.configDir = args.configDir % {"prefix": args.develPrefix + "/"}
  elif args.action == "build":
    pass
  elif args.action == "clean":
    pass
  else:
    pass
  return args
