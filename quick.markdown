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

    alibuild/aliBuild [-d] -j <jobs> build <package>

where:

- `<package>`: is the name of the package you want to build, e.g.: 
  - `AliRoot`
  - `AliPhysics`
  - `O2`
  - `ROOT`
- `-d` can be used to have verbose debug output.
- `<jobs>` is the maximum number of parallel processes to be used for building
  where possible (defaults to the number of CPUs available if omitted).

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
 

## Loading the package environment

Environment for packages built using aliBuild is managed by
[Environment Modules](http://modules.sourceforge.net). Assuming you are in the
toplevel directory containing `alibuild`, `alidist` and `sw` you can do:

    alibuild/alienv q

to list the available packages, and:

    alibuild/alienv enter VO_ALICE@PackageA::VersionA[,VO_ALICE@PackageB::VersionB...]

to enter a shell with the appropriate environment set. Note that loading a
toplevel package recursively sets the environment for all its dependencies.

You can also execute a command with the proper environment without altering the
current one. For instance:

    alibuild/alienv setenv VO_ALICE@AliRoot::latest -c aliroot -b

To see other commands consult the online manual:

    alibuild/alienv help

Environment Modules is required: the package is usually called
`environment-modules` on Linux, or simply `modules` if using Homebrew on OSX.

Note that `alienv` works exactly like the one found on CVMFS, but for local
packages built with `aliBuild`.


### Environment for packages lacking a module definition

Some packages do not have a modulefile: this usually occurs for those which are
not distributed on the Grid. If you think this is wrong feel free to submit a
[pull request](https://github.com/alisw/alidist/pulls) or
[open an issue](https://github.com/alisw/alidist/issues) to the relevant
packages.

It is still possible to load the environment by sourcing the `init.sh` file
produced for each package under the `etc/profile.d` subdirectory. For instance:

    WORK_DIR=$PWD/sw source sw/slc7_x86-64/AliRoot/v5-08-02-1/etc/profile.d/init.sh

Dependencies are automatically loaded.
