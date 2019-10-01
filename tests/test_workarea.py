from __future__ import print_function
# Assumin you are using the mock library to ... mock things
try:
    from unittest.mock import patch, call, MagicMock  # In Python 3, mock is built-in
except ImportError:
    from mock import patch, call, MagicMock  # Python 2
try:
  from collections import OrderedDict
except ImportError:
  from ordereddict import OrderedDict

from alibuild_helpers.workarea import updateReferenceRepo, updateReferenceRepoSpec
from os.path import abspath, join
from os import getcwd

import re
import mock
import unittest
import traceback

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

def allow_git_clone(x, mock_git_clone, mock_git_fetch, **k):
  s = " ".join(x) if isinstance(x, list) else x
  if re.search("^git clone ", s):
    mock_git_clone()
  elif re.search("&& git fetch -f --tags", s):
    mock_git_fetch()
  return 0

class WorkareaTestCase(unittest.TestCase):

    @mock.patch("alibuild_helpers.workarea.getstatusoutput")
    @mock.patch("alibuild_helpers.workarea.execute")
    @mock.patch("alibuild_helpers.workarea.path")
    @mock.patch("alibuild_helpers.workarea.debug")
    @mock.patch("alibuild_helpers.workarea.os")
    @mock.patch("alibuild_helpers.workarea.is_writeable")
    def test_referenceSourceExistsNonWriteable(self, mock_is_writeable, mock_os, mock_debug, mock_path, mock_execute, mock_getstatusoutput):
      # Reference sources exists but cannot be written
      # The reference repo is set nevertheless but not updated
      mock_path.exists.side_effect = lambda x: True
      mock_is_writeable.side_effect = lambda x: False
      mock_os.path.join.side_effect = join
      mock_getstatusoutput.side_effect = allow_directory_creation
      mock_git_clone = MagicMock(return_value=None)
      mock_git_fetch = MagicMock(return_value=None)
      mock_execute.side_effect = lambda x, **k: allow_git_clone(x, mock_git_clone, mock_git_fetch, *k)
      spec = OrderedDict({"source": "https://github.com/alisw/AliRoot"})
      referenceSources = "sw/MIRROR"
      reference = abspath(referenceSources) + "/aliroot"
      mock_os.makedirs.reset_mock()
      mock_git_clone.reset_mock()
      mock_git_fetch.reset_mock()
      updateReferenceRepoSpec(referenceSources=referenceSources, p="AliRoot", spec=spec, fetch=True)
      mock_os.makedirs.assert_called_with('%s/sw/MIRROR' % getcwd())
      self.assertEqual(mock_git_fetch.call_count, 0, "Expected no calls to git fetch (called %d times instead)" % mock_git_fetch.call_count)
      self.assertEqual(mock_git_clone.call_count, 0, "Expected no calls to git clone (called %d times instead)" % mock_git_clone.call_count)
      self.assertEqual(spec.get("reference"), reference)
      self.assertEqual(True, call('Updating references.') in mock_debug.mock_calls)

    @mock.patch("alibuild_helpers.workarea.getstatusoutput")
    @mock.patch("alibuild_helpers.workarea.execute")
    @mock.patch("alibuild_helpers.workarea.path")
    @mock.patch("alibuild_helpers.workarea.debug")
    @mock.patch("alibuild_helpers.workarea.os")
    @mock.patch("alibuild_helpers.workarea.is_writeable")
    def test_referenceSourceExistsWriteable(self, mock_is_writeable, mock_os, mock_debug, mock_path, mock_execute, mock_getstatusoutput):
      # Reference sources exists and can be written
      # The reference repo is set nevertheless but not updated
      mock_path.exists.side_effect = lambda x: True
      mock_is_writeable.side_effect = lambda x: True
      mock_os.path.join.side_effect = join
      mock_getstatusoutput.side_effect = allow_directory_creation
      mock_git_clone = MagicMock(return_value=None)
      mock_git_fetch = MagicMock(return_value=None)
      mock_execute.side_effect = lambda x, **k: allow_git_clone(x, mock_git_clone, mock_git_fetch, *k)
      spec = OrderedDict({"source": "https://github.com/alisw/AliRoot"})
      referenceSources = "sw/MIRROR"
      reference = abspath(referenceSources) + "/aliroot"
      mock_os.makedirs.reset_mock()
      mock_git_clone.reset_mock()
      mock_git_fetch.reset_mock()
      updateReferenceRepoSpec(referenceSources=referenceSources, p="AliRoot", spec=spec, fetch=True)
      mock_os.makedirs.assert_called_with('%s/sw/MIRROR' % getcwd())
      self.assertEqual(mock_git_fetch.call_count, 1, "Expected one call to git fetch (called %d times instead)" % mock_git_fetch.call_count)
      self.assertEqual(mock_git_clone.call_count, 0, "Expected no calls to git clone (called %d times instead)" % mock_git_clone.call_count)
      self.assertEqual(spec.get("reference"), reference)
      self.assertEqual(True, call('Updating references.') in mock_debug.mock_calls)

    @mock.patch("alibuild_helpers.workarea.getstatusoutput")
    @mock.patch("alibuild_helpers.workarea.execute")
    @mock.patch("alibuild_helpers.workarea.path")
    @mock.patch("alibuild_helpers.workarea.debug")
    @mock.patch("alibuild_helpers.workarea.os")
    @mock.patch("alibuild_helpers.workarea.is_writeable")
    def test_referenceBasedirExistsWriteable(self, mock_is_writeable, mock_os, mock_debug, mock_path, mock_execute, mock_getstatusoutput):
      """
      The referenceSources directory exists and it's writeable
      Reference sources are already there
      """
      mock_path.exists.side_effect = lambda x: True
      mock_is_writeable.side_effect = lambda x: True
      mock_os.path.join.side_effect = join
      mock_getstatusoutput.side_effect = allow_directory_creation
      mock_git_clone = MagicMock(return_value=None)
      mock_git_fetch = MagicMock(return_value=None)
      mock_execute.side_effect = lambda x, **k: allow_git_clone(x, mock_git_clone, mock_git_fetch, *k)
      spec = OrderedDict({"source": "https://github.com/alisw/AliRoot"})
      referenceSources = "sw/MIRROR"
      reference = abspath(referenceSources) + "/aliroot"
      mock_os.makedirs.reset_mock()
      mock_git_clone.reset_mock()
      mock_git_fetch.reset_mock()
      updateReferenceRepo(referenceSources=referenceSources, p="AliRoot", spec=spec)
      mock_os.makedirs.assert_called_with('%s/sw/MIRROR' % getcwd())
      self.assertEqual(mock_git_fetch.call_count, 1, "Expected one call to git fetch (called %d times instead)" % mock_git_fetch.call_count)

    @mock.patch("alibuild_helpers.workarea.getstatusoutput")
    @mock.patch("alibuild_helpers.workarea.execute")
    @mock.patch("alibuild_helpers.workarea.path")
    @mock.patch("alibuild_helpers.workarea.debug")
    @mock.patch("alibuild_helpers.workarea.os")
    @mock.patch("alibuild_helpers.workarea.is_writeable")
    def test_referenceBasedirNotExistsWriteable(self, mock_is_writeable, mock_os, mock_debug, mock_path, mock_execute, mock_getstatusoutput):
      """
      The referenceSources directory exists and it's writeable
      Reference sources are not already there
      """
      mock_path.exists.side_effect = reference_sources_do_not_exists
      mock_is_writeable.side_effect = lambda x: False # not writeable
      mock_os.path.join.side_effect = join
      mock_os.makedirs.side_effect = lambda x: True
      mock_getstatusoutput.side_effect = allow_directory_creation
      mock_git_clone = MagicMock(return_value=None)
      mock_git_fetch = MagicMock(return_value=None)
      mock_execute.side_effect = lambda x, **k: allow_git_clone(x, mock_git_clone, mock_git_fetch, *k)
      spec = OrderedDict({"source": "https://github.com/alisw/AliRoot"})
      referenceSources = "sw/MIRROR"
      reference = abspath(referenceSources) + "/aliroot"
      mock_os.makedirs.reset_mock()
      mock_git_clone.reset_mock()
      mock_git_fetch.reset_mock()
      updateReferenceRepo(referenceSources=referenceSources, p="AliRoot", spec=spec)
      mock_path.exists.assert_called_with('%s/sw/MIRROR/aliroot' % getcwd())
      mock_os.makedirs.assert_called_with('%s/sw/MIRROR' % getcwd())
      self.assertEqual(mock_git_clone.call_count, 0, "Expected no calls to git clone (called %d times instead)" % mock_git_clone.call_count)

    @mock.patch("alibuild_helpers.workarea.getstatusoutput")
    @mock.patch("alibuild_helpers.workarea.execute")
    @mock.patch("alibuild_helpers.workarea.path")
    @mock.patch("alibuild_helpers.workarea.debug")
    @mock.patch("alibuild_helpers.workarea.os")
    @mock.patch("alibuild_helpers.workarea.is_writeable")
    def test_referenceSourceNotExistsWriteable(self, mock_is_writeable, mock_os, mock_debug, mock_path, mock_execute, mock_getstatusoutput):
      """
      The referenceSources directory does not exist and it's writeable
      Reference sources are not already there
      """
      mock_path.exists.side_effect = reference_sources_do_not_exists
      mock_is_writeable.side_effect = lambda x: True  # is writeable
      mock_os.path.join.side_effect = join
      mock_os.makedirs.side_effect = lambda x: True
      mock_getstatusoutput.side_effect = allow_directory_creation
      mock_git_clone = MagicMock(return_value=None)
      mock_git_fetch = MagicMock(return_value=None)
      mock_execute.side_effect = lambda x, **k: allow_git_clone(x, mock_git_clone, mock_git_fetch, *k)
      spec = OrderedDict({"source": "https://github.com/alisw/AliRoot"})
      referenceSources = "sw/MIRROR"
      reference = abspath(referenceSources) + "/aliroot"
      mock_os.makedirs.reset_mock()
      mock_git_clone.reset_mock()
      mock_git_fetch.reset_mock()
      updateReferenceRepo(referenceSources=referenceSources, p="AliRoot", spec=spec)
      mock_path.exists.assert_called_with('%s/sw/MIRROR/aliroot' % getcwd())
      mock_os.makedirs.assert_called_with('%s/sw/MIRROR' % getcwd())
      self.assertEqual(mock_git_clone.call_count, 1, "Expected only one call to git clone (called %d times instead)" % mock_git_clone.call_count)


if __name__ == '__main__':
  unittest.main()
