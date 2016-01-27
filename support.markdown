---
title: ALIBUILD
subtitle: Support
layout: main
---

In case build fails you can find per-build log files under the `BUILD` directory
located in the working directory.

Assuming the working directory is `sw` (the default) and the package whose
build failed is `boost`, you will find its log under:

    sw/BUILD/boost-latest/log

Note that when running `aliBuild --debug` the output is also echoed in your
current terminal.
