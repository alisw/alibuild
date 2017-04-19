from __future__ import print_function
# Assuming you are using the mock library to ... mock things
try:
    from unittest.mock import patch, call, MagicMock  # In Python 3, mock is built-in
    from io import StringIO
except ImportError:
    from mock import patch, call, MagicMock  # Python 2
    from StringIO import StringIO


from alibuild_helpers.build import doBuild, HttpRemoteSync, RsyncRemoteSync, NoRemoteSync
from alibuild_helpers.analytics import decideAnalytics, askForAnalytics, report_screenview, report_exception, report_event
from argparse import Namespace
import sys
import os
import os.path
import re

import mock
import unittest
import traceback

class ExpectedExit(Exception):
  pass

TEST_ZLIB_RECIPE = """package: zlib
version: v1.2.3
---
./configure
make
make install
"""

TEST_ROOT_RECIPE = """package: ROOT
version: v6-08-30
requires:
- zlib
---
./configure
make
make install
"""

TEST_DEFAULT_RELEASE = """package: defaults-release
version: v1
---
"""

def dummy_getstatusoutput(x):
  if re.match("mkdir -p [^;]*$", x):
    return (0, "")
  if re.match("ln -snf[^;]*$", x):
    return (0, "")
  return {
      "GIT_DIR=/alidist/.git git rev-parse HEAD": (0, "6cec7b7b3769826219dfa85e5daa6de6522229a0"),
      'pip show alibuild | grep -e "^Version:" | sed -e \'s/.* //\'': (0, "v1.5.0"),
      'which pigz': (1, ""),
      'tar --ignore-failed-read -cvvf /dev/null /dev/zero': (0, "")
    }[x]

TIMES_ASKED = {}

def dummy_open(x, mode="r"):
  if mode == "r":
    threshold, result = {
      "/sw/BUILD/27ce49698e818e8efb56b6eff6dd785e503df341/defaults-release/.build_succeeded": (0, StringIO("0")),
      "/sw/BUILD/304a6928edf84202f615291f734a636b743d7397/zlib/.build_succeeded": (0, StringIO("0")),
      "/sw/BUILD/a63e3474853662469af91be25c46b3b112a16f5a/ROOT/.build_succeeded": (0, StringIO("0")),
      "/sw/osx_x86-64/defaults-release/v1-1/.build-hash": (1, StringIO("27ce49698e818e8efb56b6eff6dd785e503df341")),
      "/sw/osx_x86-64/zlib/v1.2.3-1/.build-hash": (1, StringIO("304a6928edf84202f615291f734a636b743d7397")),
      "/sw/osx_x86-64/ROOT/v6-08-30-1/.build-hash": (1, StringIO("a63e3474853662469af91be25c46b3b112a16f5a"))
    }[x]
    if threshold > TIMES_ASKED.get(x, 0):
      result = None
    TIMES_ASKED[x] = TIMES_ASKED.get(x, 0) + 1
    if not result:
      raise IOError
    return result
  return StringIO()

def dummy_execute(x, **kwds):
  if re.match(".*ln -sfn.*TARS", x):
    return 0
  return {
    "/bin/bash -e -x /sw/SPECS/osx_x86-64/defaults-release/v1-1/build.sh 2>&1": 0,
    '/bin/bash -e -x /sw/SPECS/osx_x86-64/zlib/v1.2.3-1/build.sh 2>&1': 0,
    '/bin/bash -e -x /sw/SPECS/osx_x86-64/ROOT/v6-08-30-1/build.sh 2>&1': 0
  }[x]

def dummy_readlink(x):
  return {"/sw/TARS/osx_x86-64/defaults-release/defaults-release-v1-1.osx_x86-64.tar.gz": "../../osx_x86-64/store/27/27ce49698e818e8efb56b6eff6dd785e503df341/defaults-release-v1-1.osx_x86-64.tar.gz"}[x]

def dummy_exists(x):
  if x.endswith("alibuild_helpers/.git"):
    return False
  return {"/alidist": True, "/sw/SPECS": False, "/alidist/.git": True, "alibuild_helpers/.git": False}[x]

# A few errors we should handle, together with the expected result
class BuildTestCase(unittest.TestCase):
  @patch("alibuild_helpers.build.urlopen")
  @patch("alibuild_helpers.build.execute")
  @patch("alibuild_helpers.build.getstatusoutput")
  @patch("alibuild_helpers.build.exists")
  @patch("alibuild_helpers.build.sys")
  @patch("alibuild_helpers.build.dieOnError")
  @patch("alibuild_helpers.build.readDefaults")
  @patch("alibuild_helpers.build.makedirs")
  @patch("alibuild_helpers.build.debug")
  @patch("alibuild_helpers.build.updateReferenceRepos")
  @patch("alibuild_helpers.utilities.open")
  @patch("alibuild_helpers.build.open")
  @patch("alibuild_helpers.build.shutil")
  @patch("alibuild_helpers.build.glob")
  @patch("alibuild_helpers.build.readlink")
  @patch("alibuild_helpers.build.banner")
  def test_coverDoBuild(self, mock_banner, mock_readlink, mock_glob, mock_shutil, mock_open,  mock_utilities_open, mock_reference, mock_debug, mock_makedirs, mock_read_defaults, mock_die, mock_sys, mock_exists, mock_getstatusoutput, mock_execute, mock_urlopen):
    mock_readlink.side_effect = dummy_readlink
    mock_glob.side_effect = lambda x : {"*": ["zlib"],
        "/sw/TARS/osx_x86-64/defaults-release/defaults-release-v1-*.osx_x86-64.tar.gz": ["/sw/TARS/osx_x86-64/defaults-release/defaults-release-v1-1.osx_x86-64.tar.gz"],
        "/sw/TARS/osx_x86-64/zlib/zlib-v1.2.3-*.osx_x86-64.tar.gz": [],
        "/sw/TARS/osx_x86-64/ROOT/ROOT-v6-08-30-*.osx_x86-64.tar.gz": [],
        "/sw/TARS/osx_x86-64/store/27/27ce49698e818e8efb56b6eff6dd785e503df341/*": [],
        "/sw/TARS/osx_x86-64/store/30/304a6928edf84202f615291f734a636b743d7397/*": [],
        "/sw/TARS/osx_x86-64/store/a6/a63e3474853662469af91be25c46b3b112a16f5a/*": [],
        "/sw/TARS/osx_x86-64/defaults-release/defaults-release-v1-1.osx_x86-64.tar.gz": ["../../osx_x86-64/store/27/27ce49698e818e8efb56b6eff6dd785e503df341/defaults-release-v1-1.osx_x86-64.tar.gz"],
      }[x]
    os.environ["ALIBUILD_NO_ANALYTICS"] = "1"
    mock_utilities_open.side_effect = lambda x : {
      "/alidist/root.sh": StringIO(TEST_ROOT_RECIPE),
      "/alidist/zlib.sh": StringIO(TEST_ZLIB_RECIPE),
      "/alidist/defaults-release.sh": StringIO(TEST_DEFAULT_RELEASE)
    }[x]
    mock_open.side_effect = dummy_open
    mock_execute.side_effect = dummy_execute
    mock_exists.side_effect = dummy_exists
    mock_getstatusoutput.side_effect = dummy_getstatusoutput
    mock_parser = MagicMock()
    mock_read_defaults.return_value = ({"package": "defaults-release", "disable": []}, "")
    args = Namespace(
      remoteStore="",
      writeStore="",
      referenceSources="/sw/MIRROR",
      docker=False,
      architecture="osx_x86-64",
      workDir="/sw",
      pkgname=["root"],
      configDir="/alidist",
      dist={"repo": "alisw/alidist", "ver": "master"},
      disable=[],
      defaults="release",
      jobs=2,
      preferSystem=[],
      noSystem=False,
      debug=True,
      dryRun=False,
      aggressiveCleanup=False,
      environment={},
      autoCleanup=False,
      noDevel=[]
    )
    fmt, msg, code = doBuild(args, mock_parser)
    mock_glob.assert_called_with("/sw/TARS/osx_x86-64/ROOT/ROOT-v6-08-30-*.osx_x86-64.tar.gz")
    self.assertEqual(msg, "Everything done")

  @patch("alibuild_helpers.build.urlopen")
  @patch("alibuild_helpers.build.execute")
  @patch("alibuild_helpers.build.getstatusoutput")
  @patch("alibuild_helpers.build.sys")
  @patch("alibuild_helpers.build.dieOnError")
  @patch("alibuild_helpers.build.error")
  def test_coverSyncs(self, mock_error, mock_die, mock_sys, mock_getstatusoutput, mock_execute, mock_urlopen):
    syncers = [NoRemoteSync(),
               HttpRemoteSync(remoteStore="https://local/test", architecture="osx_x86-64", workdir="/sw", insecure=False),
               RsyncRemoteSync(remoteStore="ssh://local/test", writeStore="ssh://local/test", architecture="osx_x86-64", workdir="/sw", rsyncOptions="")]
    dummy_spec = {"package": "zlib", "version": "v1.2.3", "revision": "1", "hash": "deadbeef", "storePath": "/sw/path", "linksPath": "/sw/links", "tarballHashDir": "/sw/TARS", "tarballLinkDir": "/sw/TARS"}
    for x in syncers:
      x.syncToLocal("zlib", dummy_spec)
      x.syncToRemote("zlib", dummy_spec)

if __name__ == '__main__':
  unittest.main()
