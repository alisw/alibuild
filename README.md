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
