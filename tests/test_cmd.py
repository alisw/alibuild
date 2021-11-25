from __future__ import print_function
# Assuming you are using the mock library to ... mock things
try:
    from unittest import mock  # In Python 3, mock is built-in
except ImportError:
    import mock  # Python 2

from alibuild_helpers.cmd import execute, dockerStatusOutput

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

    @mock.patch("alibuild_helpers.cmd.getstatusoutput")
    def test_dockerStatusOutput(self, mock_getstatusoutput):
        dockerStatusOutput(cmd="echo foo", dockerImage="image", executor=mock_getstatusoutput)
        self.assertEqual(mock_getstatusoutput.mock_calls,
                         [mock.call("docker run --rm --entrypoint= image bash -c 'echo foo'")])


if __name__ == '__main__':
    unittest.main()
