# aliBuild

A simple build tool for ALICE experiment software and its externals.


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
  - `version`: a mnemonic

The following entries are optional in the header:

  - `source`: URL of a Git repository from which the source is downloaded.
    Notice it's good practice to make sure that they are already patched, so
    that you can easily point to the actual sources used by the software.
  - `tag`: tag in the above mentioned repository which points to the software
    to be built.
  - `env`: list of one entry dictionaries whose key-value pairs are environment
    variables name and value to be set, *e.g.*:

        env:
          - "$ROOTSYS": $ROOT_ROOT

  - `prepend_path`: list of one entry dictionaries whose key-value pairs are
    an environment variable name and a path to be appended to it, like it
    happens in `LD_LIBRARY_PATH`, *e.g*:

        prepend_path:
          - "PATH": "$FOO_ROOT/binexec/foobar"

    will result in prepending `$FOO_ROOT/binexec/foobar` to `$PATH`
  - `append_path`: same as `prepend_path`, paths are appended rather than
    prepended.


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
 - `SOURCEDIR`: TODO

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
