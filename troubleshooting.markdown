---
title: ALIBUILD
subtitle: Troubleshooting
layout: main
---

In case build fails you can find per-build log files under the `BUILD` directory
located in the working directory.

Assuming the working directory is `sw` (the default) and the package whose
build failed is `boost`, you will find its log under:

    sw/BUILD/boost-latest/log

Note that when running `aliBuild --debug` the output is also echoed in your
current terminal.

## Common issues

### I have an error while compiling AliPhysics / AliRoot.

Notice that in general this kind of errors are not really aliBuild
related, but they are genuine issues in either AliRoot and AliPhysics.
To get the accurate and fastest feedback, the "best practice" is to do
the following:

- Make sure you have the latest version of both AliPhysics **and** AliRoot. If
  not, update to it and rebuild. Most likely someone else has already noticed
  your problem and fixed it. aliBuild will actually remind you of doing so if
  you are using master.
- If you still have a message, read what the error log for your package
  is saying and try to extract the first error. In general you can simply
  look for the first occurrence of `***` or `error:` and try to read a few
  lines around there.
- Try to find out who modified the files with an error last. This can be done by
  cd-ing into `AliRoot` / `AliPhysics`, issuing:

      git log @{yesterday}.. -- <name-of-the-file-with-error>

  and reading who was the author of the last few commits.
- Write a message to `alice-project-analysis-task-force@cern.ch`
  explaining the error. Make sure you report the first few lines of it you
  have identified above, and to include the author of the last changes in
  the problematic file.
- Make sure you do **not** attach big log files since they will cause a
  traffic storm since the list has many participants and each one of them
  will get a copy of the attachment, even if not interested. A much better
  approach is to use a service like [CERNBox](https://cernbox.cern.ch),
  Dropbox or alikes which allow to share files by providing a link to them,
  rather than by attachment.

### What are the system prerequisites of alibuild?

In principle aliBuild should now notify you for missing required system
dependencies and complain with a clear message if that is not the case. For
example if you lack bz2 it will now tell you with the following message:

    Please install bzip2 development package on your system

Moreover it will try to reuse as much as possible from your system, so
if you have a system CMake which is compatible with the one required by
AliRoot it will also pick up your version. Failing that it will build it
for you. You can have a look at what AliRoot will do by adding the `--dry-run`
option to your build command, e.g.:

    alibuild --dry-run <additional options you might have> build AliRoot

will tell you something like:

    Using package CMake from the system as preferred choice.
    Using package libxml2 from the system as preferred choice.
    Using package SWIG from the system as preferred choice.
    Using package zlib from the system as preferred choice.
    Using package autotools from the system as preferred choice.
    Using package GSL from the system as preferred choice.
    System package boost cannot be used. Building our own copy.
    We will build packages in the following order: defaults-release AliEn-CAs GMP UUID gSOAP ApMon-CPP GEANT4 boost MPFR MonALISA-gSOAP-client cgal XRootD fastjet xalienfs AliEn-Runtime ROOT vgm GEANT3 GEANT4_VMC AliRoot

If you have a system package which you think should be used but it's not,
you can run `aliDoctor` to try to understand why that was the case (or you
can open a bug report with its output and we will look at it.

### What is PIP ? How do I install it?

[PIP](https://pip.pypa.io/en/stable/) is the de-facto standard package manager
for python. While it is usually installed by default on modern distributions,
it can happen this is not the case. If so, you can usually get it via:

    sudo yum install python-pip     # (Centos / Fedora / SLC derivatives)
    sudo dnf install python-pip     # (Fedora 22+)
    sudo apt-get install python-pip # (Ubuntu / Debian alikes)

Alternatively you can try to install it by hand by following the [instructions
here](https://pip.pypa.io/en/stable/installing/#installing-with-get-pip-py).

### AliEn broken after building with aliBuild

If you are migrating from other ALICE build instructions to use aliBuild
and you are running on OSX, it could happen that you encounter an error
of the kind:

```bash
dlopen error: dlopen(/Users/me/alice/sw/osx_x86-64/ROOT/v5-34-30-alice-1/lib/libNetx.so, 9): Library not loaded: libXrdUtils.1.dylib
  Referenced from: /Users/me/alice/sw/osx_x86-64/ROOT/v5-34-30-alice-1/lib/libNetx.so
  Reason: image not found
Load Error: Failed to load Dynamic link library /Users/me/alice/sw/osx_x86-64/ROOT/v5-34-30-alice-1/lib/libNetx.so
E-TCint::AutoLoadCallback: failure loading dependent library libNetx.so for class TAlienJDL
dlopen error: dlopen(/Users/me/alice/sw/osx_x86-64/ROOT/v5-34-30-alice-1/lib/libRAliEn.so, 9): Library not loaded: /Users/jmargutti/alice/sw/INSTALLROOT/ac18e6eaa3ed801ac1cd1e788ac08c82ffd29235/osx_x86-64/xalienfs/v1.0.14r1-1/lib/libgapiUI.4.so
  Referenced from: /Users/me/alice/sw/osx_x86-64/ROOT/v5-34-30-alice-1/lib/libRAliEn.so
  Reason: image not found
Load Error: Failed to load Dynamic link library /Users/me/alice/sw/osx_x86-64/ROOT/v5-34-30-alice-1/lib/libRAliEn.so
E-TCint::AutoLoadCallback: failure loading library libRAliEn.so for class TAlienJDL
dlopen error: dlopen(/Users/me/alice/sw/osx_x86-64/AliEn-Runtime/v2-19-le-1/lib/libgapiUI.so, 9): Library not loaded: libXrdSec.0.dylib
  Referenced from: /Users/me/alice/sw/osx_x86-64/AliEn-Runtime/v2-19-le-1/lib/libgapiUI.so
  Reason: image not found
Load Error: Failed to load Dynamic link library /Users/me/alice/sw/osx_x86-64/AliEn-Runtime/v2-19-le-1/lib/libgapiUI.so
E-P010_TAlien: Please fix your loader path environment variable to be able to load libRAliEn.so
```

This happens because the new version of AliEn compiled by aliBuild is
incompatible with the old one. You can fix this issue by doing:

1. Remove old alien token stuff from `/tmp` (e.g. `rm /tmp/gclient_env* /tmp/gclient_token* /tmp/x509*`)
2. Get a new token
3. Source `/tmp/gclient_env*` file


and trying again.

### aliBuild does not work on OSX with Python shipped with ANACONDA

If you are using ANACONDA (`which python` to verify), the old version of
aliBuild had troubles with it. Upgrading to the latest version via:

    pip install --upgrade alibuild

or by doing `git pull` should fix the issue.


### aliBuild does not pick up tool X from the sytem

By default aliBuild prefers using tools from the system whenever
possible. Examples of those tools are CMake, the GCC compiler or the
autotools suite. If this does not happen even if you have it installed
it means that aliBuild does not consider you system tool good enough to
be compatible with the one provided by the recipe. You can verify what
happens during the system tool detection by running:

    aliDoctor


### I do not have privileges and I cannot install via pip

If you do not have root privileges on your machine and `pip install alibuild`
fails, you have two options:

- If your pip supports it, you can add the `--user` flag and that will install
  alibuild in `~/.local`. I.e.:

      pip install --user alibuild

- If your pip is old or if you do not have pip at all on your system or
  you do not want to use pip for whatever reasons, you can still simply
  checkout the sources with:

      git clone https://github.com/alisw/alibuild

  and simply run alibuild by invoking `alibuild/aliBuild`.


### FastJet fails to compile on my brand new Mac

A common problem is that whenever you try to compile FastJet on a brand
new Mac (from OSX 10.11 "El Capitan") you get an error like:

    checking whether we are cross compiling... configure: error: in `/Users/me/alice/sw/BUILD/c07a643b35e78fb6e4e289bdb3d5ec7a800a702d/fastjet/fastjet':
    configure: error: cannot run C compiled programs.
    If you meant to cross compile, use `--host'.

this is symtomatic of having `SIP` protection enabled on your Mac (now
default since El Captain).

Starting from El Capitan (OS X 10.11) Apple has introduced System
Integrity Protection, also known as “rootless mode”. As explained
[here](https://dberzano.github.io/2015/10/05/el-capitan/#system_integrity_protection)
this might have an impact to library loading when you have scripts (or
applications) invoking other scripts.

While we are working on a solution to make ALICE software compliant to
this new security feature you might want to turn it off completely.

To turn SIP off:

- Reboot your Mac in Recovery Mode. That is, before OS X starts up, hold down
  Command-R and keep both keys pressed until the Apple logo appears along with
  a progress bar.
- From the Utilities menu open a Terminal.
- At the shell type: csrutil disable: a message will notify the success of your
  operation.
- Now from the  menu select Restart.

**Notice that we are not liable for any damage caused by turning System
Integrity Protection off. Do it only if you know what you are doing!**


### Environment Modules is not available for my system

On some legacy systems (for instance, Ubuntu 12.04) there is no way to install
the package `environment-modules` via a package manager. This package is
required by `alienv`, and the first time you start it you would get a message
like:

    ERROR: Environment Modules was not found on your system.
           Get it with: apt-get install environment-modules

but the suggested command does not work. In this case you need to compile it by
hand. The only requirements are a valid C compiler and the development version
of TCL 8.5.

If you are on Ubuntu 12.04 (`environment-modules` appeared from 12.10) you can
get the prerequisites with:

```bash
sudo apt-get install build-essential tcl8.5-dev
```

Download the [tarball for version 3.2.10](http://downloads.sourceforge.net/project/modules/Modules/modules-3.2.10/modules-3.2.10.tar.gz), unpack it, configure and build
it:

```bash
curl -LO http://downloads.sourceforge.net/project/modules/Modules/modules-3.2.10/modules-3.2.10.tar.gz
tar xzf modules-3.2.10.tar.gz
cd modules-3.2.10/
./configure --disable-versioning --exec-prefix=/usr/local
make && sudo make install
```

You might want to slightly change the command above to do the installation in
a user directory (specify a different prefix and do not use `sudo`).

`alienv` needs the `modulecmd` in the `$PATH` in order to work. Just fire
`alienv` right afterwards, and if you get the help screen instead of the error
above then you are set.
