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
            mock_getstatusoutput.assert_called_with(["docker", "container", "exec", "container-id", "bash", "-c", "echo foo"], cwd=None)
        mock_getstatusoutput.assert_called_with("docker container kill container-id")

        mock_getoutput.reset_mock()
        mock_getstatusoutput.reset_mock()
        with DockerRunner("") as getstatusoutput_docker:
            mock_getoutput.assert_not_called()
            getstatusoutput_docker("echo foo")
            mock_getstatusoutput.assert_called_with("/bin/bash -c 'echo foo'", cwd=None)
            mock_getstatusoutput.reset_mock()
        mock_getstatusoutput.assert_not_called()

    @mock.patch("alibuild_helpers.cmd.getoutput")
    @mock.patch("alibuild_helpers.cmd.getstatusoutput")
    def test_DockerRunner_with_env_vars(self, mock_getstatusoutput, mock_getoutput):
        # Test that environment variables are properly injected into docker exec commands.
        mock_getoutput.side_effect = lambda cmd: "container-id\n"
        
        # Test with environment variables
        extra_env = {"TEST_VAR": "test_value", "ANOTHER_VAR": "another_value"}
        with DockerRunner("image", extra_env=extra_env) as getstatusoutput_docker:
            # Verify container creation includes environment variables
            mock_getoutput.assert_called_with(["docker", "run", "--detach", 
                                               "-e", "TEST_VAR=test_value",
                                               "-e", "ANOTHER_VAR=another_value",
                                               "--rm", "--entrypoint=", "image", "sleep", "inf"])
            
            # Test that exec command includes environment variables
            getstatusoutput_docker("echo test")
            mock_getstatusoutput.assert_called_with(["docker", "container", "exec", 
                                                     "-e", "TEST_VAR=test_value",
                                                     "-e", "ANOTHER_VAR=another_value", 
                                                     "container-id", "bash", "-c", "echo test"], cwd=None)

        # Test host execution with environment variables
        mock_getoutput.reset_mock()
        mock_getstatusoutput.reset_mock()
        with DockerRunner("", extra_env=extra_env) as getstatusoutput_docker:
            mock_getoutput.assert_not_called()
            getstatusoutput_docker("echo test")
            mock_getstatusoutput.assert_called_with("env TEST_VAR=test_value ANOTHER_VAR=another_value /bin/bash -c 'echo test'", cwd=None)

    @mock.patch("alibuild_helpers.cmd.getoutput")
    @mock.patch("alibuild_helpers.cmd.getstatusoutput")
    def test_DockerRunner_multiline_env_var(self, mock_getstatusoutput, mock_getoutput):
        multiline_value = "line1\nline2\nline3"
        extra_env = {"MULTILINE_VAR": multiline_value}
        
        with DockerRunner("", extra_env=extra_env) as getstatusoutput_docker:
            mock_getoutput.assert_not_called()
            getstatusoutput_docker("echo test")
            mock_getstatusoutput.assert_called_with("env MULTILINE_VAR='line1\nline2\nline3' /bin/bash -c 'echo test'", cwd=None)

    @mock.patch("alibuild_helpers.cmd.getoutput")
    @mock.patch("alibuild_helpers.cmd.getstatusoutput")
    def test_DockerRunner_env_var_with_semicolon(self, mock_getstatusoutput, mock_getoutput):
        semicolon_value = "value1;value2;value3"
        extra_env = {"SEMICOLON_VAR": semicolon_value}
        
        with DockerRunner("", extra_env=extra_env) as getstatusoutput_docker:
            mock_getoutput.assert_not_called()
            getstatusoutput_docker("echo test")
            mock_getstatusoutput.assert_called_with("env SEMICOLON_VAR='value1;value2;value3' /bin/bash -c 'echo test'", cwd=None)


if __name__ == '__main__':
    unittest.main()
