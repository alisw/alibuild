import unittest
from unittest.mock import MagicMock, patch

from alibuild_helpers.log import dieOnError, ProgressPrint


class LogTestCase(unittest.TestCase):
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
    def test_ProgressPrint(self):
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
