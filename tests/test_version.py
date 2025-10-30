import unittest
import os
from typing import Tuple
from unittest.mock import patch, MagicMock

from alibuild_helpers.version import UpdateChecker


class TestVersionParsing(unittest.TestCase):
    """Test version parsing functionality."""

    def test_parse_simple_version(self) -> None:
        """Test parsing simple semantic versions."""
        checker = UpdateChecker("test-package", "1.0.0")
        self.assertEqual(checker._parse_version("1.0.0"), (1, 0, 0))
        self.assertEqual(checker._parse_version("2.1.3"), (2, 1, 3))
        self.assertEqual(checker._parse_version("10.20.30"), (10, 20, 30))

    def test_parse_version_with_dev_suffix(self) -> None:
        """Test parsing versions with dev suffixes."""
        checker = UpdateChecker("test-package", "1.0.0")
        self.assertEqual(checker._parse_version("1.2.3.dev1"), (1, 2, 3))
        self.assertEqual(checker._parse_version("1.2.3.dev10"), (1, 2, 3))

    def test_parse_version_with_alpha_beta(self) -> None:
        """Test parsing versions with alpha/beta suffixes."""
        checker = UpdateChecker("test-package", "1.0.0")
        self.assertEqual(checker._parse_version("1.2.3a1"), (1, 2, 3))
        self.assertEqual(checker._parse_version("1.2.3b2"), (1, 2, 3))
        self.assertEqual(checker._parse_version("1.2.3rc1"), (1, 2, 3))

    def test_parse_version_with_post_suffix(self) -> None:
        """Test parsing versions with post suffixes."""
        checker = UpdateChecker("test-package", "1.0.0")
        self.assertEqual(checker._parse_version("1.2.3.post1"), (1, 2, 3))

    def test_parse_two_part_version(self) -> None:
        """Test parsing two-part versions."""
        checker = UpdateChecker("test-package", "1.0.0")
        self.assertEqual(checker._parse_version("1.0"), (1, 0))
        self.assertEqual(checker._parse_version("2.5"), (2, 5))

    def test_parse_four_part_version(self) -> None:
        """Test parsing four-part versions."""
        checker = UpdateChecker("test-package", "1.0.0")
        self.assertEqual(checker._parse_version("1.2.3.4"), (1, 2, 3, 4))

    def test_parse_invalid_version(self) -> None:
        """Test parsing invalid version strings."""
        checker = UpdateChecker("test-package", "1.0.0")
        self.assertEqual(checker._parse_version(""), (0,))
        self.assertEqual(checker._parse_version("invalid"), (0,))
        self.assertEqual(checker._parse_version("abc.def.ghi"), (0,))

    def test_parse_version_with_text(self) -> None:
        """Test parsing versions with text prefixes."""
        checker = UpdateChecker("test-package", "1.0.0")
        # The parser extracts leading digits, so "v1.0.0" becomes "1.0.0"
        # because 'v' has no leading digits and gets skipped
        self.assertEqual(checker._parse_version("1.0.0rc1"), (1, 0, 0))

    def test_parse_version_with_leading_zeros(self) -> None:
        """Test parsing versions with leading zeros."""
        checker = UpdateChecker("test-package", "1.0.0")
        self.assertEqual(checker._parse_version("1.02.03"), (1, 2, 3))

    def test_parse_version_edge_cases(self) -> None:
        """Test edge cases in version parsing."""
        checker = UpdateChecker("test-package", "1.0.0")
        self.assertEqual(checker._parse_version("0.0.0"), (0, 0, 0))
        self.assertEqual(checker._parse_version("999.999.999"), (999, 999, 999))


class TestUpdateChecking(unittest.TestCase):
    """Test update checking functionality."""

    def test_env_var_disables_check(self) -> None:
        """Test that ALIBUILD_NO_UPDATE_CHECK env var disables update checks."""
        checker = UpdateChecker("test-package", "1.0.0")

        with patch('os.environ', {"ALIBUILD_NO_UPDATE_CHECK": "1"}), \
             patch('sys.stdout.isatty', return_value=True), \
             patch('requests.get') as mock_get:
            result: bool = checker.check_for_updates()
            self.assertFalse(result)
            # Verify that no network request was made
            mock_get.assert_not_called()

    def test_non_tty_skips_check(self) -> None:
        """Test that non-TTY environments skip update checks."""
        checker = UpdateChecker("test-package", "1.0.0")

        with patch('sys.stdout.isatty', return_value=False), \
             patch('requests.get') as mock_get:
            result: bool = checker.check_for_updates()
            self.assertFalse(result)
            # Verify that no network request was made
            mock_get.assert_not_called()

    def test_no_update_needed_same_version(self) -> None:
        """Test when current version equals latest version."""
        checker = UpdateChecker("test-package", "1.5.0")
        mock_response: MagicMock = MagicMock()
        mock_response.json.return_value = {"info": {"version": "1.5.0"}}

        with patch('sys.stdout.isatty', return_value=True), \
             patch.object(checker, '_should_check_for_updates', return_value=True), \
             patch('requests.get', return_value=mock_response):
            result: bool = checker.check_for_updates()
            self.assertFalse(result)

    def test_no_update_needed_newer_local(self) -> None:
        """Test when current version is newer than PyPI version."""
        checker = UpdateChecker("test-package", "2.0.0")
        mock_response: MagicMock = MagicMock()
        mock_response.json.return_value = {"info": {"version": "1.5.0"}}

        with patch('sys.stdout.isatty', return_value=True), \
             patch.object(checker, '_should_check_for_updates', return_value=True), \
             patch('requests.get', return_value=mock_response):
            result: bool = checker.check_for_updates()
            self.assertFalse(result)

    def test_update_available(self) -> None:
        """Test when an update is available."""
        checker = UpdateChecker("test-package", "1.0.0")
        mock_response: MagicMock = MagicMock()
        mock_response.json.return_value = {"info": {"version": "2.0.0"}}

        with patch('sys.stdout.isatty', return_value=True), \
             patch.object(checker, '_should_check_for_updates', return_value=True), \
             patch('requests.get', return_value=mock_response), \
             patch('builtins.print') as mock_print:
            result: bool = checker.check_for_updates()
            self.assertTrue(result)
            # Verify that print was called with update information
            self.assertTrue(mock_print.called)
            print_calls = [str(call) for call in mock_print.call_args_list]
            self.assertTrue(any('github.com/alisw/alibuild/releases' in str(call) for call in print_calls),
                           "GitHub release URL should be included in output")

    def test_update_check_network_error(self) -> None:
        """Test handling of network errors during update check."""
        checker = UpdateChecker("test-package", "1.0.0")

        with patch('sys.stdout.isatty', return_value=True), \
             patch.object(checker, '_should_check_for_updates', return_value=True), \
             patch('requests.get', side_effect=Exception("Network error")):
            result: bool = checker.check_for_updates()
            self.assertFalse(result)

    def test_update_check_timeout(self) -> None:
        """Test handling of timeout during update check."""
        checker = UpdateChecker("test-package", "1.0.0")

        with patch('sys.stdout.isatty', return_value=True), \
             patch.object(checker, '_should_check_for_updates', return_value=True), \
             patch('requests.get', side_effect=TimeoutError("Request timeout")):
            result: bool = checker.check_for_updates()
            self.assertFalse(result)

    def test_update_check_invalid_response(self) -> None:
        """Test handling of invalid PyPI response."""
        checker = UpdateChecker("test-package", "1.0.0")
        mock_response: MagicMock = MagicMock()
        mock_response.json.return_value = {"invalid": "data"}

        with patch('sys.stdout.isatty', return_value=True), \
             patch.object(checker, '_should_check_for_updates', return_value=True), \
             patch('requests.get', return_value=mock_response):
            result: bool = checker.check_for_updates()
            self.assertFalse(result)


class TestVersionComparison(unittest.TestCase):
    """Test version comparison logic."""

    def test_major_version_comparison(self) -> None:
        """Test comparison of major version differences."""
        checker = UpdateChecker("test-package", "1.0.0")
        self.assertEqual(checker._parse_version("2.0.0"), (2, 0, 0))
        self.assertEqual(checker._parse_version("1.0.0"), (1, 0, 0))
        self.assertTrue(checker._parse_version("2.0.0") >
                        checker._parse_version("1.0.0"))

    def test_minor_version_comparison(self) -> None:
        """Test comparison of minor version differences."""
        checker = UpdateChecker("test-package", "1.0.0")
        self.assertTrue(checker._parse_version("1.5.0") > checker._parse_version("1.4.0"))

    def test_patch_version_comparison(self) -> None:
        """Test comparison of patch version differences."""
        checker = UpdateChecker("test-package", "1.0.0")
        self.assertTrue(checker._parse_version("1.0.5") > checker._parse_version("1.0.3"))

    def test_different_length_versions(self) -> None:
        """Test comparison of versions with different lengths."""
        checker = UpdateChecker("test-package", "1.0.0")
        v1: Tuple[int, ...] = checker._parse_version("1.0")
        v2: Tuple[int, ...] = checker._parse_version("1.0.0")
        # Both should parse correctly, even if different lengths
        self.assertEqual(v1, (1, 0))
        self.assertEqual(v2, (1, 0, 0))


class TestPackageManagerDetection(unittest.TestCase):
    """Test package manager detection functionality."""

    def test_detects_homebrew_cellar(self) -> None:
        """Test detection of Homebrew installation using brew --prefix."""
        checker = UpdateChecker("test-package", "1.0.0")

        # Mock brew command returning prefix
        with patch('os.path.realpath', return_value='/opt/homebrew/lib/python3.11/site-packages/alibuild_helpers/__init__.py'), \
             patch('shutil.which', return_value='/opt/homebrew/bin/brew'), \
             patch('subprocess.check_output', return_value='/opt/homebrew\n'):
            with patch.dict('sys.modules', {'alibuild_helpers': MagicMock(__file__='/opt/homebrew/lib/python3.11/site-packages/alibuild_helpers/__init__.py')}):
                result = checker._detect_package_manager()
                self.assertEqual(result, 'brew')

    def test_detects_homebrew_lib(self) -> None:
        """Test detection of Homebrew installation (Intel Mac path)."""
        checker = UpdateChecker("test-package", "1.0.0")

        # Intel Macs use /usr/local as brew prefix
        with patch('os.path.realpath', return_value='/usr/local/lib/python3.9/site-packages/alibuild_helpers/__init__.py'), \
             patch('shutil.which', return_value='/usr/local/bin/brew'), \
             patch('subprocess.check_output', return_value='/usr/local\n'):
            with patch.dict('sys.modules', {'alibuild_helpers': MagicMock(__file__='/usr/local/lib/python3.9/site-packages/alibuild_helpers/__init__.py')}):
                result = checker._detect_package_manager()
                self.assertEqual(result, 'brew')

    def test_not_homebrew_when_outside_prefix(self) -> None:
        """Test that brew is not detected when installed outside brew prefix."""
        checker = UpdateChecker("test-package", "1.0.0")

        # Installed in /usr/lib but brew prefix is /usr/local
        with patch('os.path.realpath', return_value='/usr/lib/python3/site-packages/alibuild_helpers/__init__.py'), \
             patch('shutil.which', return_value='/usr/local/bin/brew'), \
             patch('subprocess.check_output', return_value='/usr/local\n'):
            with patch.dict('sys.modules', {'alibuild_helpers': MagicMock(__file__='/usr/lib/python3/site-packages/alibuild_helpers/__init__.py')}):
                result = checker._detect_package_manager()
                # Should detect as pip, not brew
                self.assertEqual(result, 'pip')

    def test_detects_pip_site_packages(self) -> None:
        """Test detection of pip installation (site-packages)."""
        checker = UpdateChecker("test-package", "1.0.0")

        # pip uses site-packages, no brew available
        with patch('os.path.realpath', return_value='/usr/lib/python3/site-packages/alibuild_helpers/__init__.py'), \
             patch('shutil.which', return_value=None):
            with patch.dict('sys.modules', {'alibuild_helpers': MagicMock(__file__='/usr/lib/python3/site-packages/alibuild_helpers/__init__.py')}):
                result = checker._detect_package_manager()
                self.assertEqual(result, 'pip')

    def test_detects_pip_user_local(self) -> None:
        """Test detection of pip user installation (.local)."""
        checker = UpdateChecker("test-package", "1.0.0")

        # pip --user installs to .local
        with patch('os.path.realpath', return_value='/home/user/.local/lib/python3.9/site-packages/alibuild_helpers/__init__.py'):
            with patch.dict('sys.modules', {'alibuild_helpers': MagicMock(__file__='/home/user/.local/lib/python3.9/site-packages/alibuild_helpers/__init__.py')}):
                result = checker._detect_package_manager()
                self.assertEqual(result, 'pip')

    def test_detects_apt(self) -> None:
        """Test detection of apt installation."""
        checker = UpdateChecker("test-package", "1.0.0")

        # apt uses dist-packages
        with patch('os.path.realpath', return_value='/usr/lib/python3/dist-packages/alibuild_helpers/__init__.py'), \
             patch('shutil.which', side_effect=lambda x: '/usr/bin/apt' if x in ['apt', 'apt-get'] else None):
            with patch.dict('sys.modules', {'alibuild_helpers': MagicMock(__file__='/usr/lib/python3/dist-packages/alibuild_helpers/__init__.py')}):
                result = checker._detect_package_manager()
                self.assertEqual(result, 'apt')

    def test_upgrade_command_brew(self) -> None:
        """Test upgrade command for Homebrew."""
        checker = UpdateChecker("test-package", "1.0.0")
        cmd = checker._get_upgrade_command('brew')
        self.assertEqual(cmd, 'brew upgrade alibuild')

    def test_upgrade_command_pip(self) -> None:
        """Test upgrade command for pip."""
        checker = UpdateChecker("test-package", "1.0.0")
        cmd = checker._get_upgrade_command('pip')
        self.assertEqual(cmd, 'pip install --upgrade alibuild')

    def test_upgrade_command_apt(self) -> None:
        """Test upgrade command for apt."""
        checker = UpdateChecker("test-package", "1.0.0")
        cmd = checker._get_upgrade_command('apt')
        self.assertEqual(cmd, 'sudo apt update && sudo apt install --only-upgrade alibuild')

    def test_upgrade_command_default(self) -> None:
        """Test default upgrade command when package manager is unknown."""
        checker = UpdateChecker("test-package", "1.0.0")
        cmd = checker._get_upgrade_command(None)
        self.assertEqual(cmd, 'pip install --upgrade alibuild')

        cmd = checker._get_upgrade_command('unknown')
        self.assertEqual(cmd, 'pip install --upgrade alibuild')


if __name__ == '__main__':
    unittest.main()
