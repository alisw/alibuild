#!/usr/bin/env python3

from alibuild_helpers.log import debug, error, info, dieOnError
from alibuild_helpers.utilities import parseDefaults, readDefaults, getPackageList, validateDefaults
from alibuild_helpers.cmd import DockerRunner, execute
from tempfile import NamedTemporaryFile
from os import remove, path

def doDeps(args, parser):

  # Check if we have an output file
  if not args.outgraph:
    parser.error("Specify a PDF output file with --outgraph")

  # Resolve all the package parsing boilerplate
  specs = {}
  defaultsReader = lambda: readDefaults(args.configDir, args.defaults, parser.error, args.architecture)
  (err, overrides, taps) = parseDefaults(args.disable, defaultsReader, debug)

  extra_env = {"ALIBUILD_CONFIG_DIR": "/alidist" if args.docker else path.abspath(args.configDir)}
  extra_env.update(dict([e.partition('=')[::2] for e in args.environment]))
  
  with DockerRunner(args.dockerImage, args.docker_extra_args, extra_env=extra_env, extra_volumes=[f"{path.abspath(args.configDir)}:/alidist:ro"] if args.docker else []) as getstatusoutput_docker:
    def performCheck(pkg, cmd):
      return getstatusoutput_docker(cmd)
    
    systemPackages, ownPackages, failed, validDefaults = \
      getPackageList(packages                = [args.package],
                     specs                   = specs,
                     configDir               = args.configDir,
                     preferSystem            = args.preferSystem,
                     noSystem                = args.noSystem,
                     architecture            = args.architecture,
                     disable                 = args.disable,
                     defaults                = args.defaults,
                     performPreferCheck      = performCheck,
                     performRequirementCheck = performCheck,
                     performValidateDefaults = lambda spec: validateDefaults(spec, args.defaults),
                     overrides               = overrides,
                     taps                    = taps,
                     log                     = debug)

  dieOnError(validDefaults and args.defaults not in validDefaults,
             "Specified default `%s' is not compatible with the packages you want to build.\n" % args.defaults +
             "Valid defaults:\n\n- " +
             "\n- ".join(sorted(validDefaults)))

  for s in specs.values():
    # Remove disabled packages
    s["requires"] = [r for r in s["requires"] if r not in args.disable and r != "defaults-release"]
    s["build_requires"] = [r for r in s["build_requires"] if r not in args.disable and r != "defaults-release"]
    s["runtime_requires"] = [r for r in s["runtime_requires"] if r not in args.disable and r != "defaults-release"]

  # Determine which packages are only build/runtime dependencies
  all_build   = set()
  all_runtime = set()
  for k,spec in specs.items():
    all_build.update(spec["build_requires"])
    all_runtime.update(spec["runtime_requires"])
  all_both = all_build.intersection(all_runtime)

  dot = "digraph {\n"
  dot += "ratio=\"0.52\"\n"
  dot += 'graph [nodesep=0.25, ranksep=0.2];\n'
  dot += 'node [width=1.5, height=1, fonsize=46, margin=0.1];\n'
  dot += 'edge [penwidth=2];\n'

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

  # Check if we have dot in PATH
  try:
    execute(["dot", "-V"])
  except Exception:
    dieOnError(True, "Could not find dot in PATH. Please install graphviz and add it to PATH.")
  try:
    if args.neat:
      execute("tred {dotFile} > {dotFile}.0 && mv {dotFile}.0 {dotFile}".format(dotFile=fp.name))
    execute(["dot", fp.name, "-Tpdf", "-o", args.outgraph])
  except Exception as e:
    error("Error generating dependencies with dot: %s: %s", type(e).__name__, e)
  else:
    info("Dependencies graph generated: %s" % args.outgraph)
  if fp.name != args.outdot:
    remove(fp.name)
  else:
    info("Intermediate dot file for Graphviz saved: %s" % args.outdot)
  return True
