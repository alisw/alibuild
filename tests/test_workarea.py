from __future__ import print_function
# Assumin you are using the mock library to ... mock things
try:
    from unittest.mock import patch, call  # In Python 3, mock is built-in
except ImportError:
    from mock import patch, call  # Python 2

from alibuild_helpers.workarea import updateReferenceRepos
from os.path import abspath
from os import getcwd

import mock
import unittest
import traceback

def reference_sources_cannot_be_written(x, y):
  return False

def reference_sources_can_be_written(x, y):
  return True

def reference_sources_exists(x):
  return True

def reference_sources_do_not_exists(x):
  if x.endswith("/aliroot"):
    return False
  return True

def reference_basedir_exists(x):
  if x.endswith("/aliroot"):
    return False
  return {
    "sw": True,
    "sw/MIRROR": False
  }[x]

def allow_directory_creation(x):
  if x.startswith("mkdir"):
    return (0, "")
  return (1, "")

def allow_git_clone(x):
  return 0

class WorkareaTestCase(unittest.TestCase):
    @mock.patch("alibuild_helpers.workarea.getstatusoutput")
    @mock.patch("alibuild_helpers.workarea.execute")
    @mock.patch("alibuild_helpers.workarea.path")
    @mock.patch("alibuild_helpers.workarea.debug")
    @mock.patch("alibuild_helpers.workarea.os")
    def test_referenceSourceExistsNonWriteable(self, mock_os, mock_debug, mock_path, mock_execute, mock_getstatusoutput):
      # Reference sources exists but cannot be written
      # The reference repo is set nethertheless but not updated
      mock_path.exists.return_value = reference_sources_exists
      mock_os.access.side_effect = reference_sources_cannot_be_written
      spec ={"source": "https://github.com/alisw/AliRoot"}
      referenceSources = "sw/MIRROR"
      reference = abspath(referenceSources) + "/aliroot"
      updateReferenceRepos(referenceSources=referenceSources,  p="AliRoot", spec=spec)
      self.assertEqual(mock_debug.mock_calls,
                       [call('Updating references.'),
                        call('Using %s as reference for AliRoot.' % reference)])
      self.assertEqual(spec["reference"], reference)
      mock_getstatusoutput.assert_not_called()
      mock_execute.assert_not_called()

    @mock.patch("alibuild_helpers.workarea.getstatusoutput")
    @mock.patch("alibuild_helpers.workarea.execute")
    @mock.patch("alibuild_helpers.workarea.path")
    @mock.patch("alibuild_helpers.workarea.debug")
    @mock.patch("alibuild_helpers.workarea.os")
    def test_referenceSourceExistsWriteable(self, mock_os, mock_debug, mock_path, mock_execute, mock_getstatusoutput):
      # Reference sources exists but cannot be written
      # The reference repo is set nethertheless but not updated
      mock_path.exists.side_effect = reference_sources_exists
      mock_os.access.side_effect = reference_sources_can_be_written
      mock_getstatusoutput.side_effect = allow_directory_creation
      mock_execute.side_effect = allow_git_clone
      spec ={"source": "https://github.com/alisw/AliRoot"}
      referenceSources = "sw/MIRROR"
      reference = abspath(referenceSources) + "/aliroot"
      updateReferenceRepos(referenceSources=referenceSources,  p="AliRoot", spec=spec)
      self.assertEqual(mock_debug.mock_calls,
                       [call('Updating references.')])
      self.assertEqual(spec["reference"], reference)
      mock_getstatusoutput.assert_called_with('mkdir -p %s/sw/MIRROR' % getcwd())
      mock_execute.assert_called_with('cd %s/sw/MIRROR/aliroot && git fetch --tags https://github.com/alisw/AliRoot 2>&1 && git fetch https://github.com/alisw/AliRoot 2>&1' % getcwd())
      self.assertTrue("fetch" in mock_execute.call_args[0][0])

    @mock.patch("alibuild_helpers.workarea.getstatusoutput")
    @mock.patch("alibuild_helpers.workarea.execute")
    @mock.patch("alibuild_helpers.workarea.path")
    @mock.patch("alibuild_helpers.workarea.debug")
    @mock.patch("alibuild_helpers.workarea.os")
    def test_referenceBasedirExistsWriteable(self, mock_os, mock_debug, mock_path, mock_execute, mock_getstatusoutput):
      """
      The referenceSources directory exists and it's writeable
      Reference sources are already there
      """
      mock_path.exists.side_effect = reference_basedir_exists
      mock_os.access.side_effect = reference_sources_can_be_written
      mock_getstatusoutput.side_effect = allow_directory_creation
      mock_execute.side_effect = allow_git_clone
      spec ={"source": "https://github.com/alisw/AliRoot"}
      referenceSources = "sw/MIRROR"
      reference = abspath(referenceSources) + "/aliroot"
      updateReferenceRepos(referenceSources=referenceSources,  p="AliRoot", spec=spec)
      mock_getstatusoutput.assert_called_with() # Directory was requested to be created
      mock_execute.assert_called_with() # Clone was requested to be done
      print(mock_execute.mock_calls)
      self.assertTrue("clone" in mock_execute.call_args[0][0])

    @mock.patch("alibuild_helpers.workarea.getstatusoutput")
    @mock.patch("alibuild_helpers.workarea.execute")
    @mock.patch("alibuild_helpers.workarea.path")
    @mock.patch("alibuild_helpers.workarea.debug")
    @mock.patch("alibuild_helpers.workarea.os")
    def test_referenceBasedirExistsWriteable(self, mock_os, mock_debug, mock_path, mock_execute, mock_getstatusoutput):
      """
      The referenceSources directory exists and it's writeable
      Reference sources are not already there
      """
      mock_path.exists.side_effect = reference_sources_do_not_exists
      mock_os.access.side_effect = reference_sources_can_be_written
      mock_getstatusoutput.side_effect = allow_directory_creation
      mock_execute.side_effect = allow_git_clone
      spec ={"source": "https://github.com/alisw/AliRoot"}
      referenceSources = "sw/MIRROR"
      reference = abspath(referenceSources) + "/aliroot"
      updateReferenceRepos(referenceSources=referenceSources,  p="AliRoot", spec=spec)
      mock_path.exists.assert_called_with('%s/sw/MIRROR/aliroot' % getcwd())
      mock_getstatusoutput.assert_called_with('mkdir -p %s/sw/MIRROR' % getcwd())
      mock_execute.assert_called_with('git clone --bare https://github.com/alisw/AliRoot %s/sw/MIRROR/aliroot' % getcwd()) # Clone was requested to be done
      self.assertTrue("clone" in mock_execute.call_args[0][0])

    @mock.patch("alibuild_helpers.workarea.getstatusoutput")
    @mock.patch("alibuild_helpers.workarea.execute")
    @mock.patch("alibuild_helpers.workarea.path")
    @mock.patch("alibuild_helpers.workarea.debug")
    @mock.patch("alibuild_helpers.workarea.os")
    def test_referenceSourceNotExistsWriteable(self, mock_os, mock_debug, mock_path, mock_execute, mock_getstatusoutput):
      """
      The referenceSources directory exists and it's writeable
      Reference sources are not already there
      """
      mock_path.exists.side_effect = reference_sources_do_not_exists
      mock_os.access.side_effect = reference_sources_can_be_written
      mock_getstatusoutput.side_effect = allow_directory_creation
      mock_execute.side_effect = allow_git_clone
      spec ={"source": "https://github.com/alisw/AliRoot"}
      referenceSources = "sw/MIRROR"
      reference = abspath(referenceSources) + "/aliroot"
      updateReferenceRepos(referenceSources=referenceSources,  p="AliRoot", spec=spec)
      mock_path.exists.assert_called_with('%s/sw/MIRROR/aliroot' % getcwd())
      mock_getstatusoutput.assert_called_with('mkdir -p %s/sw/MIRROR' % getcwd())
      mock_execute.assert_called_with('git clone --bare https://github.com/alisw/AliRoot %s/sw/MIRROR/aliroot' % getcwd()) # Clone was requested to be done
      self.assertTrue("clone" in mock_execute.call_args[0][0])


if __name__ == '__main__':
  unittest.main()
