---
subtitle: Recipe reference manual
layout: main
---

1. [Recipe formats](#recipe-formats)
    1. [The header](#the-header)
    2. [The body](#the-body)
    3. [Defaults, common requirements for builds](#defaults)
2. [Relocation](#relocation)

## Recipe formats

The recipes are found in the a separate repository. The repository can be
specified via the `-c` option and defaults to _alidist_.

The recipes themselves are called `<package>.sh` where `<package>` is the name
of the package whose build recipe is described. Please note that all recipe
filenames are lowercase: _e.g._ the recipe for `ROOT` will be in `root.sh`.

The recipe itself is made up of two parts: an header, and the actual build
script, separated by three dashes (`---`) standalone.

The header is in [YAML](https://yaml.org) format and contains metadata about the
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
#!/bin/bash -ex
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
      - `%(branch_basename)s`: the name of the current alidist branch, without
        the leading `refs/heads/`.
      - `%(branch_stream)s`: in case the alidist branch ends in `-patches`, the
        name of branch without `-patches`. If the branch does not end in
        `-patches`, the `tag` field of the recipe is used.
      - `%(commit_hash)s`: if the `tag` field is a git tag, then the tag name.
        If it is a branch or raw git commit hash instead, then the raw git
        commit hash pointing to the `HEAD` of that branch, or said commit hash.
      - `%(short_hash)s`: like `%(commit_hash)s`, but cut off after 10 characters.
      - `%(tag)s`: the `tag` key specified in the recipe.
      - `%(tag_basename)s` if the `tag` resembles a path, *e.g.*
        `refs/tags/a/b/c`, returns the last part of the path, `c` in this case.
      - `%(defaults_upper)s`: if building with `release` defaults, this is the
        empty string; else, this is an underscore and then the name defaults,
        uppercased, with `-` replaced by `_`. For example, if building with
        `o2-dataflow` defaults, `%(default_upper)s` would be `_O2_DATAFLOW`.
      - `%(year)s`
      - `%(month)s`
      - `%(day)s`
      - `%(hour)s`

    Month, day and hour are zero-padded to two digits.

The following entries are optional in the header:

  - `source`: URL of a Git repository from which the source is downloaded.
    It's good practice to make sure that they are already patched, so that you
    can easily point to the actual sources used by the software.
  - `write_repo`: in case the repository URL to be used for developing is
    different from the `source`, set this key. It is used by `aliBuild init`,
    which will initialise your local repository with the `upstream` remote
    pointing at this URL instead of the one in `source`.
  - `tag`: git reference in the above mentioned repository which points to the
    software to be built. This can be a tag name, a branch name or a commit
    hash.
  - `env`: dictionary whose key-value pairs are environment variables to be set
    after the recipe is built. The values are interpreted as the contents of a
    double-quoted shell string, so you can reference other environment variables
    as `$VARIABLE`, which will be substituted each time another recipe is built.
    For example:

    ```yaml
    env:
      "$ROOTSYS": $ROOT_ROOT
    ```

    These variables **will not** be available in the recipe itself, as they are
    intended to be used to point to build products of the current recipe. If you
    need to set an environment variable for use in the recipe, use
    `export VARIABLE=value` in the recipe body.
  - `prepend_path`: dictionary whose key-value pairs are an environment variable
    name and a path to be prepended to it, as it happens in `LD_LIBRARY_PATH`.
    This happens only after the package declaring the `prepend_path` in question
    is built, so it is not available in the same recipe (just like variables
    declared using `env`). You can append multiple paths to a single variable
    by specifying a list too, *e.g.*:

    ```yaml
    prepend_path:
      "PATH": "$FOO_ROOT/binexec/foobar"
      "LD_LIBRARY_PATH": [ "$FOO_ROOT/sub/lib", "$FOO_ROOT/sub/lib64" ]
    ```

    will result in prepending `$FOO_ROOT/binexec/foobar` to `$PATH`, and both
    `$FOO_ROOT/sub/lib` and `lib64` to `LD_LIBRARY_PATH`.
  - `append_path`: same as `prepend_path` but paths are appended rather than
    prepended. Like `append_path` and `env`, this **does not** affect the
    environment of the current recipe.
  - `requires`: a list of run-time dependencies for the package, *e.g.*:

    ```yaml
    package: AliRoot
    requires:
      - ROOT
      ...
    ```

    The specified dependencies will be built before building the given package.
    You can specify platform-specific dependencies by appending `:<regexp>` to
    the dependency name. Such a regular expression will be matched against the
    architecture provided via `--architecture`, and if it does not match, the
    requirement will not be included. For instance:

    ```yaml
    package: AliRoot-test
    requires:
      - "igprof:(?!osx).*"
    ```

    will make sure that `IgProf` is only built on platforms whose name does not
    begin with `osx`.
  - `build_requires`: a list of build-time dependencies for the package. Like
    `requires`, these packages will be built before the current package is
    built.

    Packages in this list are marked specially in the dependency graph
    produced by `aliDeps`. Other tools treat these packages differently from
    `requires`: for instance, RPMs produced for a package won't depend on its
    `build_requires`, and `alibuild-generate-module` won't pull in build
    requirements' modulefiles.
  - `force_rebuild`: set it to `true` to force re-running the build recipe every
    time you invoke alibuild on it.
  - `prefer_system_check`: a script which is used to determine whether
    or not the system equivalent of the package can be used. See also
    `prefer_system`. If the `--no-system` option is specified, this key is not
    checked. The shell exit code is used to steer the build: if the check
    returns 0, the system package is used and the recipe is not run. If it
    returns non-zero, our own version of the package is built through the
    recipe.
  - `prefer_system`: a regular expression for architectures which should
    use the `prefer_system_check` by default to determine if the system version
    of the tool can be used. When the rule matches, the result of
    `prefer_system_check` determines whether to build the recipe. When the rule
    does not match, the check is skipped and the recipe is run. Using the switch
    `--always-prefer-system` runs the check always (even when the regular
    expression for the architecture does not match).
  - `relocate_paths`: a list of toplevel paths scanned recursively to perform
    relocation of executables and dynamic libraries **on macOS only**. If not
    specified, defaults to `bin`, `lib` and `lib64`.

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
 - `BUILDROOT`: it contains `BUILDDIR` and the log file for the build.
 - `SOURCEDIR`: where the sources are cloned.
 - `REQUIRES`: space-separated list of all dependencies, both runtime and build
   only.
 - `BUILD_REQUIRES`: space-separated list of all build dependencies, not needed
   at runtime.
 - `RUNTIME_REQUIRES`: space-separated list of all runtime dependencies only.

For each dependency already built, the corresponding environment file is loaded.
This will include, apart from custom variables and the usual `PATH` and library
paths, the following specific variables (`<PACKAGE>` is the package name,
uppercased):

 - `<PACKAGE>_ROOT`: package installation directory.
 - `<PACKAGE>_VERSION`: package version.
 - `<PACKAGE>_REVISION`: package build number.
 - `<PACKAGE>_HASH`: hash of the recipe used to build the package.

### Defaults

aliBuild uses a special file, called `defaults-release.sh` which will be
included as a build requires of any recipe. This is in general handy to
specify common options like `CXXFLAGS` or dependencies. It's up to the
recipe handle correctly the presence of these options.

It is also possible to specify on the command line a different set of
defaults, for example if you want to include code coverage. This is
done via the `--defaults <default-name>` option which will change the
defaults included to be `defaults-<default-name>.sh`.

An extra variable `%(defaults_upper)s` can be used to form the version
string accordingly. For example you could trigger a debug build by
adding `--defaults debug`, which will pick up `defaults-debug.sh`, and
then have:

```yaml
version: %(tag)s%(defaults_upper)s
```

in one of your recipes, which will expand to:

```yaml
version: SOME_TAG_DEBUG
```

If you want to add your own default, you should at least provide:

- `CXXFLAGS`: the `CXXFLAGS` to use
- `CFLAGS`: the `CFLAGS` to use
- `LDFLAGS`: the `LDFLAGS` to use
- `CMAKE_BUILD_TYPE`: the build type which needs to be used by cmake projects

Besides specifying extra global variables, starting from aliBuild
1.4.0, it's also possible to use defaults to override metadata of other
packages . This is done by specifying the `overrides` dictionary in the
metadata of your defaults file. For example to switch between ROOT6 and
ROOT5 you should do something like:

```yaml
...
overrides:
  ROOT:
    version: "v6-06-04"
    tag: "v6-06-04"
...
```

this will replace the `version` and `tag` metadata of `root.sh` with the
one specified in the override. Notice that is also possible to override
completely a recipe, picking it up from a given commit hash, branch or
tag in alidist. You can do so by adding such git reference after the name
of the external to override. For example:

```yaml
overrides:
  ROOT@abcedf123456:
    ...
```

will pick `root.sh` as found in the commit `abcedf123456`.

For a more complete example see
[defaults-o2.sh](https://github.com/alisw/alidist/blob/master/defaults-o2.sh).

You can limit which defaults can be applied to a given package by using the
`valid_defaults` key.

### Architecture defaults

Architecture defaults are similar to normal defaults but they are
always sourced, if available in alidist, and should never be provided on the
command line.

Their filename is always:

    defaults-<arch>.sh

where `<arch>` is the current architecture. They have precedence over normal
defaults.

## Relocation

aliBuild supports relocating binary packages so that the scratch space used for
builds (*e.g.* `/build`) and the actual installation folder (*i.e.*
`/cvmfs/alice.cern.ch`) do not need to be the same. By design this is done
automatically, and the user should not have to care about it. The procedure
takes care of relocating scripts and, on macOS, to embed the correct paths for
the dynamic libraries dependencies, so that SIP does not need to be disabled.
The internal procedure is roughly as follows:

* The build happens in `BUILD/<package>-latest/<package>` and installs
  byproducts in
  `INSTALLROOT=<work-dir>/INSTALLROOT/<package-hash>/<architecture>/<package>/<version>-<revisions>`.
  This way we know that every file which contains `<package-hash>` needs to be
  relocated.
* Once the build is completed, aliBuild looks for the above mentioned
  `<package-hash>` and generates a script in the `$INSTALLROOT/relocate-me.sh`
  which can be used to relocate the binary installation, once it has been
  unpacked.
* The path under `<work-dir>/INSTALLROOT/<package-hash>` is tarred up in a
  binary tarball.

When a tarball is installed, either because it was downloaded by aliBuild or by
some other script (*e.g.* the CVMFS publisher, the following happens:

* The tarball is expanded.
* The relocation script `relocate-me.sh` is executed with something similar to:

  ```bash
  WORK_DIR=<new-installation-workdir> relocate-me.sh
  ```

  which will take the path up to the `<package-hash>` and re-map it to the newly
  specified `WORK_DIR`.

Notice that the special variable `@@PKGREVISION@$PKGHASH@@` can be used to have
the actual revision of the package in the relocated file.

## Build environment

Before each package is built, aliBuild will populate the environment with build
related information. For a complete list of those see
[the body section](#the-body). After the build is done the user has access to
the environment of the build by sourcing the
`<work-dir>/<architecture>/<package>/<version>/etc/profile.d/init.sh` file.
For example:

```bash
WORK_DIR=<work-dir> source <work-dir>/<architecture>/<package>/<version>/etc/profile.d/init.sh
```

Notice that for development packages, we also generate a `.envrc` file in
`<work-dir>/BUILD/<package>-<version>/<package>/.envrc` which can be used to
load the build environment via [direnv](https://direnv.net), *e.g.* for easy
[IDE integration](https://aliceo2group.github.io/advanced/ides.html).

## Runtime environment

Runtime environment is usually provided via
[environment modules](https://modules.readthedocs.io/en/latest/).

While the build environment is automatically generated, it is responsibility of
the recipe to create a module file in `$INSTALLROOT/etc/modulefiles/$PKGNAME`.
For example:

```bash
# ModuleFile
mkdir -p etc/modulefiles
cat > etc/modulefiles/$PKGNAME <<EoF
#%Module1.0
proc ModulesHelp { } {
   global version
   puts stderr "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
}
set version $PKGVERSION-@@PKGREVISION@$PKGHASH@@
module-whatis "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
# Dependencies
module load BASE/1.0                                                                      \\
             ${BOOST_REVISION:+boost/$BOOST_VERSION-$BOOST_REVISION}                      \\
             ${FAIRLOGGER_REVISION:+FairLogger/$FAIRLOGGER_VERSION-$FAIRLOGGER_REVISION}  \\
             ${ZEROMQ_REVISION:+ZeroMQ/$ZEROMQ_VERSION-$ZEROMQ_REVISION}                  \\
             ${ASIOFI_REVISION:+asiofi/$ASIOFI_VERSION-$ASIOFI_REVISION}                  \\
             ${DDS_REVISION:+DDS/$DDS_VERSION-$DDS_REVISION}
# Our environment
set FAIRMQ_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
prepend-path PATH \$FAIRMQ_ROOT/bin
prepend-path LD_LIBRARY_PATH \$FAIRMQ_ROOT/lib
EoF
MODULEDIR="$INSTALLROOT/etc/modulefiles"
mkdir -p $MODULEDIR && rsync -a --delete etc/modulefiles/ $MODULEDIR
```

Please keep in mind the following recommendation when writing the modulefile:

* Do not use runtime environment variables which are usually not set by a given
  tool. For example avoid exposing `<package>_ROOT`. This is because if we build
  in a mode where system dependencies are used, we cannot rely on their
  presence.
* Use `<package>_REVISION` to guard inclusion of extra dependencies. This will
  make sure that only dependencies which were actually built via `aliBuild` will
  be included in the modulefile.

It's also now possible to generate automatically the initial part of the
modulefile, up to the `# Our environment` line, by using the
`alibuild-recipe-tools` helper scripts. In order to do this you need to add
`alibuild-recipe-tools` as a `build_requires` of your package and substitute the
module creation with:

```bash
#ModuleFile
mkdir -p etc/modulefiles
alibuild-generate-module > etc/modulefiles/$PKGNAME
mkdir -p $INSTALLROOT/etc/modulefiles && rsync -a --delete etc/modulefiles/ $INSTALLROOT/etc/modulefiles
```

One can also make sure that `PATH` and `LD_LIBRARY_PATH` are properly amended by
passing the option `--bin` and `--lib` (respectively). Or you can simply append
extra information via:

```bash
alibuild-generate-module > etc/modulefiles/$PKGNAME
cat >> etc/modulefiles/$PKGNAME <<EoF
prepend-path ROOT_INCLUDE_PATH \$PKG_ROOT/include
EoF
```
