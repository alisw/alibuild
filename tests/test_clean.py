from __future__ import print_function
from textwrap import dedent
# Assuming you are using the mock library to ... mock things
from unittest.mock import patch, call

from alibuild_helpers.clean import decideClean, doClean

import unittest

REALPATH_WITH_OBSOLETE_FILES = {
  "sw/BUILD/a-latest": "/sw/BUILD/f339115741c6ab9cf291d3210f44bee795c56e16",
  "sw/BUILD/b-latest": "/sw/BUILD/fcdfc2e1c9f0433c60b3b000e0e2737d297a9b1c",
  "sw/BUILD/f339115741c6ab9cf291d3210f44bee795c56e16": "/sw/BUILD/f339115741c6ab9cf291d3210f44bee795c56e16",
  "sw/BUILD/fcdfc2e1c9f0433c60b3b000e0e2737d297a9b1c": "/sw/BUILD/fcdfc2e1c9f0433c60b3b000e0e2737d297a9b1c",
  "sw/BUILD/somethingtodelete": "/sw/BUILD/somethingtodelete",
  "sw/osx_x86-64/b/latest": "/sw/osx_x86-64/b/v2",
  "sw/osx_x86-64/a/latest": "/sw/osx_x86-64/a/v1",
  "sw/osx_x86-64/b/latest-root6": "/sw/osx_x86-64/b/v4",
  "sw/osx_x86-64/b/latest-release": "/sw/osx_x86-64/b/v2",
  "sw/osx_x86-64/a/latest-release": "/sw/osx_x86-64/a/v1",
  "sw/osx_x86-64/b/v4": "/sw/osx_x86-64/b/v4",
  "sw/osx_x86-64/b/v3": "/sw/osx_x86-64/b/v3",
  "sw/osx_x86-64/b/v2": "/sw/osx_x86-64/b/v2",
  "sw/osx_x86-64/b/v1": "/sw/osx_x86-64/b/v1",
  "sw/osx_x86-64/a/v1": "/sw/osx_x86-64/a/v1"
}

GLOB_WITH_OBSOLETE_FILES = {
  "sw/BUILD/*-latest*": ["sw/BUILD/a-latest", "sw/BUILD/b-latest"],
  "sw/BUILD/*": ["sw/BUILD/a-latest",
                 "sw/BUILD/b-latest",
                 "sw/BUILD/f339115741c6ab9cf291d3210f44bee795c56e16",
                 "sw/BUILD/fcdfc2e1c9f0433c60b3b000e0e2737d297a9b1c",
                 "sw/BUILD/somethingtodelete"],
  "sw/osx_x86-64/*/": ["sw/osx_x86-64/a/", "sw/osx_x86-64/b/"],
  "sw/osx_x86-64/b/latest*": ["sw/osx_x86-64/b/latest",
                              "sw/osx_x86-64/b/latest-release",
                              "sw/osx_x86-64/b/latest-root6"],
  "sw/osx_x86-64/a/latest*": ["sw/osx_x86-64/a/latest", "sw/osx_x86-64/a/latest-release"],
  "sw/osx_x86-64/*/*": ["sw/osx_x86-64/a/latest", "sw/osx_x86-64/a/v1",
                        "sw/osx_x86-64/b/latest", "sw/osx_x86-64/b/v1",
                        "sw/osx_x86-64/b/v2", "sw/osx_x86-64/b/v3",
                        "sw/osx_x86-64/b/v4"],
  "sw/slc7_x86-64/*/": [],
  "sw/slc7_x86-64/*/*": []
}

READLINK_MOCKUP_DB = {
  "sw/BUILD/a-latest": "f339115741c6ab9cf291d3210f44bee795c56e16",
  "sw/BUILD/b-latest": "fcdfc2e1c9f0433c60b3b000e0e2737d297a9b1c"
}


class CleanTestCase(unittest.TestCase):
    @patch('alibuild_helpers.clean.glob')
    @patch('alibuild_helpers.clean.os')
    @patch('alibuild_helpers.clean.path')
    def test_decideClean(self, mock_path, mock_os, mock_glob):
        mock_path.realpath.side_effect = lambda x : REALPATH_WITH_OBSOLETE_FILES[x]
        mock_path.islink.side_effect = lambda x : "latest" in x
        mock_glob.glob.side_effect = lambda x : GLOB_WITH_OBSOLETE_FILES[x]
        mock_os.readlink.side_effect = lambda x : READLINK_MOCKUP_DB[x]
        toDelete = decideClean(workDir="sw", architecture="osx_x86-64", aggressiveCleanup=False)
        mock_os.readlink.assert_called_with("sw/BUILD/b-latest")
        mock_path.islink.assert_called_with("sw/osx_x86-64/b/v4")
        mock_path.exists.assert_called_with("sw/osx_x86-64/b/v3")
        self.assertEqual(toDelete, ['sw/TMP', 'sw/INSTALLROOT', 'sw/BUILD/somethingtodelete',
                                    'sw/osx_x86-64/b/v1', 'sw/osx_x86-64/b/v3'])
        toDelete = decideClean(workDir="sw", architecture="osx_x86-64", aggressiveCleanup=True)
        self.assertEqual(toDelete, ['sw/TMP', 'sw/INSTALLROOT', 'sw/TARS/osx_x86-64/store',
                                    'sw/SOURCES', 'sw/BUILD/somethingtodelete',
                                    'sw/osx_x86-64/b/v1', 'sw/osx_x86-64/b/v3'])
        toDelete = decideClean(workDir="sw", architecture="slc7_x86-64", aggressiveCleanup=True)
        self.assertEqual(toDelete, ['sw/TMP', 'sw/INSTALLROOT', 'sw/TARS/slc7_x86-64/store',
                                    'sw/SOURCES', 'sw/BUILD/somethingtodelete'])

    @patch('alibuild_helpers.clean.glob')
    @patch('alibuild_helpers.clean.os')
    @patch('alibuild_helpers.clean.path')
    @patch('alibuild_helpers.clean.shutil')
    @patch('alibuild_helpers.clean.log')
    def test_doClean(self, mock_log, mock_shutil, mock_path, mock_os, mock_glob):
        mock_path.realpath.side_effect = lambda x: REALPATH_WITH_OBSOLETE_FILES[x]
        mock_path.islink.side_effect = lambda x: "latest" in x
        mock_os.readlink.side_effect = lambda x: READLINK_MOCKUP_DB[x]

        files_to_delete = [
            "sw/TMP",
            "sw/INSTALLROOT",
            "sw/TARS/osx_x86-64/store",
            "sw/SOURCES",
            "sw/BUILD/somethingtodelete",
            "sw/osx_x86-64/b/v1",
            "sw/osx_x86-64/b/v3",
        ]
        remove_files_calls = list(map(call, files_to_delete))
        files_delete_formatarg = "\n".join(files_to_delete)

        mock_glob.glob.side_effect = lambda x: []
        # To get rid of default entries like sw/TMP, sw/INSTALLROOT.
        mock_path.exists.return_value = False

        with self.assertRaises(SystemExit) as cm:
          doClean(workDir="sw", architecture="osx_x86-64", aggressiveCleanup=True, dryRun=True)
        self.assertEqual(cm.exception.code, 0)
        mock_shutil.rmtree.assert_not_called()
        mock_log.info.assert_called_with("Nothing to delete.")
        mock_log.banner.assert_not_called()

        mock_log.banner.reset_mock()
        mock_log.info.reset_mock()

        mock_glob.glob.side_effect = lambda x: GLOB_WITH_OBSOLETE_FILES[x]
        mock_path.exists.return_value = True

        with self.assertRaises(SystemExit) as cm:
          doClean(workDir="sw", architecture="osx_x86-64", aggressiveCleanup=True, dryRun=True)
        self.assertEqual(cm.exception.code, 0)
        mock_shutil.rmtree.assert_not_called()
        mock_log.banner.assert_called_with("This %s delete the following directories:\n%s",
                                           "would", files_delete_formatarg)
        mock_log.info.assert_called_with("--dry-run / -n specified. Doing nothing.")

        mock_log.banner.reset_mock()
        mock_log.info.reset_mock()

        with self.assertRaises(SystemExit) as cm:
          doClean(workDir="sw", architecture="osx_x86-64", aggressiveCleanup=True, dryRun=False)
        self.assertEqual(cm.exception.code, 0)
        self.assertEqual(mock_shutil.rmtree.mock_calls, remove_files_calls)
        mock_log.banner.assert_called_with("This %s delete the following directories:\n%s",
                                           "will", files_delete_formatarg)
        mock_log.info.assert_not_called()

        mock_log.banner.reset_mock()
        mock_log.info.reset_mock()
        mock_shutil.rmtree.reset_mock()

        def failing_rmtree(directory):
            raise OSError("sentinel exception")

        mock_shutil.rmtree.side_effect = failing_rmtree

        with self.assertRaises(SystemExit) as cm:
          doClean(workDir="sw", architecture="osx_x86-64", aggressiveCleanup=True, dryRun=False)
        self.assertEqual(cm.exception.code, 1)
        # Make sure the function still attempts to delete all of the
        # directories, even if some fail.
        self.assertEqual(mock_shutil.rmtree.mock_calls, remove_files_calls)
        mock_log.banner.assert_called_with("This %s delete the following directories:\n%s",
                                           "will", files_delete_formatarg)
        mock_log.info.assert_not_called()


if __name__ == '__main__':
  unittest.main()
