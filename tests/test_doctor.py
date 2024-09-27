from __future__ import print_function
from unittest.mock import patch, MagicMock
from io import StringIO

from alibuild_helpers.doctor import doDoctor
from argparse import Namespace
import unittest

RECIPE_DEFAULTS_RELEASE = """package: defaults-release
version: v1
---
"""

RECIPE_PACKAGE1 = """package: Package1
version: v1
prefer_system: .*
prefer_system_check: /bin/false
---
"""

RECIPE_SYSDEP = """package: SysDep
version: v1
system_requirement: .*
system_requirement_check: /bin/false
---
"""

RECIPE_BREAKDEFAULTS = """package: BreakDefaults
version: v1
valid_defaults:
  - its_not_there
---
"""

RECIPE_TESTDEF1 = """package: TestDef1
version: v1
valid_defaults:
  - common_default
  - default1
requires:
  - TestDef2
---
"""

RECIPE_TESTDEF2 = """package: TestDef2
version: v1
valid_defaults:
  - common_default
  - default2
---
"""
class DoctorTestCase(unittest.TestCase):

  @patch("alibuild_helpers.doctor.banner")
  @patch("alibuild_helpers.doctor.warning")
  @patch("alibuild_helpers.doctor.error")
  @patch("alibuild_helpers.doctor.exists")
  @patch("alibuild_helpers.utilities.open")
  def test_doctor(self, mockOpen, mockExists, mockPrintError, mockPrintWarning, mockPrintBanner):
    mockExists.return_value = True
    mockOpen.side_effect = lambda f: { "/dist/package1.sh"         : StringIO(RECIPE_PACKAGE1),
                                       "/dist/testdef1.sh"         : StringIO(RECIPE_TESTDEF1),
                                       "/dist/testdef2.sh"         : StringIO(RECIPE_TESTDEF2),
                                       "/dist/sysdep.sh"           : StringIO(RECIPE_SYSDEP),
                                       "/dist/defaults-release.sh" : StringIO(RECIPE_DEFAULTS_RELEASE),
                                       "/dist/breakdefaults.sh"    : StringIO(RECIPE_BREAKDEFAULTS) }[f]

    # Collect printouts
    def resetOut():
      return { "warning": StringIO(), "error": StringIO(), "banner": StringIO() }
    mockPrintError.side_effect   = lambda e, *a: out["error"].write((e%a)+"\n")
    mockPrintWarning.side_effect = lambda e, *a: out["warning"].write((e%a)+"\n")
    mockPrintBanner.side_effect  = lambda e, *a: out["banner"].write((e%a)+"\n")

    args = Namespace(workDir="/work",
                     configDir="/dist",
                     docker=False,
                     dockerImage=None,
                     docker_extra_args=["--network=host"],
                     debug=False,
                     preferSystem=[],
                     noSystem=False,
                     architecture="osx_x86-64",
                     disable=[],
                     defaults="release")

    # What to call (longer names deprecated in Python 3.5+)
    if not hasattr(self, "assertRegex"):
      self.assertRegex = self.assertRegexpMatches
      self.assertNotRegex = self.assertNotRegexpMatches

    # Test: all should go OK (exit with 0)
    out = resetOut()
    with self.assertRaises(SystemExit) as cm:
      args.packages=["Package1"]
      doDoctor(args, MagicMock())
    self.assertEqual(cm.exception.code, 0)

    # Test: system dependency not found
    out = resetOut()
    with self.assertRaises(SystemExit) as cm:
      args.packages=["SysDep"]
      doDoctor(args, MagicMock())
    self.assertEqual(cm.exception.code, 1)

    # Test: invalid default
    out = resetOut()
    with self.assertRaises(SystemExit) as cm:
      args.packages=["BreakDefaults"]
      doDoctor(args, MagicMock())
    self.assertEqual(cm.exception.code, 2)
    self.assertRegex(out["error"].getvalue(), "- its_not_there")

    # Test: common defaults
    out = resetOut()
    with self.assertRaises(SystemExit) as cm:
      args.packages=["TestDef1"]
      doDoctor(args, MagicMock())
    self.assertEqual(cm.exception.code, 2)
    self.assertRegex(out["banner"].getvalue(), "- common_default")
    self.assertNotRegex(out["banner"].getvalue(), "- default1")
    self.assertNotRegex(out["banner"].getvalue(), "- default2")

if __name__ == '__main__':
  unittest.main()
