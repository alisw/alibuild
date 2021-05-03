from __future__ import print_function
# Assuming you are using the mock library to ... mock things
try:
    from unittest.mock import patch  # In Python 3, mock is built-in
except ImportError:
    from mock import patch  # Python 2

from alibuild_helpers.log import dieOnError, ProgressPrint

import unittest
from time import sleep

class LogTestCase(unittest.TestCase):
    @patch('alibuild_helpers.log.error')
    @patch('alibuild_helpers.log.sys')
    def test_dieOnError(self, mock_sys, mock_error):
      dieOnError(True, "Message")
      mock_sys.exit.assert_called_once_with(1)
      mock_error.assert_called_once_with("%s", "Message")
      mock_error.reset_mock()
      dieOnError(False, "Message")
      mock_error.assert_not_called()

    @patch('alibuild_helpers.log.sys.stderr')
    def test_ProgressPrint(self, mock_stderr):
      mock_stderr.write.side_effect = lambda x: True
      sleep_time = 0.6
      p = ProgressPrint("begin")
      p("%s", "First message")
      self.assertEqual(p.percent, -1)
      sleep(sleep_time)
      p("%s", "Has percentage: 80%")
      self.assertEqual(p.percent, 80)
      sleep(sleep_time)
      p("%s", "No percentage")
      self.assertEqual(p.percent, 80)  # unchanged
      sleep(sleep_time)
      p("%s", "[100/200] Building CXX object this/is/a/ninja/test")
      self.assertEqual(p.percent, 50)
      sleep(sleep_time)
      p("%s", "[100/0] Wrong-styled Ninja progress")
      self.assertEqual(p.percent, 50)  # unchanged
      sleep(sleep_time)
      p("%s", "Last message")
      p.end()

if __name__ == '__main__':
  unittest.main()
