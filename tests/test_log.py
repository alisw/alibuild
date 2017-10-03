from __future__ import print_function
# Assuming you are using the mock library to ... mock things
try:
    from unittest.mock import patch, call  # In Python 3, mock is built-in
except ImportError:
    from mock import patch, call  # Python 2

from alibuild_helpers.log import dieOnError, ProgressPrint

import mock
import unittest
import traceback
from time import sleep

class LogTestCase(unittest.TestCase):
    @patch('alibuild_helpers.log.error')
    @patch('alibuild_helpers.log.sys')
    def test_dieOnError(self, mock_sys, mock_error):
      dieOnError(True, "Message")
      mock_sys.exit.assert_called_once_with(1)
      mock_error.assert_called_once_with("Message")
      mock_error.reset_mock()
      dieOnError(False, "Message")
      mock_error.assert_not_called()

    @patch('alibuild_helpers.log.sys.stderr')
    def test_ProgressPrint(self, mock_stderr):
      mock_stderr.write.side_effect = lambda x: True
      p = ProgressPrint("begin")
      p("First message")
      sleep(1)
      p("Has percentage: 80%")
      sleep(1)
      p("Last message")
      p.end()

if __name__ == '__main__':
  unittest.main()
