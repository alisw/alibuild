import unittest
from unittest.mock import MagicMock, patch

import logging

from alibuild_helpers.log import dieOnError, ProgressPrint, LogFormatter, redact_secrets


FAKE_KEY = ("-----BEGIN RSA PRIVATE KEY-----\nMIIEfakefakefake\nAAAAsecretbody\n"
            "-----END RSA PRIVATE KEY-----")


class LogTestCase(unittest.TestCase):
    def test_redact_docker_command(self) -> None:
        """The docker command line, joined unquoted, must not show the key."""
        cmd = " ".join(["docker", "run", "-e", "JALIEN_TOKEN_KEY=" + FAKE_KEY,
                        "-e", "ALICEO2_CCDB_AUTH_TOKEN=abc123", "-e", "ARCHITECTURE=slc9_x86-64",
                        "-e", "ALIBUILD_PREFER_SYSTEM_KEY=gcc", "image"])
        out = redact_secrets(cmd)
        self.assertNotIn("secretbody", out)
        self.assertNotIn("MIIEfake", out)
        self.assertNotIn("abc123", out)
        self.assertIn("ARCHITECTURE=slc9_x86-64", out)
        self.assertIn("ALIBUILD_PREFER_SYSTEM_KEY=gcc", out)
        self.assertIn("image", out)

    def test_redact_quoted(self) -> None:
        """Shell-quoted values are redacted whole, including the quotes."""
        out = redact_secrets("env GITHUB_TOKEN='tok en' JALIEN_TOKEN_KEY=\"%s\" bash" % FAKE_KEY)
        self.assertEqual(out.count("<redacted>"), 2)
        self.assertNotIn("tok en", out)
        self.assertNotIn("secretbody", out)
        self.assertTrue(out.endswith(" bash"))

    def test_redact_unterminated_key(self) -> None:
        """A key cut off before its END marker is redacted to the end."""
        out = redact_secrets("before " + FAKE_KEY.split("-----END")[0])
        self.assertEqual(out, "before -----BEGIN RSA PRIVATE KEY----- <redacted>")

    def test_formatter_redacts(self) -> None:
        """Everything going through the formatter is redacted, args included."""
        record = logging.LogRecord("alibuild", logging.DEBUG, __file__, 1,
                                   "Build command: %s", ("docker run -e JALIEN_TOKEN_KEY=" + FAKE_KEY,), None)
        out = LogFormatter("%(levelname)s: %(message)s").format(record)
        self.assertNotIn("secretbody", out)
        self.assertIn("Build command: docker run -e JALIEN_TOKEN_KEY=<redacted>", out)

    @patch("alibuild_helpers.log.error")
    @patch("alibuild_helpers.log.sys")
    def test_dieOnError(self, mock_sys, mock_error):
        """Check dieOnError dies on error."""
        dieOnError(True, "Message")
        mock_sys.exit.assert_called_once_with(1)
        mock_error.assert_called_once_with("%s", "Message")
        mock_sys.reset_mock()
        mock_error.reset_mock()
        dieOnError(False, "Message")
        mock_error.assert_not_called()
        mock_sys.exit.assert_not_called()

    @patch("sys.stdout.isatty", new=MagicMock(return_value=True))
    @patch("sys.stderr", new=MagicMock(return_value=True))
    def test_ProgressPrint(self) -> None:
        """Make sure ProgressPrint updates correctly."""
        # ProgressPrint only parses messages every 0.5s. Trick it into thinking
        # the last message was <interval> seconds ago.
        interval = 0.6
        p = ProgressPrint("begin")
        p("%s", "First message")
        self.assertEqual(p.percent, -1)
        p("%s", "[100/200] Update too fast")
        self.assertEqual(p.percent, -1)  # unchanged
        p.lasttime -= interval
        p("%s", "Has percentage: 80%")
        self.assertEqual(p.percent, 80)
        p.lasttime -= interval
        p("%s", "No percentage")
        self.assertEqual(p.percent, 80)  # unchanged
        p.lasttime -= interval
        p("%s", "[100/200] Building CXX object this/is/a/ninja/test")
        self.assertEqual(p.percent, 50)
        p.lasttime -= interval
        p("%s", "[100/0] Wrong-styled Ninja progress")
        self.assertEqual(p.percent, 50)  # unchanged
        p.lasttime -= interval
        p("%s", "Last message")
        p.end()

if __name__ == '__main__':
  unittest.main()
