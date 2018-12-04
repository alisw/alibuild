#!/usr/bin/env python

from __future__ import print_function
from alibuild_helpers.log import debug, error, banner, info, success, warning, dieOnError
from alibuild_helpers.utilities import parseDefaults, readDefaults, getPackageList, validateDefaults, dockerStatusOutput, format
from alibuild_helpers.cmd import getStatusOutputBash, execute
from tempfile import NamedTemporaryFile
from os import remove

def doDeps(args, parser):

  # Check if we have an output file
  if not args.outgraph:
    parser.error("Specify a PDF output file with --outgraph")

  # In case we are using Docker
  dockerImage = args.dockerImage if "dockerImage" in args else ""
  if args.docker and not dockerImage:
    dockerImage = "alisw/%s-builder" % args.architecture.split("_")[0]

  # Resolve all the package parsing boilerplate
  specs = {}
  defaultsReader = lambda: readDefaults(args.configDir, args.defaults, parser.error)
  (err, overrides, taps) = parseDefaults(args.disable, defaultsReader, debug)
  (systemPackages, ownPackages, failed, validDefaults) = \
    getPackageList(packages                = [args.package],
                   specs                   = specs,
                   configDir               = args.configDir,
                   preferSystem            = args.preferSystem,
                   noSystem                = args.noSystem,
                   architecture            = args.architecture,
                   disable                 = args.disable,
                   defaults                = args.defaults,
                   dieOnError              = dieOnError,
                   performPreferCheck      = lambda pkg, cmd : dockerStatusOutput(cmd, dockerImage, executor = getStatusOutputBash),
                   performRequirementCheck = lambda pkg, cmd : dockerStatusOutput(cmd, dockerImage, executor = getStatusOutputBash),
                   performValidateDefaults = lambda spec : validateDefaults(spec, args.defaults),
                   overrides               = overrides,
                   taps                    = taps,
                   log                     = debug)
  dieOnError(validDefaults and args.defaults not in validDefaults,
             "Specified default `%s' is not compatible with the packages you want to build.\n" % args.defaults +
             "Valid defaults:\n\n- " +
             "\n- ".join(sorted(validDefaults)))

  for s in specs.values():
    # Remove disabled packages
    s["requires"] = [r for r in s["requires"] if not r in args.disable and r != "defaults-release"]
    s["build_requires"] = [r for r in s["build_requires"] if not r in args.disable and r != "defaults-release"]
    s["runtime_requires"] = [r for r in s["runtime_requires"] if not r in args.disable and r != "defaults-release"]

  # Determine which pacakages are only build/runtime dependencies
  all_build   = set()
  all_runtime = set()
  for k,spec in specs.items():
    all_build.update(spec["build_requires"])
    all_runtime.update(spec["runtime_requires"])
  all_both = all_build.intersection(all_runtime)

  dot = "digraph {\n"
  for k,spec in specs.items():
    if k == "defaults-release":
      continue

    # Determine node color based on its dependency status
    color = None
    if k in all_both:
      color = "tomato1"
    elif k in all_runtime:
      color = "greenyellow"
    elif k in all_build:
      color = "plum"
    elif k == args.package:
      color = "gold"
    else:
      assert color, "This should not happen (happened for %s)" % k

    # Node definition
    dot += '"%s" [shape=box, style="rounded,filled", fontname="helvetica", fillcolor=%s]\n' % (k,color)

    # Connections (different whether it's a build dependency or a runtime one)
    for dep in spec["build_requires"]:
     dot += '"%s" -> "%s" [color=grey70]\n' % (k, dep)
    for dep in spec["runtime_requires"]:
     dot += '"%s" -> "%s" [color=dodgerblue3]\n' % (k, dep)

  dot += "}\n"

  if args.outdot:
    fp = open(args.outdot, "wt")
  else:
    fp = NamedTemporaryFile(delete=False, mode="wt")
  fp.write(dot)
  fp.close()

  try:
    if args.neat:
      execute(format("tred %(dotFile)s > %(dotFile)s.0 && mv %(dotFile)s.0 %(dotFile)s",
              dotFile=fp.name))
    execute(["dot", fp.name, "-Tpdf", "-o", args.outgraph])
  except Exception as e:
    error(format("Error generating dependencies with dot: %(type)s: %(msg)s",
                 type=type(e).__name__, msg=str(e)))
  else:
    info("Dependencies graph generated: %s" % args.outgraph)
  if fp.name != args.outdot:
    remove(fp.name)
  else:
    info("Intermediate dot file for Graphviz saved: %s" % args.outdot)
  return True
