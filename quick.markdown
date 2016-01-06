---
title: ALIBUILD
subtitle: Quick Start
layout: main
---

aliBuild is a tool to simplify building and installing ALICE / ALFA software.
The tool itself if available as a github repository which can be checked out via:

    git clone https://github.com/alisw/alibuild.git

This will provide you the tool itself. In order to work you will need a set of
recipes from a repository called `alidist`:

    git clone https://github.com/alisw/alidist.git

Once you have obtained both repository, you can trigger a build via:

    alibuild/aliBuild [-d] -a <architecture> -j <jobs> build <package>

where:

- `<package>`: is the name of the package you want to build, e.g.: 
  - `AliRoot`
  - `AliPhysics`
  - `O2`
  - `ROOT`
- `<architecture>` is the platform we are building for. This can be be:
  - `slc5_x86-64`: Scientific Linux 5 and compatibles, on Intel / AMD x86-64.
  - `slc6_x86-64`: Scientific Linux 6 and compatibles, on Intel / AMD x86-64.
  - `slc7_x86-64`: CERN Centos 7 and compatibles, on Intel / AMD x86-64.
  - `ubuntu1404_x86-64`: Ubuntu 1404 and compatibles, on Intel / AMD x86-64.
  - `osx_x86-64`: OSX, on Intel / AMD x86-64.
  - `slc7_ppc64`: RHEL7 on POWER8 (LE only for now).

- `<jobs>` is the maximum number of parallel processes to be used for building
  where possible.

### Results of a build

By default (can be changed using the `-c` option) the installation of your builds
can be found in:

    sw/<architecture>/<package-name>/<package-version>-<revision>/

where:

- `<architecture>` is the same as the one passed via the `-a` option.
- `<package-name>`: is the same as the one passed as an argument.
- `<package-version>`: is the same as the one found in the related recipe in alidist.
- `<package-revision>`: is the number of times you rebuilt the same version of
  a package, using a different recipe. In general this will be 1.

For example:

    sw/slc7_x86-64/AliRoot/v5-07-01-1

we call this path "the `PACKAGE_ROOT` for package `<package>`".
 

## Modulefiles

ALICE software is loading the environment from CVMFS by means of
[Modulefiles](http://modules.sourceforge.net/). To test the environment loaded
by those modulefiles, export your working directory and architecture, then run
the `aliModules` script:

    export WORK_DIR=/path/containing/sw
    export ARCHITECTURE=slc5_x86-64
    alibuild/aliModules [module1 [module2...]]

If you do not specify any module, the list of available ones is printed. You
will enter a shell which has the environment configured by Modulefiles.

Note that you must have `modulecmd` on your system (on RedHat-based OSes it is
the `environment-modules` package).

### Environment for packages which do not have a module-file

Some packages do not have a module file as they are not directly distributed to the grid.

In that case you can use the  `init.sh` file found file for any package:
`$<PACKAGE>_ROOT/etc/profile.d/init.sh` which sets up the environment so
that it the built software can be used. In order to use it:

    WORK_DIR=$PWD/sw source sw/slc7_x86-64/AliRoot/v5-07-01-1/etc/profile.d/init.sh

this will bring in a package and all it's dependencies.
