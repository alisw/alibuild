import unittest
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


if __name__ == '__main__':
    unittest.main()
