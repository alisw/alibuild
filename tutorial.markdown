---
title: ALIBUILD
subtitle: Basic tutorial
layout: main
---

# Who should read this tutorial

This tutorial is thought for [ALICE experiment](http://cern.ch/alice)
physicists who want to setup their working environment quickly.

It covers only the simplest use case of:

  - Installing aliBuild and preparing the build environment
  - Getting the latest version of AliRoot and AliPhysics
  - Developing AliRoot and AliPhysics
  - Setting up the environment so that you can use your local installation

This is meant for people developing a single feature at the time, using
the master branch of both AliRoot and AliPhysics, on their laptop.

For all other kind of workflows, using more than one
version of AliRoot or AliPhysics, using ROOT6 than it's
reccomended you look at the beautiful, advanced, [tutorial by
Dario](https://dberzano.github.io/alice/alibuild).

Depending on how powerful your laptop is, the first build should take
between 30 minutes and 1 hour, subsequent builds will be incremental
and should take between 20 seconds and a few minutes, assuming you are
changing something which does not involve a lot of recompilation.

# aliBuild installation

aliBuild is installed via pip, the Python package manager. This procedure
needs to be done only once.

On most laptops (in particular Macs) this means running:

    pip install alibuild

or, in case you need to be root to install packages (e.g. on Ubuntu and
other Linux distributions):

    sudo pip install alibuild

If you are on a system where you do not have enough privileges
to install packages, you can also [install it in your home
directory](troubleshooting.html#i-do-not-have-privileges-and-i-cannot-in
stall-via-pip). If you do not have pip on your system you
can install it following the [guide in the troubleshooting
section](troubleshooting.html#what-is-pip--how-do-i-install-it).

# Setting up your work environment

We will now setup your work environment. This procedure needs to be done
only once.

First of all, you should decide where you want to keep your workarea. A good
default choice is something like `$HOME/alice`.

If the directory does not exists, you can then create it with:

    mkdir -p $HOME/alice

You can then cd into it and get a copy of `AliRoot`, `AliPhysics`. This
can be done by hand, but you will probably find it handy to use the
`aliBuild init` command:

```bash
cd $HOME/alice
aliBuild init AliRoot,AliPhysics
```

Once the above command returns, you should have a copy of the current
master of `AliRoot` and `AliPhysics` in `$HOME/alice` which you can
modify at will.

Moreover you will have an `alidist` folder which contains the recipes
used by aliBuild to actually build the software. While you do not need
to know about these you can find more information in the [aliBuild
reference guide](reference.html).

# Checking the system setup

Before we actually tell aliBuild to build your software, it's good
practice to check that everything on our machine is in order and that
we can pick up as many of the externals as possible from the system,
so that aliBuild will not need to build them. Also this part can be
done only once, however it is safe to repeat it whenever you have
installation troubles and include it in your bug report.

To do so you can go in `$HOME/alice` and invoke

    cd $HOME/alice
    aliDoctor AliPhysics

This will examine your system and provide suggestions (in the form of
warnings) or actual errors about your setup. You should fix all the
errors before continuing and you should try to cleanup all the warnings
as that will improve aliBuild performance by reusing system tools.
Notice however that this is not always possible: for example the version
of boost available on Ubuntu is not new enough to compile FastJet, so in
that case you will have to let aliBuild do it for you. On the other hand
it's in general good practice to have at least CMake and autotools come
from the system so do your best to cleanup at least those warnings.

# Building AliRoot and AliPhysics

Once you have your area setup, you can start the build of the software via
`aliBuild`.

    cd $HOME/alice
    aliBuild build AliPhysics

Notice that aliBuild automatically takes care of dependencies, so you
only need to specify the toplevel package.

Depending on your setup, this should take between 30 minutes to 1 hour
on reasonably modern hardware. If it takes more, you might want to read
again the previous step and try to fix more warnings.

Once the build is completed you should get a message and you should be back
at the prompt. You should have AliPhysics installed in:

    sw/<architecture>/AliPhysics/latest

where architecture is a string identifying your OS, most likely
`osx_x86-64` if you are running on Mac or `ubuntu1404_x86-64` if you are
on the Long Term Support Ubuntu 14.04.

Notice that while you can use the

    aliBuild build AliPhysics

command as many times as you want. However, you can also do it just once
and then do subsequent rebuilds by doing:

    cd sw/BUILD/AliPhysics-latest/AliPhysics

and then invoking by hand:

    make -j10 install

as you would normally do without aliBuild. This means you can simply use
`aliBuild` to setup your area once and then build by hand. This approach
has the advantage of being slightly faster under normal conditions. The
`-j10` option simply specifies how many parallel processes should be
used for the build. This should be roughly twice the amount of available
cores on your machine and `-j10` is a reasonably safe default on modern
hardware.

# Setting up the environment and using the builds

Once you have a complete installation of AliPhysics, you can use it by
doing:

    eval $(alienv load AliPhysics/latest)

This will setup your environment so that `aliroot` and all the required
libraries are correctly picked up.

Alternatively you can use:

    alienv enter AliPhysics/latest

to launch a new shell which will have the correct environment.
