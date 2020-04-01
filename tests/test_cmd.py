from __future__ import print_function
# Assuming you are using the mock library to ... mock things
try:
    from unittest.mock import patch, call  # In Python 3, mock is built-in
except ImportError:
    from mock import patch, call  # Python 2

from alibuild_helpers.cmd import execute

import mock
import unittest
import traceback

class CmdTestCase(unittest.TestCase):
    @mock.patch("alibuild_helpers.cmd.debug")
    def test_execute(self, mock_debug):
      err = execute("echo foo", mock_debug)
      self.assertEqual(err, 0)
      self.assertEqual(mock_debug.mock_calls, [call('foo')])
      mock_debug.reset_mock()
      err = execute("echoo 2> /dev/null", mock_debug)
      self.assertEqual(err, 127)
      self.assertEqual(mock_debug.mock_calls, [])

if __name__ == '__main__':
  unittest.main()
