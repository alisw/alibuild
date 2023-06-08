---
title: ALIBUILD
subtile: About this tool
layout: main
---

<div style="text-align:center;width:100%">
  <a href="https://badge.fury.io/py/alibuild"><img src="https://badge.fury.io/py/alibuild.svg" alt="PyPI version" height="22"></a>
  <a href="https://github.com/alisw/alibuild/actions/workflows/pr-check.yml"><img src="https://github.com/alisw/alibuild/actions/workflows/pr-check.yml/badge.svg?branch=master&event=push" alt="Build status" height="22"></a>
</div>

A simple build tool for ALICE experiment software and its externals. Recipes
for the externals and ALICE software are stored in
[alidist](https://github.com/alisw/alidist).

Install with:

    pip install alibuild

On macOS you can also install with:

    brew tap alisw/system-deps
    brew install alisw/system-deps/alibuild

Instant gratification on your machine with:

    git clone https://github.com/alisw/alidist.git
    aliBuild build AliRoot

For a more verbose documentation of what is happening have a look at
the [quickstart guide](quick.html). See the [user guide](user.html)
for more command line options or have a look at the [troubleshooting
pages](troubleshooting.html) for hints on how to debug build errors.
Have a look at the [reference guide](reference.html) if you want to
package your own software.

<div class="pure-g">
    <div class="pure-u-1-3"><h3>Simple build recipes</h3>
      Build recipes are simple bash scripts with a YAML header. Whenever
      a dependency or a package changes only what is affected by the
      change is rebuilt.
      <br/><a href="reference.html">Read more</a>
    </div>
    <div class="pure-u-1-3"><h3>Reuses system tools</h3>
      If desired, aliBuild will do its best to reuse what is available
      on the system, if compatible to what is found in the recipe.
      <br/><a href="user.html#controlling-which-system-packages-are-picked-up">Read more</a>
    </div>
    <div class="pure-u-1-3"><h3>Docker support</h3>
      aliBuild allows builds to happen inside a docker container, so
      that you can develop on Mac and build on your production Linux
      platform.
      <br/><a href="user.html#running-in-docker">Read more</a>
    </div>
</div>
<div class="pure-g">
    <div class="pure-u-1-3"><h3>Binary packages</h3>
      aliBuild provides the ability to reuse binary packages which were
      previously centrally built, when they match the one that would be
      built locally.
      <br/><a href="user.html#using-precompiled-packages">Read more</a>
    </div>
    <div class="pure-u-1-3"><h3>Developer mode</h3>
      Besides building and packaging your dependencies, aliBuild
      provides you the ability to develop those via a simple git clone.
      <br/><a href="user.html#developing-packages-locally">Read more</a>
    </div>
    <div class="pure-u-1-3"><h3>Integrates with modules</h3>
      Easily setup your work environment using `alienv`, which is based on
      standard <a href="http://modules.sourceforge.net">modulefiles</a>.
      <br/><a href="quick.html#loading-the-package-environment">Read more</a>
    </div>
</div>
