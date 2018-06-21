from __future__ import print_function
# Assuming you are using the mock library to ... mock things
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

from alibuild_helpers.build import doBuild, HttpRemoteSync, RsyncRemoteSync, NoRemoteSync
from alibuild_helpers.analytics import decideAnalytics, askForAnalytics, report_screenview, report_exception, report_event
from argparse import Namespace
import sys
import os
import os.path
import re

import unittest
import traceback

class ExpectedExit(Exception):
  pass

TEST_ZLIB_RECIPE = """package: zlib
version: v1.2.3
source: https://github.com/star-externals/zlib
tag: master
---
./configure
make
make install
"""

TEST_ROOT_RECIPE = """package: ROOT
version: v6-08-30
source: https://github.com/root-mirror/root
tag: v6-08-00-patches
requires:
  - zlib
env:
  ROOT_TEST_1: "root test 1"
  ROOT_TEST_2: "root test 2"
  ROOT_TEST_3: "root test 3"
  ROOT_TEST_4: "root test 4"
  ROOT_TEST_5: "root test 5"
  ROOT_TEST_6: "root test 6"
prepend_path:
  PREPEND_ROOT_1: "prepend root 1"
  PREPEND_ROOT_2: "prepend root 2"
  PREPEND_ROOT_3: "prepend root 3"
  PREPEND_ROOT_4: "prepend root 4"
  PREPEND_ROOT_5: "prepend root 5"
  PREPEND_ROOT_6: "prepend root 6"
append_path:
  APPEND_ROOT_1: "append root 1"
  APPEND_ROOT_2: "append root 2"
  APPEND_ROOT_3: "append root 3"
  APPEND_ROOT_4: "append root 4"
  APPEND_ROOT_5: "append root 5"
  APPEND_ROOT_6: "append root 6"
---
./configure
make
make install
"""
TEST_ROOT_BUILD_HASH = "2cb80ea18ac9ec56b94c4d9a865caa1f7e03a8f0" if sys.version_info[0] < 3 else \
                       "1fc9be611d016280a2a66519923965839d0d009b"

TEST_DEFAULT_RELEASE = """package: defaults-release
version: v1
---
"""

def dummy_getstatusoutput(x):
  if re.match("/bin/bash --version", x):
    return (0, "GNU bash, version 3.2.57(1)-release (x86_64-apple-darwin17)\nCopyright (C) 2007 Free Software Foundation, Inc.\n")
  if re.match("mkdir -p [^;]*$", x):
    return (0, "")
  if re.match("ln -snf[^;]*$", x):
    return (0, "")
  return {
      "GIT_DIR=/alidist/.git git rev-parse HEAD": (0, "6cec7b7b3769826219dfa85e5daa6de6522229a0"),
      'pip --disable-pip-version-check show alibuild | grep -e "^Version:" | sed -e \'s/.* //\'': (0, "v1.5.0"),
      'which pigz': (1, ""),
      'tar --ignore-failed-read -cvvf /dev/null /dev/zero': (0, "")
    }[x]

def dummy_getStatusOutputBash(x):
  return {
      'git ls-remote --heads /sw/MIRROR/root': (0, "87b87c4322d2a3fad315c919cb2e2dd73f2154dc\trefs/heads/master\nf7b336611753f1f4aaa94222b0d620748ae230c0\trefs/heads/v6-08-00-patches"),
      'git ls-remote --heads /sw/MIRROR/zlib': (0, "8822efa61f2a385e0bc83ca5819d608111b2168a\trefs/heads/master")
    }[x]

TIMES_ASKED = {}

def dummy_open(x, mode="r"):
  if mode == "r":
    threshold, result = {
      "/sw/BUILD/27ce49698e818e8efb56b6eff6dd785e503df341/defaults-release/.build_succeeded": (0, StringIO("0")),
      "/sw/BUILD/3e90b4e08bad439fa5f25282480d1adb9efb0c0d/zlib/.build_succeeded": (0, StringIO("0")),
      "/sw/BUILD/%s/ROOT/.build_succeeded" % TEST_ROOT_BUILD_HASH: (0, StringIO("0")),
      "/sw/osx_x86-64/defaults-release/v1-1/.build-hash": (1, StringIO("27ce49698e818e8efb56b6eff6dd785e503df341")),
      "/sw/osx_x86-64/zlib/v1.2.3-1/.build-hash": (1, StringIO("3e90b4e08bad439fa5f25282480d1adb9efb0c0d")),
      "/sw/osx_x86-64/ROOT/v6-08-30-1/.build-hash": (1, StringIO(TEST_ROOT_BUILD_HASH))
    }[x]
    if threshold > TIMES_ASKED.get(x, 0):
      result = None
    TIMES_ASKED[x] = TIMES_ASKED.get(x, 0) + 1
    if not result:
      raise IOError
    return result
  return StringIO()

def dummy_execute(x, mock_git_clone, mock_git_fetch, **kwds):
  s = " ".join(x) if isinstance(x, list) else x
  if re.match(".*ln -sfn.*TARS", s):
    return 0
  if re.search("^git clone --bare", s):
    mock_git_clone()
  elif re.search("&& git fetch --tags", s):
    mock_git_fetch()
    return 0
  return {
    "/bin/bash -e -x /sw/SPECS/osx_x86-64/defaults-release/v1-1/build.sh 2>&1": 0,
    '/bin/bash -e -x /sw/SPECS/osx_x86-64/zlib/v1.2.3-1/build.sh 2>&1': 0,
    '/bin/bash -e -x /sw/SPECS/osx_x86-64/ROOT/v6-08-30-1/build.sh 2>&1': 0,
    "git clone --bare https://github.com/star-externals/zlib /sw/MIRROR/zlib": 0,
    "git clone --bare https://github.com/root-mirror/root /sw/MIRROR/root": 0
  }[s]

def dummy_readlink(x):
  return {"/sw/TARS/osx_x86-64/defaults-release/defaults-release-v1-1.osx_x86-64.tar.gz": "../../osx_x86-64/store/27/27ce49698e818e8efb56b6eff6dd785e503df341/defaults-release-v1-1.osx_x86-64.tar.gz"}[x]

def dummy_exists(x):
  if x.endswith("alibuild_helpers/.git"):
    return False
  return {
    "/alidist": True,
    "/sw/SPECS": False,
    "/alidist/.git": True,
    "alibuild_helpers/.git": False,
    "/sw/MIRROR/root": True,
    "/sw/MIRROR/zlib": False}[x]

# A few errors we should handle, together with the expected result
class BuildTestCase(unittest.TestCase):
  @patch("alibuild_helpers.build.urlopen")
  @patch("alibuild_helpers.build.execute")
  @patch("alibuild_helpers.workarea.execute")
  @patch("alibuild_helpers.build.getstatusoutput")
  @patch("alibuild_helpers.build.exists")
  @patch("alibuild_helpers.workarea.path.exists")
  @patch("alibuild_helpers.build.sys")
  @patch("alibuild_helpers.build.dieOnError")
  @patch("alibuild_helpers.build.readDefaults")
  @patch("alibuild_helpers.build.makedirs")
  @patch("alibuild_helpers.build.debug")
  @patch("alibuild_helpers.utilities.open")
  @patch("alibuild_helpers.build.open")
  @patch("alibuild_helpers.build.shutil")
  @patch("alibuild_helpers.build.glob")
  @patch("alibuild_helpers.build.readlink")
  @patch("alibuild_helpers.build.banner")
  @patch("alibuild_helpers.build.getStatusOutputBash")
  @patch("alibuild_helpers.workarea.is_writeable")
  def test_coverDoBuild(self, mock_is_writeable, mock_getStatusOutputBash, mock_banner,
                              mock_readlink, mock_glob, mock_shutil, mock_open, mock_utilities_open,
                              mock_debug, mock_makedirs, mock_read_defaults, mock_die, mock_sys,
                              mock_workarea_exists, mock_exists, mock_getstatusoutput,
                              mock_workarea_execute, mock_execute, mock_urlopen):
    mock_readlink.side_effect = dummy_readlink
    mock_glob.side_effect = lambda x : {"*": ["zlib"],
        "/sw/TARS/osx_x86-64/defaults-release/defaults-release-v1-*.osx_x86-64.tar.gz": ["/sw/TARS/osx_x86-64/defaults-release/defaults-release-v1-1.osx_x86-64.tar.gz"],
        "/sw/TARS/osx_x86-64/zlib/zlib-v1.2.3-*.osx_x86-64.tar.gz": [],
        "/sw/TARS/osx_x86-64/ROOT/ROOT-v6-08-30-*.osx_x86-64.tar.gz": [],
        "/sw/TARS/osx_x86-64/store/27/27ce49698e818e8efb56b6eff6dd785e503df341/*": [],
        "/sw/TARS/osx_x86-64/store/3e/3e90b4e08bad439fa5f25282480d1adb9efb0c0d/*": [],
        "/sw/TARS/osx_x86-64/store/%s/%s/*" % (TEST_ROOT_BUILD_HASH[0:2], TEST_ROOT_BUILD_HASH): [],
        "/sw/TARS/osx_x86-64/defaults-release/defaults-release-v1-1.osx_x86-64.tar.gz": ["../../osx_x86-64/store/27/27ce49698e818e8efb56b6eff6dd785e503df341/defaults-release-v1-1.osx_x86-64.tar.gz"],
      }[x]
    os.environ["ALIBUILD_NO_ANALYTICS"] = "1"
    mock_utilities_open.side_effect = lambda x : {
      "/alidist/root.sh": StringIO(TEST_ROOT_RECIPE),
      "/alidist/zlib.sh": StringIO(TEST_ZLIB_RECIPE),
      "/alidist/defaults-release.sh": StringIO(TEST_DEFAULT_RELEASE)
    }[x]
    mock_is_writeable.side_effect = lambda x: True
    mock_open.side_effect = dummy_open

    mock_git_clone = MagicMock(return_value=None)
    mock_git_fetch = MagicMock(return_value=None)
    mock_execute.side_effect = lambda x, **kwds: dummy_execute(x, mock_git_clone, mock_git_fetch, **kwds)
    mock_workarea_execute.side_effect = lambda x, **kwds: dummy_execute(x, mock_git_clone, mock_git_fetch, **kwds)

    mock_exists.side_effect = dummy_exists
    mock_workarea_exists.side_effect = dummy_exists
    mock_getstatusoutput.side_effect = dummy_getstatusoutput
    mock_getStatusOutputBash.side_effect = dummy_getStatusOutputBash
    mock_parser = MagicMock()
    mock_read_defaults.return_value = (OrderedDict({"package": "defaults-release", "disable": []}), "")
    args = Namespace(
      remoteStore="",
      writeStore="",
      referenceSources="/sw/MIRROR",
      docker=False,
      architecture="osx_x86-64",
      workDir="/sw",
      pkgname=["root"],
      configDir="/alidist",
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
      noDevel=[],
      fetchRepos=False
    )
    mock_sys.version_info = sys.version_info

    mock_git_clone.reset_mock()
    mock_git_fetch.reset_mock()
    fmt, msg, code = doBuild(args, mock_parser)
    self.assertEqual(mock_git_clone.call_count, 1, "Expected only one call to git clone (called %d times instead)" % mock_git_clone.call_count)
    self.assertEqual(mock_git_fetch.call_count, 0, "Expected only no calls to git fetch (called %d times instead)" % mock_git_fetch.call_count)

    # Force fetching repos
    mock_git_clone.reset_mock()
    mock_git_fetch.reset_mock()
    args.fetchRepos = True
    fmt, msg, code = doBuild(args, mock_parser)
    mock_glob.assert_called_with("/sw/TARS/osx_x86-64/ROOT/ROOT-v6-08-30-*.osx_x86-64.tar.gz")
    self.assertEqual(msg, "Everything done")
    self.assertEqual(mock_git_clone.call_count, 1, "Expected only one call to git clone (called %d times instead)" % mock_git_clone.call_count)
    self.assertEqual(mock_git_fetch.call_count, 1, "Expected only one call to git fetch (called %d times instead)" % mock_git_fetch.call_count)

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

  def test_parse_environment_arguments(self):
      from alibuild_helpers.build import parse_environment_arguments
      args = parse_environment_arguments(["A=b", "B=c", "C"])
      self.assertEqual(args[0], ("A", "b"))
      self.assertEqual(args[1], ("B", "c"))
      self.assertEqual(args[2], ("C", ""))

if __name__ == '__main__':
  unittest.main()
