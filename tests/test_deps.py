from __future__ import print_function
try:
  from unittest.mock import patch, call, MagicMock  # In Python 3, mock is built-in
  from io import StringIO
except ImportError:
  from mock import patch, call, MagicMock  # Python 2
  from StringIO import StringIO
try:
  from collections import OrderedDict
except ImportError:
  from ordereddict import OrderedDict

from alibuild_helpers.deps import doDeps
from argparse import Namespace
import unittest

RECIPE_DEFAULTS_RELEASE = """package: defaults-release
version: v1
---
"""

RECIPE_ALIROOT = """package: AliRoot
version: v1
requires:
  - ROOT
  - GCC-Toolchain
---
"""

RECIPE_ROOT = """package: ROOT
version: v1
build_requires:
  - GCC-Toolchain
---
"""

RECIPE_GCC_TOOLCHAIN = """package: GCC-Toolchain
version: v1
---
"""

class DepsTestCase(unittest.TestCase):

  @patch("alibuild_helpers.deps.open")
  @patch("alibuild_helpers.deps.execute")
  @patch("alibuild_helpers.utilities.open")
  def test_deps(self, mockOpen, mockExecute, mockDepsOpen):
    mockOpen.side_effect = lambda f: { "/dist/aliroot.sh"          : StringIO(RECIPE_ALIROOT),
                                       "/dist/root.sh"             : StringIO(RECIPE_ROOT),
                                       "/dist/gcc-toolchain.sh"    : StringIO(RECIPE_GCC_TOOLCHAIN),
                                       "/dist/defaults-release.sh" : StringIO(RECIPE_DEFAULTS_RELEASE) }[f]

    class NamedStringIO(StringIO):
      name = ""
    def depsOpen(fn, mode):
      dot.name = fn
      return dot
    dot = NamedStringIO()
    mockExecute.side_effect = lambda cmd: True
    mockDepsOpen.side_effect = depsOpen

    args = Namespace(workDir="/work",
                     configDir="/dist",
                     debug=False,
                     docker=False,
                     preferSystem=[],
                     noSystem=True,
                     architecture="slc7_x86-64",
                     disable=[],
                     neat=True,
                     outdot="/tmp/out.dot",
                     outgraph="/tmp/outgraph.pdf",
                     package="AliRoot",
                     defaults="release")

    doDeps(args, MagicMock())

    # Same check without explicit intermediate dotfile
    args.outdot = None
    doDeps(args, MagicMock())

if __name__ == '__main__':
  unittest.main()
