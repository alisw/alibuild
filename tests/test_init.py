from argparse import Namespace
import os.path as path
import unittest
try:
    from unittest.mock import MagicMock, call, patch  # In Python 3, mock is built-in
    from io import StringIO
except ImportError:
    from mock import MagicMock, call, patch  # Python 2
    from StringIO import StringIO
try:
    from collections import OrderedDict
except ImportError:
    from ordereddict import OrderedDict

from alibuild_helpers.init import doInit, parsePackagesDefinition


def dummy_exists(x):
  return {
      '/sw/MIRROR/aliroot': True,
  }.get(x, False)


CLONE_EVERYTHING = [
    call(["clone", "--origin", "upstream", "https://github.com/alisw/alidist",
          "-b", "master", "/alidist"]),
    call(["clone", "--origin", "upstream", "https://github.com/alisw/AliRoot",
          "--reference", "/sw/MIRROR/aliroot", "-b", "v5-08-00", "./AliRoot"]),
    call(("remote", "set-url", "--push", "upstream",
          "https://github.com/alisw/AliRoot"), directory="./AliRoot"),
]


class InitTestCase(unittest.TestCase):
    def test_packageDefinition(self):
      self.assertEqual(parsePackagesDefinition("AliRoot@v5-08-16,AliPhysics@v5-08-16-01"),
                       [{'ver': 'v5-08-16', 'name': 'AliRoot'},
                        {'ver': 'v5-08-16-01', 'name': 'AliPhysics'}])
      self.assertEqual(parsePackagesDefinition("AliRoot,AliPhysics@v5-08-16-01"),
                       [{'ver': '', 'name': 'AliRoot'},
                        {'ver': 'v5-08-16-01', 'name': 'AliPhysics'}])

    @patch("alibuild_helpers.init.info")
    @patch("alibuild_helpers.init.path")
    @patch("alibuild_helpers.init.os")
    def test_doDryRunInit(self, mock_os, mock_path,  mock_info):
      fake_dist = {"repo": "alisw/alidist", "ver": "master"}
      args = Namespace(
        develPrefix = ".",
        configDir = "/alidist",
        pkgname = "zlib,AliRoot@v5-08-00",
        referenceSources = "/sw/MIRROR",
        dist = fake_dist,
        defaults = "release",
        dryRun = True,
        fetchRepos = False,
        architecture = "slc7_x86-64"
      )
      self.assertRaises(SystemExit, doInit, args)
      self.assertEqual(mock_info.mock_calls, [call('This will initialise local checkouts for %s\n--dry-run / -n specified. Doing nothing.', 'zlib,AliRoot')])

    @patch("alibuild_helpers.init.banner")
    @patch("alibuild_helpers.init.info")
    @patch("alibuild_helpers.init.path")
    @patch("alibuild_helpers.init.os")
    @patch("alibuild_helpers.init.git")
    @patch("alibuild_helpers.init.updateReferenceRepoSpec")
    @patch("alibuild_helpers.utilities.open")
    @patch("alibuild_helpers.init.readDefaults")
    def test_doRealInit(self, mock_read_defaults, mock_open, mock_update_reference, mock_git, mock_os, mock_path,  mock_info, mock_banner):
      fake_dist = {"repo": "alisw/alidist", "ver": "master"}
      mock_open.side_effect = lambda x: {
        "/alidist/defaults-release.sh": StringIO("package: defaults-release\nversion: v1\n---"),
        "/alidist/aliroot.sh": StringIO("package: AliRoot\nversion: master\nsource: https://github.com/alisw/AliRoot\n---")
      }[x]
      mock_git.return_value = ""
      mock_path.exists.side_effect = dummy_exists
      mock_os.mkdir.return_value = None
      mock_path.join.side_effect = path.join
      mock_read_defaults.return_value = (OrderedDict({"package": "defaults-release", "disable": []}), "")
      args = Namespace(
        develPrefix = ".",
        configDir = "/alidist",
        pkgname = "AliRoot@v5-08-00",
        referenceSources = "/sw/MIRROR",
        dist = fake_dist,
        defaults = "release",
        dryRun = False,
        fetchRepos = False,
        architecture = "slc7_x86-64"
      )
      doInit(args)
      self.assertEqual(mock_git.mock_calls, CLONE_EVERYTHING)
      mock_path.exists.assert_has_calls([call('.'), call('/sw/MIRROR'), call('/alidist'), call('./AliRoot')])

      # Force fetch repos
      mock_git.reset_mock()
      mock_path.reset_mock()
      args.fetchRepos = True
      doInit(args)
      self.assertEqual(mock_git.mock_calls, CLONE_EVERYTHING)
      mock_path.exists.assert_has_calls([call('.'), call('/sw/MIRROR'), call('/alidist'), call('./AliRoot')])


if __name__ == '__main__':
    unittest.main()
