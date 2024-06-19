---
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

You can install aliBuild on [Ubuntu][ubuntu], [MacOS][mac], [CentOS 7][centos7], [Alma 8][alma8], [Alma 9][alma9] and [Fedora][fedora].

[centos7]: https://alice-doc.github.io/alice-analysis-tutorial/building/prereq-centos7.html
[alma8]: https://alice-doc.github.io/alice-analysis-tutorial/building/prereq-centos8.html
[alma9]: https://alice-doc.github.io/alice-analysis-tutorial/building/prereq-alma9.html
[ubuntu]: https://alice-doc.github.io/alice-analysis-tutorial/building/prereq-ubuntu.html
[mac]: https://alice-doc.github.io/alice-analysis-tutorial/building/prereq-macos.html
[fedora]: https://alice-doc.github.io/alice-analysis-tutorial/building/prereq-fedora.html

Then, build ALICE's software with:

    git clone https://github.com/alisw/alidist.git
    aliBuild build O2Physics

For a more verbose documentation of what is happening have a look at
the [quickstart guide](quick.md). See the [user guide](user.md)
for more command line options or have a look at the [troubleshooting
pages](troubleshooting.md) for hints on how to debug build errors.
Have a look at the [reference guide](reference.md) if you want to
package your own software.

<div style="display:grid;
  grid-template-columns: repeat(3,1fr);  /* 3 columns */
  grid-template-rows: repeat(2,1fr); /* 2 rows  */
  grid-gap:50px 30px;

">
    <div><h2>Simple build recipes</h2>
      Build recipes are simple bash scripts with a YAML header. Whenever
      a dependency or a package changes only what is affected by the
      change is rebuilt.
      <br/><a href="reference.html">Read more</a>
    </div>
    <div><h2>Reuses system tools</h2>
      If desired, aliBuild will do its best to reuse what is available
      on the system, if compatible to what is found in the recipe.
      <br/><a href="user.html#controlling-which-system-packages-are-picked-up">Read more</a>
    </div>
    <div><h2>Docker support</h2>
      aliBuild allows builds to happen inside a docker container, so
      that you can develop on Mac and build on your production Linux
      platform.
      <br/><a href="user.html#running-in-docker">Read more</a>
    </div>
    <div><h2>Binary packages</h2>
      aliBuild provides the ability to reuse binary packages which were
      previously centrally built, when they match the one that would be
      built locally.
      <br/><a href="user.html#using-precompiled-packages">Read more</a>
    </div>
    <div><h2>Developer mode</h2>
      Besides building and packaging your dependencies, aliBuild
      provides you the ability to develop those via a simple git clone.
      <br/><a href="user.html#developing-packages-locally">Read more</a>
    </div>
    <div><h2>Integrates with modules</h2>
      Easily setup your work environment using `alienv`, which is based on
      standard <a href="http://modules.sourceforge.net">modulefiles</a>.
      <br/><a href="quick.html#loading-the-package-environment">Read more</a>
    </div>
</div>
