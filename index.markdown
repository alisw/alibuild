---
title: ALIBUILD
subtile: About this tool
layout: main
---

A simple build tool for ALICE experiment software and its externals. Recipes
for the externals and ALICE software are stored in
[alidist](https://github.com/alisw/alidist).

Instant gratification on your [CERN Centos 7](http://linux.web.cern.ch/linux/centos7/) machine with:

    git clone https://github.com/alisw/alibuild.git
    git clone https://github.com/alisw/alidist.git
    alibuild/aliBuild -d -a slc7_x86-64 -j 16 build AliRoot
