from __future__ import print_function
# Assuming you are using the mock library to ... mock things
try:
    from unittest.mock import patch, call  # In Python 3, mock is built-in
except ImportError:
    from mock import patch, call  # Python 2

from alibuild_helpers.init import doInit,parsePackagesDefinition

import mock
import unittest
import traceback

def can_do_git_clone(x):
  return 0

def valid_recipe(x):
  if "zlib" in x.url:
    return (0, {"package": "zlib",
                "source": "https://github.com/alisw/zlib",
                "version": "v1.0"}, "")
  elif "aliroot" in  x.url:
    return (0, {"package": "AliRoot",
                "source": "https://github.com/alisw/AliRoot",
                "version": "master"}, "")

CLONE_EVERYTHING = [
 call(u'git clone https://github.com/alisw/alidist -b master --reference sw/MIRROR/alidist alidist && cd alidist && git remote set-url --push origin https://github.com/alisw/alidist'),
 call(u'git clone https://github.com/alisw/zlib -b v1.0 --reference sw/MIRROR/zlib ./zlib && cd ./zlib && git remote set-url --push origin https://github.com/alisw/zlib'),
 call(u'git clone https://github.com/alisw/AliRoot -b v5-08-00 --reference sw/MIRROR/aliroot ./AliRoot && cd ./AliRoot && git remote set-url --push origin https://github.com/alisw/AliRoot')
]

class InitTestCase(unittest.TestCase):
    def test_packageDefinition(self):
      self.assertEqual(parsePackagesDefinition("AliRoot@v5-08-16,AliPhysics@v5-08-16-01"),
                       [{'ver': 'v5-08-16', 'name': 'AliRoot'},
                        {'ver': 'v5-08-16-01', 'name': 'AliPhysics'}])
      self.assertEqual(parsePackagesDefinition("AliRoot,AliPhysics@v5-08-16-01"),
                       [{'ver': '', 'name': 'AliRoot'},
                        {'ver': 'v5-08-16-01', 'name': 'AliPhysics'}])

    @mock.patch("alibuild_helpers.init.info")
    @mock.patch("alibuild_helpers.init.path")
    @mock.patch("alibuild_helpers.init.os")
    def test_doDryRunInit(self, mock_os, mock_path,  mock_info):
      fake_dist = {"repo": "alisw/alidist", "ver": "master"}
      self.assertRaises(SystemExit, doInit, setdir=".",
                                            configDir="alidist",
                                            pkgname="zlib,AliRoot@v5-08-00",
                                            referenceSources="sw/MIRROR",
                                            dist=fake_dist,
                                            dryRun=True)
      self.assertEqual(mock_info.mock_calls, [call('This will initialise local checkouts for zlib,AliRoot\n--dry-run / -n specified. Doing nothing.')])

    @mock.patch("alibuild_helpers.init.info")
    @mock.patch("alibuild_helpers.init.path")
    @mock.patch("alibuild_helpers.init.os")
    @mock.patch("alibuild_helpers.init.execute")
    @mock.patch("alibuild_helpers.init.parseRecipe")
    @mock.patch("alibuild_helpers.init.updateReferenceRepos")
    def test_doRealInit(self, mock_update_reference, mock_parse_recipe, mock_execute, mock_os, mock_path,  mock_info):
      fake_dist = {"repo": "alisw/alidist", "ver": "master"}
      mock_execute.side_effect = can_do_git_clone
      mock_parse_recipe.side_effect = valid_recipe
      mock_path.exists.side_effect = lambda x : False
      mock_os.mkdir.return_value = None
      doInit(setdir=".",
             configDir="alidist",
             pkgname="zlib,AliRoot@v5-08-00",
             referenceSources="sw/MIRROR",
             dist=fake_dist,
             dryRun=False)
      mock_execute.assert_called_with("git clone https://github.com/alisw/AliRoot -b v5-08-00 --reference sw/MIRROR/aliroot ./AliRoot && cd ./AliRoot && git remote set-url --push origin https://github.com/alisw/AliRoot")
      self.assertEqual(mock_execute.mock_calls, CLONE_EVERYTHING)
      mock_path.exists.assert_called_with("./AliRoot")


if __name__ == '__main__':
  unittest.main()
