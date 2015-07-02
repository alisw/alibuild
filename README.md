# aliBuild

A simple build tool for ALICE experiment software and its externals.

# Format of the recipes

The recipes are found in the a separate repository. The repository 
can be specified via the `-c` option and defaults to alidist.

The recipes themselves are called `<package>.sh` where `<package>` is the name of
the package whose build recipe is described, e.g. `root`.

The recipe itself is made up of two parts: an header, and the actual build
script, separated by three dashes (`---`) standalone.

The header is in [YAML](http://yaml.org) format and contains metadata about the
package, like it's name, it's version and where to find the sources.

The build script is a standard build script which is invoked by the tool to
perform the build itself. A few environment variable can be expected to be
defined when the script is invoked.

An example recipe for `zlib` is the following:

```
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

  - `source`: url of a git repository from which the sources should be fetch
    from.  Notice it's a good practice to make sure that they are already
    patched, so that you can easily point to the actual sources used by the
    software.
  - `tag`: tag in the above mentioned repository which points to the software
    to be built.
  - `env`: list of one entry dictionaries whose key-value pairs are
    an environment variables name and value to be set. E.g.:

        env:
        - "$ROOTSYS": $ROOT_ROOT

  - `prepend_path`: list of one entry dictionaries whose key-value pairs are
    an environment variable name and a path to be appended to it, like it
    happens in `LD_LIBRARY_PATH`. E.g:

        prepend_path:
          - "PATH": "$FOO_ROOT/binexec/foobar"

    will result in prepending `$FOO_ROOT/binexec/foobar` to $PATH
  - `append_path`: same as `prepend_path`, paths are appended rather than
    prepended.

### The body

The following variables can be expected to be defined and can be used in
your evironment.

- `<PACKAGE>_ROOT`: where <PACKAGE> is the upper name of the package, as
  defined in the `name` field in the header.
- `<PACKAGE>_VERSION`: the version of the package, as defined in the `version`
  field.
- `INSTALLROOT`: the path to use as installation path, e.g. what you pass via 
  `--prefix` to configure or via `-DCMAKE_INSTALL_PREFIX` to cmake.
- `JOBS`: the number of jobs specified via the command line option `-j`.

moreover given the closure of all the dependencies of a package (i.e. direct
and indirect ones) you will get `<DEPENDENCIES>_ROOT` and
`<DEPENDENCIES>_VERSION` which you can use to drive the build.


### The environment file

In every package you can find an environment file in
`$<PACKAGE>_ROOT/etc/profile.d/init.sh` which sets up the environment so that
it the built software can be used.
