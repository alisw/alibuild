---
title: ALIBUILD
subtitle: Recipe reference manual
layout: main
---

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

    package: zlib
    version: v1.2.8
    source: https://github.com/star-externals/zlib
    tag: v1.2.8
    ---
    #!/bin/sh
    ./configure --prefix=$INSTALLROOT
    make ${JOBS+-j $JOBS}
    make install

### The header

The following entries are mandatory in the header:

  - `package`: the name of the package
  - `version`: a mnemonic for the version which will be used in the name
    of the package. Notice you can actually use some special formatting
    substitutions which will be replaced with the associated value on build.
    Valid substitutions are:
      - `%(commit_hash)s`
      - `%(short_hash)s`
      - `%(tag)s`
      - `%(tag_basename)s`
      - `%(year)s`
      - `%(month)s`
      - `%(day)s`
      - `%(hour)s`

    Month, day and hour are zero-padded to two digits.

The following entries are optional in the header:

  - `source`: URL of a Git repository from which the source is downloaded.
    Notice it's good practice to make sure that they are already patched, so
    that you can easily point to the actual sources used by the software.
  - `tag`: tag in the above mentioned repository which points to the software
    to be built.
  - `tag_basename`: if the tag resembles a path, e.g. `a/b/c`, returns the 
    last part of the path, `c` in this case.
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
  - `build_requires`: currently behaves just like `requires` with the exception
    that packages in this list are not included in the dependency graph
    produced by alideps.
  - `force_rebuild`: set it to `true` to force re-running the build recipe.
  - `prefer_system_check`: a script which is used to determine whether
    or not the system equivalent of the package can be used. See also
    `prefer_system`. If the `--no-system` option is specified, our own
    version of the tool is used. Shell exit code is used to steer the build: in
    case the check returns 0, the system package is used and the recipe is not
    run. In case the check returns nonzero, our own version of the package is
    built through the recipe.
  - `prefer_system`: a regular expression for architectures which should
    use the `prefer_system_check` by default to determine if the system
    version of the tool can be used. When the rule matches, the result of
    `prefer_system_check` determines whether to build the recipe. When the rule
    does not match, the check is skipped and the recipe is run. Using the switch
    `--always-prefer-system` runs the check always (even when the regular
    expression for the architecture does not match).

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
 - `REQUIRES`: space-separated list of all dependencies, both runtime and build
   only.
 - `BUILD_REQUIRES`: space-separated list of all build dependencies, not needed
   at runtime.
 - `RUNTIME_REQUIRES`: space-separated list of all runtime dependencies only.

For each dependency already built, the corresponding enviornment file is loaded.
This will include, apart from custom variables and the usual `PATH` and library
paths, the following specific variables (`<PACKAGE>` is the package name,
uppercased):

 - `<PACKAGE>_ROOT`: package installation directory.
 - `<PACKAGE>_VERSION`: package version.
 - `<PACKAGE>_REVISION`: package build number.
 - `<PACKAGE>_HASH`: hash of the recipe used to build the package.

