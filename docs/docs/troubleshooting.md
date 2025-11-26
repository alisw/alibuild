---
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

If you have a system package which you think should be used but it's not, you
can run `aliBuild doctor <package-name>` to try to understand why that was the
case (or you can [open a bug report](https://github.com/alisw/alidist/issues)
with its output and we will look at it).

### What is PIP ? How do I install it?

[PIP](https://pip.pypa.io/en/stable/) is the de-facto standard package manager
for python. While it is usually installed by default on modern distributions,
it can happen this is not the case. If so, you can usually get it via:

    sudo yum install python-pip     # (Centos / Fedora / SLC derivatives)
    sudo dnf install python-pip     # (Fedora 22+)
    sudo apt-get install python-pip # (Ubuntu / Debian alikes)

Alternatively you can try to install it by hand by following the [instructions
here](https://pip.pypa.io/en/stable/installation/#supported-methods).

### Package branch was updated, but aliBuild does not rebuild it

Some recipes specify branches in the `tag:` field instead of an actual tag. For
such recipes, aliBuild must contact remote servers in order to determine what is
the latest commit for that branch. Since this is a corner case and the operation
is expensive and slow, it is off by default, and cached information is used
instead. Try to ask aliBuild to update its cached information by using the `-u`
or `--fetch-repos` switch.


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


### aliBuild does not pick up tool X from the system

By default aliBuild prefers using tools from the system whenever
possible. Examples of those tools are CMake, the GCC compiler or the
autotools suite. If this does not happen even if you have it installed
it means that aliBuild does not consider you system tool good enough to
be compatible with the one provided by the recipe. You can verify what
happens during the system tool detection by running:

    aliBuild doctor <package name>


### AliBuild fails with `cannot open file "AvailabilityMacros.h`

If your build fails with:

```
Error: cannot open file "AvailabilityMacros.h" sw/BUILD/.../ROOT/include/RConfig.h:384:
```

and you are on macOS, this most likely means you have an incomplete XCode installation,
e.g. due to an upgrade. You can fix this with:

```
xcode-select --install
```

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

### I am changing an uncommitted file in a development package, but it is not updated in the installation folder.

If you add a file to a development package and the build recipe is
able to handle uncommitted files, it will be copied the first time.

However alibuild considers any untracked file as the same, and therefore unless
the file is added or committed to the local clone of the development package any
subsequent rebuild will ignore the changes. This can be worked around in two ways:

1. You add the file to your local clone via git add / git commit
2. You add an incremental_recipe which is able to handle uncommitted files

What 1. does is to make alibuild aware of the changes of the new file, so you
will get a new build for each change to the file. What 2. does is to always
execute the incremental recipe to refresh the installation folder on each aliBuild
invocation, possibly updating untracked files if so specified in the recipe itself.

### How do I set compilation options for AliRoot and / or AliPhysics?

If you want to change the compilation options for AliRoot, AliPhysics,
or as a matter of fact any packages you have two options:

- If the package itself is one which you are developing locally, i.e.
  you have the checkout available, you can modify its CMakeFile, add
  whatever options you like there and then issue again your aliBuild
  command.
- On contrary, if you do not have a local checkout but you still want to
  modify it's compiler flags, you can edit the `alidist/aliroot.sh` recipe
  and add the options there.

Finally, for certain common options, e.g. debug flags, we provide a
precooked configuration using so called [defaults](user.md#defaults).
Simply add `--defaults debug` to your aliBuild flags and it will add
debug flags to all your packages.

### AliPhysics takes very long time to build and builds things like autotools, GCC

In order to build AliPhysics, a number of externals are required,
including working autotools, boost, and GCC. While aliBuild tries it
best to reuse whatever comes from the system, it will not complain when
building unless one of the system dependencies is absolutely required
(e.g. X11, perl). This might lead to the fact it will rebuild large
tool, where simply installing them might be a better option. For this
reason we suggest that users run:

    aliBuild doctor AliPhysics

in the same path where their `alidist` folder is, before actually
starting to build, so that they can get an overview of what will be
picked up from the system and what not.

Notice that if you change (either add or remove) your set of system
dependencies, aliBuild will trigger a rebuild of whatever depends on
them, taking additional time, so make sure you do this when not pressed
for a deadline.

### Permission denied when running alienv on shared (farm) installations

When attempting to do `alienv` operations on shared (farm) installations you
might get a number of `Permission denied` errors. In order to fix this problem
you need to make sure that shared builds with `aliBuild` are always made by the
same user. In addition after every `aliBuild` run the person who has run it has
to run the following command in order to generate all the correct modulefiles
as seen by the users:

    alienv q

Users have to append the `--no-refresh` option to every `alienv` operation, for
instance:

    alienv --no-refresh enter AliPhysics/latest

Note that the `--no-refresh` option is not necessary anymore starting from
`v1.4.0.rc1`.

### Building on Windows Ubuntu environment does not work

At the time of writing, neither Windows native nor the Ubuntu environment 
on Windows are supported and most likely this will stay the same unless some
third party does the work and provides a pull request.

### Can I build on an unsupported architecture?

You can try, but of course your mileage might vary. In case the architecture is similar to one of the supported ones (e.g. Ubuntu and Kubuntu) this should be recognized automatically and the build should proceed, attempting to use the supported one. This will still not guarantee things will not break for some packages.

In case the architecture is completely unknown to us, you will get a message:

```
ERROR: Cannot autodetect architecture
```

if you still want to try, you can use the `--force-unknown-architecture` option and while we strive our best to help you out also in this case, sometimes priorities force us to simply ignore support requests.

### How do I run on a system where I do not have global install rights?

If you want to run on a system where you do not have global install rights, and
the PyYAML package is not installed (e.g. lxplus), you can still do so by using
the `--user` flag when you install with `pip`. This will install alibuild under
`~/.local/bin`.

This means that you need to do (only once):

    pip install --user --upgrade alibuild

and then adapt you PATH to pickup the local installation, e.g. via:

    export PATH=~/.local/bin:$PATH


### aliBuild keeps asking for my password

Some packages you may need to build have their source code in a protected repository on CERN GitLab.
This means that you may be asked for a username and password when you run `aliBuild build`.
See below for ways to avoid being prompted too often.

#### SSH authentication

You can use an SSH key to authenticate with CERN GitLab.
This way, you will not be prompted for your GitLab password at all.
To do this, find your public key (this usually lives in `~/.ssh/id_rsa.pub`) and copy the contents of the file into [your user settings on CERN GitLab][gitlab-ssh-key].
If you have no SSH key, you can generate one using the `ssh-keygen` command.
Then, configure git to use SSH to authenticate with CERN GitLab using the following command:

```bash
git config --global 'url.ssh://git@gitlab.cern.ch:7999/.insteadof' 'https://gitlab.cern.ch/'
```

[gitlab-ssh-key]: https://gitlab.cern.ch/-/user_settings/ssh_keys

#### Caching passwords

If you prefer not to use SSH keys as described above, you can alternatively configure git to remember the passwords you input for a short time (such as a few hours).
In order to do this, run the command below (which remembers your passwords for an hour each time you type them into git).

```bash
git config --global credential.helper 'cache --timeout 3600'
```

You can adjust the timeout (3600 seconds, above) to your liking, if you would prefer git to remember your passwords for longer.

#### I get an HTTP/2 related error

Some network provider do not support HTTP/2 apparently. If you get:

```bash
error: RPC failed; curl 92 HTTP/2 stream 5 was not closed cleanly: CANCEL (err 8)
```

or similar message, try to disable HTTP/2 with something like:

```
git config --global http.version HTTP/1.1
```
