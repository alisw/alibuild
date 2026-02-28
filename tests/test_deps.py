from unittest.mock import patch, MagicMock
from io import StringIO
import os.path

from alibuild_helpers.deps import doDeps
from argparse import Namespace
import unittest

RECIPES = {
    "/dist/defaults-release.sh": """\
package: defaults-release
version: v1
---
""",
    "/dist/gcc-toolchain.sh": """\
package: GCC-Toolchain
version: v1
---
""",
    "/dist/aliroot.sh": """\
package: AliRoot
version: v1
requires:
  - ROOT
  - GCC-Toolchain
---
""",
    "/dist/root.sh": """\
package: ROOT
version: v1
build_requires:
  - GCC-Toolchain
---
""",
}


class DepsTestCase(unittest.TestCase):

    @patch("alibuild_helpers.deps.open")
    @patch("alibuild_helpers.deps.execute", new=lambda cmd: True)
    @patch("alibuild_helpers.utilities.open", new=lambda f: StringIO(RECIPES[f]))
    def test_deps(self, mockDepsOpen):
        """Check doDeps doesn't raise an exception."""
        dot = StringIO()
        dot.name = ""

        def depsOpen(fn, mode):
            dot.name = fn
            return dot
        mockDepsOpen.side_effect = depsOpen

        args = Namespace(workDir="/work",
                         configDir="/dist",
                         debug=False,
                         docker=False,
                         dockerImage=None,
                         docker_extra_args=["--network=host"],
                         preferSystem=[],
                         noSystem="*",
                         architecture="slc7_x86-64",
                         disable=[],
                         neat=True,
                         outdot="/tmp/out.dot",
                         outgraph="/tmp/outgraph.pdf",
                         package="AliRoot",
                         defaults="release",
                         environment=[])
        def fake_exists(n):
            return {"/alidist/aliroot.sh": True}
        with patch.object(os.path, "exists", fake_exists):
            doDeps(args, MagicMock())

            # Same check without explicit intermediate dotfile
            args.outdot = None
            doDeps(args, MagicMock())


if __name__ == '__main__':
    unittest.main()
