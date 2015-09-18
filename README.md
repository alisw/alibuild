# aliBuild

A simple build tool for ALICE experiment software and its externals. Recipes
for the externals and ALICE software are stored in
[alidist](https://github.com/alisw/alidist)

## Instant Gratification

Instant gratification (almost) with:

    git clone https://github.com/alisw/alibuild.git
    git clone https://github.com/alisw/alidist.git
    alibuild/aliBuild -d -a slc7_amd64 -j 16 build aliroot

## Recipes format

The recipes are found in the a separate repository. The repository can be 
specified via the `-c` option and defaults to _alidist_.

The recipes themselves are called `<package>.sh` where `<package>` is the name
of the package whose build recipe is described. Please note that all recipe
filenames are lowercase: _e.g._ the recipe for `ROOT` will be in `root.sh`.

The recipe itself is made up of two parts: an header, and the actual build
script, separated by three dashes (`---`) standalone.

The header is in [YAML](http://yaml.org) format and contains metadata about the
package, like its name, version and where to find the sources.

The build script is a standard build script which is invoked by the tool to
perform the build itself. A few environment variable can be expected to be
defined when the script is invoked.

An example recipe for `zlib` is the following:

```yaml
package: zlib
version: v1.2.8
source: https://github.com/star-externals/zlib
tag: v1.2.8
---
#!/bin/sh
./configure --prefix=$INSTALLROOT
make ${JOBS+-j $JOBS}
make install
```

### The header

The following entries are mandatory in the header:

  - `package`: the name of the package
  - `version`: a mnemonic for the version which will be used in the name
    of the package. Notice you can actually use some special formatting
    substitutions which will be replaced with the associated value on build.
    Valid substitutions are:
      - ```%(commit_hash)s```
      - ```%(short_hash)s```
      - ```%(tag)s```
      - ```%(year)s```
      - ```%(month)s```
      - ```%(hour)s```

The following entries are optional in the header:

  - `source`: URL of a Git repository from which the source is downloaded.
    Notice it's good practice to make sure that they are already patched, so
    that you can easily point to the actual sources used by the software.
  - `tag`: tag in the above mentioned repository which points to the software
    to be built.
  - `env`: dictionary whose key-value pairs are environment variables to be set,
    *e.g.*:

        env:
          "$ROOTSYS": $ROOT_ROOT

  - `prepend_path`: dictionary whose key-value pairs are an environment variable
    name and a path to be prepended to it, as it happens in `LD_LIBRARY_PATH`.
    You can append multiple paths to a single variable by specifying a list too,
    *e.g.*:

        prepend_path:
          "PATH": "$FOO_ROOT/binexec/foobar"
          "LD_LIBRARY_PATH": [ "$FOO_ROOT/sub/lib", "$FOO_ROOT/sub/lib64 ]
          "DYLD_LIBRARY_PATH":
            - "$FOO_ROOT/sub/lib"
            - "$FOO_ROOT/sub/lib64

    will result in prepending `$FOO_ROOT/binexec/foobar` to `$PATH`, and both
    `$FOO_ROOT/sub/lib` and `lib64` to `LD_LIBRARY_PATH` and
    `DYLD_LIBRARY_PATH`.
  - `append_path`: same as `prepend_path` but paths are appended rather than
    prepended.
  - `requires`: a list of run-time and build-time dependency for the package. E.g.:
    
        package: AliRoot
        requires:
          - ROOT
        ...

    The specified dependencies will be built before building the given package.
    You can specify platform-specific dependencies by appending `:<regexp>` to
    the dependency name. Such a reqular expression will be matched against the
    architecture provided via `--architecture` and if it does not match it will
    not be included. For instance:
    
        package: AliRoot-test
        requires:
          - "igprof:(?!osx).*"
        ...

    will make sure that `IgProf` is only built on platforms which do not begin
    by `osx`.
    will make sure that IgProf is only built on architectures whose name does
    not begin with `osx`.
  - `force_rebuild`: set it to `true` to force re-running the build recipe.

### The body

This is the build script executed to effectively build and install your
software. Being a shell script you can be as flexible as you want in its
definition.

Some environment variables are made available to the script.

 - `INSTALLROOT`: the installation prefix. This is commonly passed in the form
   `./configure --prefix=$INSTALLROOT` or
   `cmake -DCMAKE_INSTALL_PREFIX=$INSTALLROOT`. The build tool will create an
   archive based on the sole content of this directory.
 - `PKGNAME`: name of the current package.
 - `PKGVERSION`: package version, as defined in the recipe's `version:` field.
 - `PKGREVISION`: the "build iteration", automatically incremented by the build
   script.
 - `PKGHASH`: SHA1 checksum of the recipe.
 - `ARCHITECTURE`: an arbitrary string summarizing the current build platform.
   This is passed using the `--architecture` (or `-a`) argument to the build
   script.
 - `SOURCE0`: URL of the source code. Note: if `source:` is not provided in the
   recipe, the variable will be empty.
 - `GIT_TAG`: the Git reference to checkout.
 - `JOBS`: number of parallel jobs to use during compilation. This is passed on
   the command line to the build script, and should be used in a context like
   `make -j$JOBS`.
 - `BUILDDIR`: the working directory. This is, *e.g.*, the "build directory"
   for CMake, *i.e.* the directory from where you invoke `cmake`. You should not
   write files outside this directory.
 - `BUILD_ROOT`: it contains `BUILDDIR` and the logfile for the build
 - `CONFIG_DIR`: directory containing all the build recipes.
 - `SOURCEDIR`: where the sources are cloned.

For each dependency already built, the corresponding enviornment file is loaded.
This will include, apart from custom variables and the usual `PATH` and library
paths, the following specific variables (`<PACKAGE>` is the package name,
uppercased):

 - `<PACKAGE>_ROOT`: package installation directory.
 - `<PACKAGE>_VERSION`: package version.
 - `<PACKAGE>_REVISION`: package build number.
 - `<PACKAGE>_HASH`: hash of the recipe used to build the package.


### The environment file

In every package you can find an environment file in
`$<PACKAGE>_ROOT/etc/profile.d/init.sh` which sets up the environment so that
it the built software can be used.

## Speedup build process by using a build store.

In order to avoid rebuilding packages every single time we start from scratch,
aliBuild supports the concept of an object store where already built tarballs
are kept. This means that if it notices that a recipe being built has the same
hash of one of the tarballs in the store, it will fetch it, unpack, and
relocate it as required. 

In order to specify the object store you can use the option `--remote-store
<uri>` where `<uri>` is either a file path, or in the for
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

## Dependency graph

Assuming you are in a directory containing `alibuild` and `alidist`, you can
generate a dependency plot with:

    alibuild/aliDeps

A file named `dist.pdf` will be created. `dot` from Graphviz is required. To
show all the dependencies recursively from a specific package (for instance,
`ThePEG`) use:

    alibuild/aliDeps ThePEG

Use `-h` or `--help` for more options.
