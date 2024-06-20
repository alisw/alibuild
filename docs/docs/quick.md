---
subtitle: Quick Start
layout: main
---

aliBuild is a tool to simplify building and installing ALICE / ALFA
software. This is a quickstart Guide which will show you how to build
and use a package, for extended documentation please have a look at the
[user guide](user.md).

## Setting up

The tool itself is available as a standard PyPi package. You
can install it via:

    pip install alibuild

Alternatively, if you cannot use pip, you can checkout the Github repository and
use it from there:

    git clone https://github.com/alisw/alibuild.git

This will provide you the tool itself. 

In order to work you will need a set of recipes from a repository called
[alidist](https://github.com/alisw/alidist.git). On the first invokation of
`alibuild` the recipes will be downloaded and put in a `alidist` folder. 
In case you need to use a special branch / repository you can always `git clone` 
the repository yourself. By default alibuild will pickup the recipes found
in `$PWD/alidist`.

## Building a package

Once you have obtained both repository, you can trigger a build via:

    aliBuild [-d] -j <jobs> build <package>

(or alibuild/aliBuild if you are working from sources) where:

- `<package>`: is the name of the package you want to build, e.g.: 
  - `AliRoot`
  - `AliPhysics`
  - `O2`
  - `ROOT`
- `-d` can be used to have verbose debug output.
- `<jobs>` is the maximum number of parallel processes to be used for
  building where possible (defaults to the number of CPUs available if
  omitted).

If you need to modify the compile options, you can do so by looking at the
recipes in your local `alidist` folder and amend them.

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

Environment for packages built using aliBuild is managed by [Environment
Modules](http://modules.sourceforge.net) and a wrapper script called alienv.
Notice you will need the package `environment-modules` on Linux or `modules` on
macOS for the following to work.

Assuming you are in the toplevel directory containing `alibuild`, `alidist` and
`sw` you can do:

    alienv q

to list the available packages, and:

    alienv enter VO_ALICE@PackageA::VersionA[,VO_ALICE@PackageB::VersionB...]

to enter a shell with the appropriate environment set. To learn more about alienv you
can also look at the [user guide](user.md#using-the-packages-you-have-built).
