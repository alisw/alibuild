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
                    [--devel-prefix [DEVELPREFIX]] [--dist DIST]
                    [--dry-run] [--fetch-repos|-u]
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
      --fetch-repos, -u     Fetch repository updates


## Using precompiled packages

By running aliBuild with no special option on CC7, it will automatically try to
use as many precompiled packages as possible by downloading them from a default
central server. By using precompiled packages you lose the ability to pick some
of them from your system. If you do not want to use precompiled packages and you
want to pick as many packages as possible from your system, you should manually
specify the `--always-prefer-system` option.

It is possible to benefit from precompiled builds on every platform, provided
that the server caching the builds is maintained by yourself. Since every build
is stored as a tarball with a unique hash, it is sufficient to provide for a
server or shared space where cached builds will be stored and made available to
others.

In order to specify the cache store, use the option `--remote-store <uri>`,
where `<uri>` can be:

* a local path, for instance `/opt/alibuild_cache`,
* a remote SSH accessible path, `ssh://<host>:<path>`,
* an unencrypted rsync path, `rsync://<host>/path`,
* a HTTP(s) server, `http://<host>/<path>`.

The first three options can also be writable (if you have proper permissions):
if you specify `::rw` at the end of the URL, your builds will be cached there.
This is normally what sysadmins do to precache builds: other users can simply
use the same URL in read-only mode (no `::rw` specified) to fetch the builds.

You need to make sure you have proper filesystem/SSH/rsync permissions of
course.

It is also possible to specify a write store different from the read one by
using the `--write-store` option.


## Developing packages locally

One of the use cases we want to cover is the ability to develop external
packages without having to go through an commit - push - pull cycle.

In order to do so, you can simply checkout the package you want to
develop at the same level as alibuild and alidist.

For example, if you want to build O2 while having the ability to modify
ROOT, you can do the following:

    git clone https://github.com/alisw/alidist
    git clone https://github.com/root-mirror/root ROOT
    <modify files in ROOT/>
    aliBuild ... build O2

The above will make sure the build will pick up your changes in the local
directory.

As a cherry on the cake, in case your recipe does not require any environment,
you can even do:

    cd sw/BUILD/ROOT/latest
    make install

and it will correctly install everything in `sw/<arch>/ROOT/latest`.
This of course mean that for each development package you might end up
with one or more build directories which might increase the used disk
space.

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
in [Docker](https://docker.io) via the `--docker` option. When it is
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

By default `aliBuild` is tuned to build the production version of ALICE
Offline software, as deployed on the Grid, so some of the choices in
terms of version of the packages and compilation flags are tweaked for
that. For example, ROOT5 is used because that's what is what has been
validated for datataking and the choice will not change until the end of
RUN2 of LHC. In order to change that and use, for example, a more recent
version of ROOT you can use the `--default root6` option which will
enable ROOT6 based builds. For a more complete description of how defaults
works please look at [the reference manual](reference.html#defaults).

## Disabling packages

You can optionally disable certain packages by specifying them as a comma
separated list with the `--disable` option.

Moreover, starting from aliBuild 1.4.0, it will also be
possible to disable packages by adding them to the `disable`
keyword of your defaults file (see previous paragraph). See the
[defaults-o2.sh](https://github.com/alisw/alidist/blob/master/defaults-o2.sh)
file for an example of how to disable `AliEn-Runtime` and `AliRoot`
when passing `--defaults o2`.

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
the output to a [Riemann](http://riemann.io) instance. This can be
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

## Upgrading aliBuild

aliBuild is installed via `pip`. In order to upgrade it on most laptops (in
particular Macs) do:

    pip install --upgrade alibuild

or in case you need to be root (_e.g._ on Ubuntu and most Linux distributions
for convenience):

    sudo pip install --upgrade alibuild

In general updating aliBuild is safe and it should never trigger a rebuild or
break compilation of older versions of alidist (i.e. we do try to guarantee
backward compatibility). In no case an update of aliBuild will result in the
update of `alidist`, which users will have to be done separately.
In case some yet to appear bug in alibuild will force us to rebuild a
previously built area, this will be widely publicized and users will get a warning
when running the command.

## Rebuilding packages from branches instead of tags

Generally, recipes specify a Git _tag_ name in the `tag:` field. In some cases,
_branch names_ might be used instead (such as `tag: master` or `tag: dev`). In
such a rare case, aliBuild needs to know what is the last branch commit to
determine whether a rebuild is necessary.

Such check by default uses cached information instead of doing very slow queries
to remote servers. This means that aliBuild is fast in determining which
packages to build. However, packages using branch names might not get rebuilt as
expected when new changes are pushed to those branches.

In this case, you can ask aliBuild to update cached branches information by
adding the `-u` or `--fetch-repos` option. Note that by default this is not
needed, it's only for very special use cases (such as centralized builds and
server-side pull request checks).

## Generating a dependency graph

It is possible to generating a PDF with a dependency graph using the `aliDeps`
tool. Assuming you run it from a directory containing `alidist`, and you have
Graphviz installed on your system, you can simply run:

    aliDeps O2 --defaults o2 --outgraph graph.pdf

The example above generates a dependency graph for the package `O2` using the
defaults `o2`, and saving the results to a PDF file named `graph.pdf`. This is
what the graph looks like:

![drawing](deps.png)

Packages in green are runtime dependencies, purple are build dependencies, while
red packages are runtime dependencies in some cases, and build dependencies in
others (this can indicate an error in the recipes).

Connections are color-coded as well: blue connections indicate a runtime
dependency whereas a grey connection indicate a build dependency.

By default, `aliDeps` runs the usual system checks to exclude packages that can
be taken from the system. If you want to display the full list of dependencies,
you may want to use:

    aliDeps O2 --defaults o2 --no-system --outgraph graph.pdf

Please run `aliDeps --help` for further information.
