from __future__ import print_function
# Assuming you are using the mock library to ... mock things
from unittest import mock

from alibuild_helpers.cmd import execute, DockerRunner

import unittest


@mock.patch("alibuild_helpers.cmd.BASH", new="/bin/bash")
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

    @mock.patch("alibuild_helpers.cmd.getoutput")
    @mock.patch("alibuild_helpers.cmd.getstatusoutput")
    def test_DockerRunner(self, mock_getstatusoutput, mock_getoutput):
        mock_getoutput.side_effect = lambda cmd: "container-id\n"
        with DockerRunner("image", ["extra arg"]) as getstatusoutput_docker:
            mock_getoutput.assert_called_with(["docker", "run", "--detach", "--rm", "--entrypoint=",
                                               "extra arg", "image", "sleep", "inf"])
            getstatusoutput_docker("echo foo")
            mock_getstatusoutput.assert_called_with("docker container exec container-id bash -c 'echo foo'")
        mock_getstatusoutput.assert_called_with("docker container kill container-id")

        mock_getoutput.reset_mock()
        mock_getstatusoutput.reset_mock()
        with DockerRunner("") as getstatusoutput_docker:
            mock_getoutput.assert_not_called()
            getstatusoutput_docker("echo foo")
            mock_getstatusoutput.assert_called_with("/bin/bash -c 'echo foo'")
            mock_getstatusoutput.reset_mock()
        mock_getstatusoutput.assert_not_called()


if __name__ == '__main__':
    unittest.main()
