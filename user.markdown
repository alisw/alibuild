---
title: ALIBUILD
subtitle: User command line reference manual
layout: main
---

## SYNOPSIS

For a quick start introduction, please look [here](./quick.html).

    usage: alibuild [-h] [--config-dir CONFIGDIR] [--no-local NODEVEL] [--docker]
                    [--work-dir WORKDIR] [--architecture ARCHITECTURE]
                    [-e ENVIRONMENT] [-v VOLUMES] [--jobs JOBS]
                    [--reference-sources REFERENCESOURCES]
                    [--remote-store REMOTESTORE] [--write-store WRITESTORE]
                    [--disable PACKAGE] [--defaults [FILE]]
                    [--always-prefer-system] [--no-system]
                    [--force-unknown-architecture] [--insecure]
                    [--aggressive-cleanup] [--debug] [--no-auto-cleanup]
                    [--devel-prefix [DEVELPREFIX]] [--dist DIST] [--dry-run]
                    {init,build,clean} [pkgname]

    positional arguments:
      {init,build,clean}    what alibuild should do
      pkgname               One (or more) of the packages in `alidist'

    optional arguments:
      -h, --help            show this help message and exit
      --config-dir CONFIGDIR, -c CONFIGDIR
      --no-local NODEVEL    Do not pick up the following packages from a local
                            checkout.
      --docker
      --work-dir WORKDIR, -w WORKDIR
      --architecture ARCHITECTURE, -a ARCHITECTURE
      -e ENVIRONMENT
      -v VOLUMES            Specify volumes to be used in Docker
      --jobs JOBS, -j JOBS
      --reference-sources REFERENCESOURCES
      --remote-store REMOTESTORE
                            Where to find packages already built for reuse.Use
                            ssh:// in front for remote store. End with ::rw if you
                            want to upload.
      --write-store WRITESTORE
                            Where to upload the built packages for reuse.Use
                            ssh:// in front for remote store.
      --disable PACKAGE     Do not build PACKAGE and all its (unique)
                            dependencies.
      --defaults [FILE]     Specify which defaults to use
      --always-prefer-system
                            Always use system packages when compatible
      --no-system           Never use system packages
      --force-unknown-architecture
                            Do not check for valid architecture
      --insecure            Do not check for valid certificates
      --aggressive-cleanup  Perform additional cleanups
      --debug, -d
      --no-auto-cleanup     Do not cleanup build by products automatically
      --devel-prefix [DEVELPREFIX], -z [DEVELPREFIX]
                            Version name to use for development packages. Defaults
                            to branch name.
      --dist DIST           Prepare development mode by downloading the given
                            recipes set ([user/repo@]branch)
      --dry-run, -n         Prints what would happen, without actually doing the
                            build.


## Speedup build process by using a build store

In order to avoid rebuilding packages every single time we start from scratch,
aliBuild supports the concept of an object store where already built tarballs
are kept. This means that if it notices that a recipe being built has the same
hash of one of the tarballs in the store, it will fetch it, unpack, and
relocate it as required.

In order to specify the object store you can use the option `--remote-store <uri>`
where `<uri>` is either a file path, or in the for
`ssh://<hostname>:<path>`. Notice the latter will use ssh to connect to the
host, therefore you must make sure you have access to `<hostname>`.

If you have write access to the store, you can upload tarballs by specifying
`--write-store <uri>` or by adding `::rw` to the `--remote-store` uri.

Support for web based repository is foreseen, but not yet implemented.

## Developing packages locally

One of the use cases we want to cover is the ability to develop external
packages without having to go through an commit - push - pull cycle.

In order to do so, you can simply checkout the package you want to
develop at the same level as alibuild and alidist.

For example, if you want to build O2 while having the ability to modify
ROOT, you can do the following:

    git clone https://github.com/alisw/alibuild
    git clone https://github.com/alisw/alidist
    git clone https://github.com/root-mirror/root ROOT
    <modify files in ROOT/>
    alibuild/aliBuild ... build O2

The above will make sure the build will pick up your changes in the local
directory. 

As a cherry on the cake, in case your recipe does not require any environment,
you can even do:

    cd sw/BUILD/ROOT/latest
    make install

and it will correctly install everything in `sw/<arch>/ROOT/latest`.

It's also important to notice that if you use your own checkout of a
package, you will not be able to write to any store and the generated
tgz will be empty. 

If you wish to temporary compile with the package as specified by
alidist, you can use the `--no-local <PACKAGE>` option.

### Incremental builds

When developing locally using the development mode, if the external
is well behaved and supports incremental building, it is possible to
specify an `incremental_recipe` in the YAML preamble. Such a recipe will
be used after the second time the build happens (to ensure that the non
incremental parts of the build are done) and will be executed directly
in $BUILDDIR, only recompiled what changed. Notice that if this is the
case the incremental recipe will always be executed.

### Forcing a different architecture

While alibuild does its best to find out which OS / distribution you are
using, sometimes it might fail to do so, for example in the case you
start using a new *buntu flavour or a bleeding edge version of Centos.
In order to force the the correct architecture for the build you can use
the `--architecture` (`-a`) flag with one of the supported options:

- `slc5_x86-64`: Scientific Linux 5 and compatibles, on Intel / AMD x86-64.
- `slc6_x86-64`: Scientific Linux 6 and compatibles, on Intel / AMD x86-64.
- `slc7_x86-64`: CERN Centos 7 and compatibles, on Intel / AMD x86-64.
- `ubuntu1404_x86-64`: Ubuntu 1404 and compatibles, on Intel / AMD x86-64.
- `osx_x86-64`: OSX, on Intel / AMD x86-64.
- `slc7_ppc64`: RHEL7 on POWER8 (LE only for now).

### Running in Docker

Very often one needs to run on a platform which is different from
the one being used for development. The common use case is that
development happens on a Mac while production runs on some older Linux
distribution like SLC5 or SLC6. In order to improve the experience
of cross platform development aliBuild now offers the ability to run
in [Docker](http://docker.io) via the `--docker` option. When it is
specified the first part of the architecture will be used to construct
the name of the docker container to be used for the build and the build
itself will be performed inside that container. For example if you
specify:

```bash
alibuild --docker -a slc7_x86-64 build ROOT
```

the build itself will happen inside the alisw/slc7-builder Docker
container. Environment variables can be passed to docker by specifying
them with the `-e` option. Extra volumes can be specified with the -v
option using the same syntax used by Docker.

## Defaults

aliBuild uses a special file, called "defaults-release.sh" which will
be included as a build requires of any recipe. This is in general handy
to specify common options like CXXFLAGS or dependencies. It's up to the
recipe handle correctly the presence of these options.

It is also possible to specify on the command line a different set of
defaults, for example if you want to include code coverage. This is
done via the `--defaults <default-name>` option which will change the
defaults included to be `defaults-<default-name>.sh`.

An extra variable `%(defaults_upper)s` can be used to form the version
string accordingly. For example you could trigger a debug build by
adding `--defaults debug`, which will pick up defaults-debug.sh, and
then have:

    version: %(tag)s%(defaults_upper)s

in one of your recipes, which will expand to:

    version: SOME_TAG_DEBUG

If you want to add your own default, you should at least provide:

- **CXXFLAGS**: the CXXFLAGS to use
- **CFLAGS**: the CFLAGS to use
- **LDFLAGS**: the LDFLAGS tos use
- **CMAKE_BUILD_TYPE**: the build type which needs to be used by cmake projects

## Disabling packages

You can optionally disable certain packages by specifying them as a comma
separated list with the `--disable` option.

## Controlling which system packages are picked up

When compiling, there is a number of packages which can be picked up
from the system, and only if they are not found, do not have their
devel part installed, or they are not considered good enough they are
recompiled from scratch. A typical example is things like autotools,
zlib or cmake which should be available on a standard developer machine
and we rebuild them as last resort. In certain cases, to ensure full
compatibility on what is done in production it might be desirable to
always pick up our own version of the tools. This can be done by passing
the `--no-system` option to alibuild. On the other hand, there might
be cases in which you want to pick up not only basic tools, but also
advanced ones like ROOT, Geant4, or Pythia from the system, either to
save time or because you have a pre-existing setup which you do not want
to touch. In this case you can use `--always-prefer-system` option which
will try very hard to reuse as many system packages as possible (always
checking they are actually compatible with the one used in the recipe).

## Monitoring builds with Riemann

aliBuild comes with support for pushing every single line produced by
the output to a [Riemann](https://riemann.io) instance. This can be
enabled by setting the two environment variables:

- `RIEMANN_HOST`: the hostname Riemann server you want to push your data
  to, defaults to `localhost`.
- `RIEMANN_PORT`: the port the Riemann server is listening at, defaults
  to 5555.

## Cleaning up the build area (new in 1.1.0)

Whenever you build using a different recipe or set of sources, alibuild
makes sure that all the dependent packages which might be affected
by the change are rebuild, and it does so in a different directory.
This can lead to the profiliferation of many build / installation
directories, in particular while developing a recipe for a new package
(e.g. a new generator).

In order to remove all past builds and only keep the latest one for each
alidist area you might have used and for each breanch (but not commit)
ever build for a given development package you can use the

    aliBuild clean

subcommand which will do its best to clean up your build and
installation area.
