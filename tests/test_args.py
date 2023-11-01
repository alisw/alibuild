from __future__ import print_function
# Assuming you are using the mock library to ... mock things
try:
    from unittest import mock
    from unittest.mock import patch, call  # In Python 3, mock is built-in
except ImportError:
    import mock
    from mock import patch, call  # Python 2

import alibuild_helpers.args
from alibuild_helpers.args import doParseArgs, matchValidArch, finaliseArgs, DEFAULT_WORK_DIR, DEFAULT_CHDIR, ARCHITECTURE_TABLE
import sys
import os
import os.path

import unittest
import shlex

if (sys.version_info[0] >= 3):
  BUILD_MISSING_PKG_ERROR = "the following arguments are required: PACKAGE"
  ANALYTICS_MISSING_STATE_ERROR = "the following arguments are required: state"
else:
  BUILD_MISSING_PKG_ERROR = "too few arguments"
  ANALYTICS_MISSING_STATE_ERROR = "too few arguments"

# A few errors we should handle, together with the expected result
ARCHITECTURE_ERROR = [call(u"Unknown / unsupported architecture: foo.\n\n{table}Alternatively, you can use the `--force-unknown-architecture' option.".format(table=ARCHITECTURE_TABLE))]
PARSER_ERRORS = {
  "build --force-unknown-architecture": [call(BUILD_MISSING_PKG_ERROR)],
  "build --force-unknown-architecture zlib --foo": [call('unrecognized arguments: --foo')],
  "init --docker-image": [call('unrecognized arguments: --docker-image')],
  "builda --force-unknown-architecture zlib" : [call("argument action: invalid choice: 'builda' (choose from 'analytics', 'architecture', 'build', 'clean', 'deps', 'doctor', 'init', 'version')")],
  "build --force-unknown-architecture zlib --no-system --always-prefer-system" : [call('argument --always-prefer-system: not allowed with argument --no-system')],
  "build zlib --architecture foo": ARCHITECTURE_ERROR,
  "build --force-unknown-architecture zlib --remote-store rsync://test1.local/::rw --write-store rsync://test2.local/::rw ": [call('cannot specify ::rw and --write-store at the same time')],
  "build zlib -a osx_x86-64 --docker-image foo": [call('cannot use `-a osx_x86-64` and --docker')],
  "analytics": [call(ANALYTICS_MISSING_STATE_ERROR)]
}

# A few valid archs
VALID_ARCHS = ["osx_x86-64", "slc7_x86-64", "slc8_x86-64"]
INVALID_ARCHS = ["osx_ppc64", "sl8_x86-64"]

class FakeExit(Exception):
  pass

CORRECT_BEHAVIOR = [
  ((), "build --force-unknown-architecture zlib"                                       , [("action", "build"), ("workDir", "sw"), ("referenceSources", "sw/MIRROR")]),
  ((), "init"                                                                          , [("action", "init"), ("workDir", "sw"), ("referenceSources", "sw/MIRROR")]),
  ((), "version"                                                                       , [("action", "version")]),
  ((), "clean"                                                                         , [("action", "clean"), ("workDir", "sw")]),
  ((), "build --force-unknown-architecture -j 10 zlib"                                 , [("action", "build"), ("jobs", 10), ("pkgname", ["zlib"])]),
  ((), "build --force-unknown-architecture -j 10 zlib --disable gcc --disable foo"     , [("disable", ["gcc", "foo"])]),
  ((), "build --force-unknown-architecture -j 10 zlib --disable gcc --disable foo,bar" , [("disable", ["gcc", "foo", "bar"])]),
  ((), "init zlib --dist master"                                                       , [("dist", {"repo": "alisw/alidist", "ver": "master"})]),
  ((), "init zlib --dist ktf/alidist@dev"                                              , [("dist", {"repo": "ktf/alidist", "ver": "dev"})]),
  ((), "build --force-unknown-architecture zlib --remote-store rsync://test.local/"    , [("noSystem", True), ("remoteStore", "rsync://test.local/")]),
  ((), "build --force-unknown-architecture zlib --remote-store rsync://test.local/::rw", [("noSystem", True), ("remoteStore", "rsync://test.local/"), ("writeStore", "rsync://test.local/")]),
  ((), "build --force-unknown-architecture zlib --no-remote-store --remote-store rsync://test.local/", [("noSystem", False), ("remoteStore", "")]),
  ((), "build zlib --architecture slc7_x86-64"                                         , [("noSystem", True), ("preferSystem", False), ("remoteStore", "https://s3.cern.ch/swift/v1/alibuild-repo")]),
  ((), "build zlib --architecture ubuntu1804_x86-64"                                   , [("noSystem", False), ("preferSystem", False), ("remoteStore", "")]),
  ((), "build zlib -a slc7_x86-64"                                                     , [("docker", False), ("dockerImage", None), ("docker_extra_args", ["--network=host"])]),
  ((), "build zlib -a slc7_x86-64 --docker-image registry.cern.ch/alisw/some-builder"  , [("docker", True), ("dockerImage", "registry.cern.ch/alisw/some-builder")]),
  ((), "build zlib -a slc7_x86-64 --docker"                                            , [("docker", True), ("dockerImage", "registry.cern.ch/alisw/slc7-builder")]),
  ((), "build zlib -a slc7_x86-64 --docker-extra-args=--foo"                           , [("docker", True), ("dockerImage", "registry.cern.ch/alisw/slc7-builder"), ("docker_extra_args", ["--foo", "--network=host"])]),
  ((), "build zlib --devel-prefix -a slc7_x86-64 --docker"                             , [("docker", True), ("dockerImage", "registry.cern.ch/alisw/slc7-builder"), ("develPrefix", "%s-slc7_x86-64" % os.path.basename(os.getcwd()))]),
  ((), "build zlib --devel-prefix -a slc7_x86-64 --docker-image someimage"             , [("docker", True), ("dockerImage", "someimage"), ("develPrefix", "%s-slc7_x86-64" % os.path.basename(os.getcwd()))]),
  ((), "--debug build --force-unknown-architecture --defaults o2 O2"                   , [("debug", True), ("action",  "build"), ("defaults", "o2"), ("pkgname", ["O2"])]),
  ((), "build --force-unknown-architecture --debug --defaults o2 O2"                   , [("debug", True), ("action",  "build"), ("force_rebuild", []), ("defaults", "o2"), ("pkgname", ["O2"])]),
  ((), "build --force-unknown-architecture --force-rebuild O2 --force-rebuild O2Physics --defaults o2 O2Physics", [("action", "build"), ("force_rebuild", ["O2", "O2Physics"]), ("defaults", "o2"), ("pkgname", ["O2Physics"])]),
  ((), "build --force-unknown-architecture --force-rebuild O2,O2Physics --defaults o2 O2Physics", [("action", "build"), ("force_rebuild", ["O2", "O2Physics"]), ("defaults", "o2"), ("pkgname", ["O2Physics"])]),
  ((), "init -z test zlib"                                                             , [("configDir", "test/alidist")]),
  ((), "build --force-unknown-architecture -z test zlib"                               , [("configDir", "alidist")]),
  ((), "analytics off"                                                                 , [("state", "off")]),
  ((), "analytics on"                                                                  , [("state", "on")]),

  # With ALIBUILD_WORK_DIR and ALIBUILD_CHDIR set
  (("sw2", ".")    , "build --force-unknown-architecture zlib"                         , [("action", "build"), ("workDir", "sw2"), ("referenceSources", "sw2/MIRROR"), ("chdir", ".")]),
  (("sw3", "mydir"), "init"                                                            , [("action", "init"), ("workDir", "sw3"), ("referenceSources", "sw3/MIRROR"), ("chdir", "mydir")]),
  (("sw", ".")     , "clean --chdir mydir2 --work-dir sw4"                             , [("action", "clean"), ("workDir", "sw4"), ("chdir", "mydir2")]),
  (()              , "doctor zlib -C mydir -w sw2"                                     , [("action", "doctor"), ("workDir", "sw2"), ("chdir", "mydir")]),
  (()              , "deps zlib --outgraph graph.pdf"                                  , [("action", "deps"), ("outgraph", "graph.pdf")]),
]

GETSTATUSOUTPUT_MOCKS = {
  "which docker": (0, "/usr/local/bin/docker")
}

class ArgsTestCase(unittest.TestCase):
  @mock.patch("alibuild_helpers.utilities.getoutput", new=lambda cmd: "x86_64")   # for uname -m
  @mock.patch('alibuild_helpers.args.commands')
  def test_actionParsing(self, mock_commands):
    mock_commands.getstatusoutput.side_effect = lambda x : GETSTATUSOUTPUT_MOCKS[x]
    for (env, cmd, effects) in CORRECT_BEHAVIOR:
      (alibuild_helpers.args.DEFAULT_WORK_DIR,
       alibuild_helpers.args.DEFAULT_CHDIR) = env or ("sw", ".")
      with patch.object(sys, "argv", ["alibuild"] + shlex.split(cmd)):
        args, parser = doParseArgs()
        args = vars(args)
        for k, v in effects:
          self.assertEqual(args[k], v)

  @mock.patch("alibuild_helpers.utilities.getoutput", new=lambda cmd: "x86_64")   # for uname -m
  @mock.patch('alibuild_helpers.args.argparse.ArgumentParser.error')
  def test_failingParsing(self, mock_print):
    mock_print.side_effect = FakeExit("raised")
    for (cmd, calls) in PARSER_ERRORS.items():
      mock_print.mock_calls = []
      with patch.object(sys, "argv", ["alibuild"] + shlex.split(cmd)):
        self.assertRaises(FakeExit, doParseArgs)
        self.assertEqual(mock_print.mock_calls, calls)

  def test_validArchitectures(self):
    for arch in VALID_ARCHS:
      self.assertTrue(matchValidArch(arch))
    for arch in INVALID_ARCHS:
      self.assertFalse(matchValidArch(arch))

if __name__ == '__main__':
  unittest.main()
