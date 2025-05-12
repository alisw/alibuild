---
subtitle: Quick Start
layout: main
---

Bits is a tool to build, install and package large software stacks. It originates from the aliBuild tool, originally developed to simplify building and installing ALICE / ALFA software and attempts to make it more general and usable for other communities that share similar problems and have overlapping dependencies.

This is a quickstart Guide which will show you how to build
and use a package, for extended documentation please have a look at the
[user guide](user.md).

## Setting up

The tool itself is available as a standard PyPi package. You
can install it via:

    pip install bits

Alternatively, if you cannot use pip, you can checkout the Github repository and
use it from there:

    git clone https://github.com/bitsorg/bits.git

This will provide you the tool itself. 

In order to work, you will need a set of recipes from a repository called
[common.bits, hep.bits, alice.bits. fair.bits,..](see https://github.com/orgs/bitsorg/repositories). The recipes will be downloaded and put in a `repositories` folder on the first invocation of' bits'.
If you need to use a particular branch / repository you can always `git clone` the repository yourself. By default `bits` will look for the recipes found in `$PWD/repositories` folder.

## Building a package

Once you have obtained both repository, you can trigger a build via:

    bits [-d] -j <jobs> build <package>

where:

- `<package>`: is the name of the package you want to build, e.g.: 
  - `GEANT4`
  - `ROOT`
- `-d` can be used to have verbose debug output.
- `<jobs>` is the maximum number of parallel processes to be used for
  building where possible (defaults to the number of CPUs available if
  omitted).

If you need to modify the compile options, you can do so by looking at the
recipes in your local `bits` folder and amend them.

## Results of a build

By default (can be changed using the `-c` option) the installation of your builds
can be found in:

    sw/<architecture>/<package-name>/<package-version>-<revision>/

where:

- `<architecture>` is the same as the one passed via the `-a` option.
- `<package-name>`: is the same as the one passed as an argument.
- `<package-version>`: is the same as the one found in the related recipe in alidist.
- `<package-revision>`: is the number of times you rebuilt the same version of
  a package, using a different recipe. In general this will be 1.

For example, on Centos7:

    sw/slc7_x86-64/AliRoot/v6-16-01-1

## Using the built package

Environment for packages built using bits is managed by [Environment
Modules](http://modules.sourceforge.net). Notice you will need the package
`environment-modules` on Linux or `modules` on macOS for the following to work.

Assuming you are in the toplevel directory containing `bits`, `repositories` and
`sw` you can do:

    bits q

to list the available packages, and:

    bits enter [VO_ALICE@]PackageA::VersionA[,[VO_ALICE@]PackageB::VersionB...]

to enter a shell with the appropriate environment set. To learn more about `bits` you
can also look at the [user guide](user.md#using-the-packages-you-have-built).
