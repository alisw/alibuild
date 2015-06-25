# \*Build

A simple build tool for HEP experiment software.

Depending on how you call it, the prefix is used to decide defaults. For
example if you invoke it as "aliBuild" you will end up with ALICE defaults.

# Format of the recipes

The recipes are found in the a separate repository. The repository 
can be specified via the `-c` option and defaults to \*dist where \* is the
usual per experiment prefix.

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
  - `source`:
  - tag:
