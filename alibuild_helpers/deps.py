#!/usr/bin/env python

from __future__ import print_function
from glob import glob
from tempfile import NamedTemporaryFile
import os, sys
from alibuild_helpers.log import debug, error, info
from os import remove
from alibuild_helpers.utilities import format
from alibuild_helpers.cmd import execute
from alibuild_helpers.utilities import detectArch
from alibuild_helpers.utilities import parseRecipe, getRecipeReader

def deps(recipesDir, topPackage, outFile, buildRequires, transitiveRed, disable):
  dot = {}
  keys = [ "requires" ]
  if buildRequires:
    keys.append("build_requires")
  for p in glob("%s/*.sh" % recipesDir):
    debug(format("Reading file %(filename)s", filename=p))
    try:
      err, recipe, _ = parseRecipe(getRecipeReader(p))
      name = recipe["package"]
      if name in disable:
        debug("Ignoring %s, disabled explicitly" % name)
        continue
    except Exception as e:
      error(format("Error reading recipe %(filename)s: %(type)s: %(msg)s",
                   filename=p, type=type(e).__name__, msg=str(e)))
      sys.exit(1)
    dot[name] = dot.get(name, [])
    for k in keys:
      for d in recipe.get(k, []):
        d = d.split(":")[0]
        d in disable or dot[name].append(d)

  selected = None
  if topPackage != "all":
    if not topPackage in dot:
      error(format("Package %(topPackage)s does not exist", topPackage=topPackage))
      return False
    selected = [ topPackage ]
    olen = 0
    while len(selected) != olen:
      olen = len(selected)
      selected += [ x
                    for s in selected if s in dot
                    for x in dot[s] if not x in selected ]
    selected.sort()

  result = "digraph {\n"
  for p,deps in list(dot.items()):
    if selected and not p in selected: continue
    result += "  \"%s\";\n" % p
    for d in deps:
      result += "  \"%s\" -> \"%s\";\n" % (p,d)
  result += "}\n"

  with NamedTemporaryFile(delete=False) as fp:
    fp.write(result)
  try:
    if transitiveRed:
      execute(format("tred %(dotFile)s > %(dotFile)s.0 && mv %(dotFile)s.0 %(dotFile)s",
              dotFile=fp.name))
    execute(["dot", fp.name, "-Tpdf", "-o", outFile])
  except Exception as e:
    error(format("Error generating dependencies with dot: %(type)s: %(msg)s",
                 type=type(e).__name__, msg=str(e)))
  else:
    info(format("Dependencies graph generated: %(outFile)s", outFile=outFile))
  remove(fp.name)
  return True

def depsArgsParser(parser):
  parser.add_argument("topPackage")
  parser.add_argument("-a", "--architecture", help="force architecture",
                      dest="architecture", default=detectArch())
  parser.add_argument("--dist", dest="distDir", default="alidist",
                      help="Recipes directory")
  parser.add_argument("--output-file", "-o", dest="outFile", default="dist.pdf",
                      help="Output file (PDF format)")
  parser.add_argument("--debug", "-d", dest="debug", action="store_true", default=False,
                      help="Debug output")
  parser.add_argument("--build-requires", "-b", dest="buildRequires", action="store_true",
                      default=False, help="Debug output")
  parser.add_argument("--neat", dest="neat", action="store_true", default=False,
                      help="Neat graph with transitive reduction")
  parser.add_argument("--disable", dest="disable", default=[],
                      help="List of packages to ignore")
  parser.add_argument("--chdir", "-C", help="Change to the specified directory first",
                      metavar="DIR", dest="chdir", default=os.environ.get("ALIBUILD_CHDIR", "."))
  return parser
