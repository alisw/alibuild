from __future__ import print_function
# Assuming you are using the mock library to ... mock things
try:
    from unittest.mock import patch, call  # In Python 3, mock is built-in
except ImportError:
    from mock import patch, call  # Python 2

from alibuild_helpers.args import doParseArgs, matchValidArch, finaliseArgs
import argparse
import sys
import os
import os.path

import mock
import unittest
import traceback
import shlex

if (sys.version_info[0] >= 3):
  BUILD_MISSING_PKG_ERROR = "the following arguments are required: pkgname"
  ANALYTICS_MISSING_STATE_ERROR = "the following arguments are required: state"
else:
  BUILD_MISSING_PKG_ERROR = "too few arguments"
  ANALYTICS_MISSING_STATE_ERROR = "too few arguments"

# A few errors we should handle, together with the expected result
ARCHITECTURE_ERROR = [call(u"Unknown / unsupported architecture: foo.\n\nOn Linux, x86-64:\n   RHEL5 / SLC5 compatible: slc5_x86-64\n   RHEL6 / SLC6 compatible: slc6_x86-64\n   RHEL7 / CC7 compatible: slc7_x86-64\n   Ubuntu 14.04 compatible: ubuntu1404_x86-64\n   Ubuntu 15.04 compatible: ubuntu1504_x86-64\n   Ubuntu 15.10 compatible: ubuntu1510_x86-64\n   Ubuntu 16.04 compatible: ubuntu1604_x86-64\n\nOn Linux, POWER8 / PPC64 (little endian):\n   RHEL7 / CC7 compatible: slc7_ppc64\n\nOn Mac, x86-64:\n   Yosemite and El-Captain: osx_x86-64\n\nAlternatively, you can use the `--force-unknown-architecture' option.")]
PARSER_ERRORS = {
  "build": [call(BUILD_MISSING_PKG_ERROR)],
  "build zlib --foo": [call('unrecognized arguments: --foo')],
  "init --docker-image": [call('unrecognized arguments: --docker-image')],
  "builda zlib" : [call("argument action: invalid choice: 'builda' (choose from 'analytics', 'build', 'clean', 'deps', 'doctor', 'init', 'version')")],
  "build zlib --no-system --always-prefer-system" : [call('argument --always-prefer-system: not allowed with argument --no-system')],
  "build zlib --architecture foo": ARCHITECTURE_ERROR,
  "clean --architecture foo": ARCHITECTURE_ERROR,
  "build zlib --remote-store rsync://test1.local/::rw --write-store rsync://test2.local/::rw ": [call('cannot specify ::rw and --write-store at the same time')],
  "build zlib -a osx_x86-64 --docker-image foo": [call('cannot use `-a osx_x86-64` and --docker')],
  "analytics": [call(ANALYTICS_MISSING_STATE_ERROR)]
}

# A few valid archs
VALID_ARCHS = [
  "osx_x86-64",
  "slc7_x86-64"
]

INVALID_ARCHS = [
  "osx_x86-64",
  "sl8_x86-64"
]

class FakeExit(Exception):
  pass

CORRECT_BEHAVIOR = {
  "build zlib": [("action", "build"), ("workDir", "sw"), ("referenceSources", "sw/MIRROR")],
  "init": [("action", "init"), ("workDir", "sw"), ("referenceSources", "sw/MIRROR")],
  "version": [("action", "version")],
  "clean": [("action", "clean"), ("workDir", "sw"), ("referenceSources", "sw/MIRROR")],
  "build -j 10 zlib": [("action", "build"), ("jobs", 10), ("pkgname", ["zlib"])],
  "build -j 10 zlib --disable gcc --disable foo": [("disable", ["gcc", "foo"])],
  "build -j 10 zlib --disable gcc --disable foo,bar": [("disable", ["gcc", "foo", "bar"])],
  "build zlib --dist master": [("dist", {"repo": "alisw/alidist", "ver": "master"})],
  "build zlib --dist ktf/alidist@dev": [("dist", {"repo": "ktf/alidist", "ver": "dev"})],
  "build zlib --remote-store rsync://test.local/": [("noSystem", True)],
  "build zlib --remote-store rsync://test.local/::rw": [("noSystem", True), ("remoteStore", "rsync://test.local/"), ("writeStore", "rsync://test.local/")],
  "build zlib -a slc7_x86-64 --docker-image alisw/slc7-builder": [("docker", True), ("dockerImage", "alisw/slc7-builder")],
  "build zlib -a slc7_x86-64 --docker": [("docker", True), ("dockerImage", "alisw/slc7-builder")],
  "build zlib --devel-prefix -a slc7_x86-64 --docker": [("docker", True), ("dockerImage", "alisw/slc7-builder"), ("develPrefix", "%s-slc7_x86-64" % os.path.basename(os.getcwd()))],
  "build zlib --devel-prefix -a slc7_x86-64 --docker-image someimage": [("docker", True), ("dockerImage", "someimage"), ("develPrefix", "%s-slc7_x86-64" % os.path.basename(os.getcwd()))],
  "--debug build --defaults o2 O2": [("debug", True), ("action",  "build"), ("defaults", "o2"), ("pkgname", ["O2"])],
  "build --debug --defaults o2 O2": [("debug", True), ("action",  "build"), ("defaults", "o2"), ("pkgname", ["O2"])],
  "init -z test zlib": [("configDir", "test/alidist")],
  "build -z test zlib": [("configDir", "alidist")],
  "analytics off": [("state", "off")],
  "analytics on": [("state", "on")],
}

GETSTATUSOUTPUT_MOCKS = {
  "which docker": (0, "/usr/local/bin/docker")
}

class ArgsTestCase(unittest.TestCase):
  @mock.patch('alibuild_helpers.args.commands')
  def test_actionParsing(self, mock_commands):
    mock_commands.getstatusoutput.side_effect = lambda x : GETSTATUSOUTPUT_MOCKS[x]
    for (cmd, effects) in CORRECT_BEHAVIOR.items():
      with patch.object(sys, "argv", ["alibuild"] + shlex.split(cmd)):
        args, parser = doParseArgs("ali")
        args = vars(args)
        for k, v in effects:
          self.assertEqual(args[k], v)
          mock_commands.mock_calls

  @mock.patch('alibuild_helpers.args.argparse.ArgumentParser.error')
  def test_failingParsing(self, mock_print):
    mock_print.side_effect = FakeExit("raised")
    for (cmd, calls) in PARSER_ERRORS.items():
      mock_print.mock_calls = []
      with patch.object(sys, "argv", ["alibuild"] + shlex.split(cmd)):
        self.assertRaises(FakeExit, lambda : doParseArgs("ali"))
        self.assertEqual(mock_print.mock_calls, calls)

  @mock.patch('alibuild_helpers.args.argparse.ArgumentParser.error')
  def test_validArchitectures(self, mock_error):
    for x in VALID_ARCHS:
      self.assertTrue(matchValidArch(x))

if __name__ == '__main__':
  unittest.main()
