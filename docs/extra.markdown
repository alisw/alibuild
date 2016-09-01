---
title: ALIBUILD
subtitle: Extra tools
layout: main
---

## Dependency graph

Assuming you are in a directory containing `alibuild` and `alidist`, you can
generate a dependency plot with:

    alibuild/aliDeps

A file named `dist.pdf` will be created. `dot` from Graphviz is required. To
show all the dependencies recursively from a specific package (for instance,
`O2`) use:

    alibuild/aliDeps O2

which will produce something like:

![drawing](deps.png)

Use `-h` or `--help` for more options.

