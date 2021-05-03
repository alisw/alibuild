from __future__ import print_function
# Assuming you are using the mock library to ... mock things
try:
    from unittest import mock  # In Python 3, mock is built-in
except ImportError:
    import mock  # Python 2

from alibuild_helpers.cmd import execute

import unittest

class CmdTestCase(unittest.TestCase):
    @mock.patch("alibuild_helpers.cmd.debug")
    def test_execute(self, mock_debug):
      err = execute("echo foo", mock_debug)
      self.assertEqual(err, 0)
      self.assertEqual(mock_debug.mock_calls, [mock.call("%s", "foo")])
      mock_debug.reset_mock()
      err = execute("echoo 2> /dev/null", mock_debug)
      self.assertEqual(err, 127)
      self.assertEqual(mock_debug.mock_calls, [])

if __name__ == '__main__':
  unittest.main()
