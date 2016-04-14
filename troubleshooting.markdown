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

## Common issues:

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

### aliBuild does not work with python shipped with ANACONDA

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

### Fastjet fails to compile on my brand new Mac

A common problem is that whenever you try to compile FastJet on a brand
new mac you get an error like:

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

