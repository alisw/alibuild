---
title: ALIBUILD
subtitle: User command line reference manual
layout: main
---

## SYNOPSIS

For a quick start introduction, please look [here](./quick.html).

    usage: aliBuild [-h] 
                    [--config-dir CONFIGDIR] 
                    [--devel DEVEL] 
                    [--docker]
                    [--work-dir WORKDIR] 
                    --architecture ARCHITECTURE
                    [-e ENVIRONMENT] 
                    [-v VOLUMES] 
                    [--jobs JOBS]
                    [--reference-sources REFERENCESOURCES]
                    [--remote-store REMOTESTORE] 
                    [--write-store WRITESTORE]
                    [--disable PACKAGE] 
                    [--defaults FILE] 
                    [--debug]
                    action pkgname

    positional arguments:
      action
        pkgname

## Speedup build process by using a build store.

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

## Developing packages locally (experimental)

One of the use cases we want to cover is the ability to develop external
packages without having to go through an commit - push - pull cycle.

In order to do so, you can use the `--devel <package>` where package is a
package which you have already checked out locally at the same level as
alibuild and alidist. For example, if you want to build O2 while having the
ability to modify ROOT, you can do the following:

    git clone https://github.com/alisw/alibuild
    git clone https://github.com/alisw/alidist
    git clone https://github.com/root-mirror/root
    <modify files in root/>
    alibuild/aliBuild ... --devel ROOT build O2

the above will make sure the build will pick up your changes in the local
directory. 

As a cherry on the cake, in case your recipe does not require any environment,
you can even do:

    cd sw/BUILD/ROOT/latest
    make install

and it will correctly install everything in `sw/<arch>/ROOT/latest`.

It's also important to notice that if you use the devel mode, you will not be
able to write to any store and the generated tgz will be empty.

### Incremental builds

When developing locally using the `--devel` mode, if the external is well
behaved and supports incremental building, it is possible to specify an
`incremental_recipe` in the YAML preamble. Such a recipe will be used after the
second time the build happens (to ensure that the non incremental parts of the
build are done) and will be executed directly in $BUILDDIR, only recompiled
what changed. Notice that if this is the case the incremental recipe will always
be executed.


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

## Monitoring builds with Riemann

aliBuild comes with support for pushing every single line produced by
the output to a [Riemann](https://riemann.io) instance. This can be
enabled by setting the two environment variables:

- `RIEMANN_HOST`: the hostname Riemann server you want to push your data to, defaults 
  to `localhost`.
- `RIEMANN_PORT`: the port the Riemann server is listening at, defaults to 5555.
