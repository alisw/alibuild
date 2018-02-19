---
title: ALIBUILD
subtitle: O2 Dataflow build tutorial
layout: main
---

# Who should read this tutorial

This tutorial is meant to ALICE developers wanting to contribute to O2 DAQ
components, and focuses in particular on the `flpproto` package.

`flpproto` is installed and developed using the standard ALICE O2 procedures,
involving the use of aliBuild and "software recipes" telling aliBuild how to
construct the package and all its dependencies.


# Supported platforms

The majority of O2 software components support the latest and long-term support
versions of all major Linux software distributions (RHEL/CentOS, Ubuntu,
Fedora). In addition, the two most recent releases of macOS are supported.

**The official reference platform is CentOS 7**, and this guide focuses on it.
Interactive output from the aliBuild utilities, and small adjustments, will
help you in case you are using different platforms.

Note that in case of hardware-related components, such as drivers, **the only
supported platform is CentOS 7**.


# Get aliBuild

aliBuild requires Python and Git to work. **As root user**, run:

    yum install -y git python
    curl -o /tmp/get-pip.py https://bootstrap.pypa.io/get-pip.py
    python /tmp/get-pip.py
    pip install alibuild


# Get a supported compiler

The first thing to do on CentOS 7 is installing the devtoolset-6 package from
[SCL](https://www.softwarecollections.org/en/scls/rhscl/devtoolset-6/): this
contains a fully-fledged compiler and it will save you from the time required
for building our own. Note that the standard GCC compiler of CentOS 7 won't do
the job.

    yum install -y centos-release-scl
    yum-config-manager --enable rhel-server-rhscl-7-rpms
    yum install -y devtoolset-6

Now, you absolutely need to **enable the compiler on your machine**. This is
done by running in the current shell:

    source /opt/rh/devtoolset-6/enable

but its effect is temporary and only valid for your current shell. You will need
to place the line above inside your `~/.bashrc` file (or equivalent) if you want
the setting to be persistent (recommended).

    echo 'source /opt/rh/devtoolset-6/enable' >> ~/.bashrc


# Your workspace

aliBuild operations depend on your current directory. For simplicity we are
going to assume that you work under `~/alice`:

    mkdir ~/alice
    cd ~/alice
    aliBuild init flpproto@master

The command above will create in the current directory a working clone of the
flpproto source code, with the version set to current master branch. In
addition, it creates an alidist directory containing the [software
recipes](https://github.com/alisw/alidist), _i.e._ the scripts
telling aliBuild how to build packages.

Note that the `flpproto` and `alidist` directories are Git clones, and once
created they must be kept up-to-date by you - aliBuild will not download
software updates and updated recipes. You will generally not need to update the
recipes unless otherwise requested.

To update flpproto, or alidist, do what you would do with any other Git
repository:

    cd ~/alice/flpproto
    git pull

Also note that the software installation is fully self-contained. This means
that removing the `~/alice` directory will return your system to a pristine
state.


# System requirements

aliBuild is smart and tries as much as possible to avoid compiling packages, if
they can be obtained as system packages (with `yum`, or `pip`, for instance). It
will also tell you what to do to get them.

    cd ~/alice
    aliDoctor --defaults o2-dataflow flpproto

The command above will print what packages are absolutely needed but missing,
and which ones can optionally be installed as system ones. Our objective is to
install as many packages as possible to reduce compilation, and recompilation
times.

The initial list can be quite huge on a newly installed system. Messages suggest
you what packages you need to install in order to suppress errors and warnings.

For convenience, we have collected all the packages you will need on CentOS 7.
Run **as root**:

    yum install -y mysql-devel curl curl-devel python python-devel          \
                   python-pip bzip2-devel autoconf automake texinfo gettext \
                   gettext-devel libtool freetype freetype-devel libpng     \
                   libpng-devel sqlite sqlite-devel ncurses-devel           \
                   mesa-libGLU-devel libX11-devel libXpm-devel              \
                   libXext-devel libXft-devel libxml2 libxml2-devel motif   \
                   motif-devel kernel-devel pciutils-devel kmod-devel

Before proceeding with the installation of Python packages, update your
setuptools version **(as root)**:

    pip install -U setuptools

And then proceed with the missing Python packages **(as root)**:

    pip install matplotlib numpy certifi ipython==5.4.1 ipywidgets ipykernel \
                notebook metakernel pyyaml

For other platforms, please read the error messages and act accordingly. Note
that this operation has to be done once for all.

After you have correctly installed the packages above, re-run the aliDoctor
command:

    cd ~/alice
    aliDoctor --defaults o2-dataflow flpproto

If everything is correct, the following packages will be picked up from the
system:

* Python-modules
* FreeType
* Python
* libxml2
* GCC-Toolchain
* autotools

It is fine, instead, if the following packages cannot be installed from the
system but they will be built by aliBuild:

* CMake
* protobuf
* nanomsg
* ZeroMQ
* boost
* GSL

For those packages we generally need a more updated version rather than the one
supplied by the software distribution, this is why it's fine to compile them.
Note that their compilation time is negligible compared to the rest.


# Build the software

This is the simplest part and the one you are going to reiterate in case of
continued development.

    cd ~/alice
    aliBuild build flpproto --defaults o2-dataflow

Do not forget the `--defaults o2-dataflow` flag!

The first installation will take a while and will take care of building all the
dependencies. Subsequent builds will be much faster, and in particular,
dependencies will not be rebuilt.


# Using the software

To use the software you need to load the environment. First add this line to your .bashrc:

    export ALIBUILD_WORK_DIR=$HOME/alice/sw; eval "`alienv shell-helper`"

Then execute:

    alienv load flpproto/latest

It loads the environment in your *current* shell. Use the `unload` command to clean the environment.

You will also be able to open a *new* shell (you can clean the environment by just coming back
to the old shell with `exit`):

    alienv enter flpproto/latest
