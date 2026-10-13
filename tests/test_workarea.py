from os import getcwd
import unittest
from unittest.mock import patch, MagicMock  # In Python 3, mock is built-in
from collections import OrderedDict

from alibuild_helpers.workarea import updateReferenceRepoSpec
from alibuild_helpers.git import Git


MOCK_SPEC = OrderedDict((
    ("package", "AliRoot"),
    ("source", "https://github.com/alisw/AliRoot"),
    ("scm", Git()),
    ("is_devel_pkg", False),
))


@patch("alibuild_helpers.workarea.debug", new=MagicMock())
@patch("alibuild_helpers.git.clone_speedup_options",
       new=MagicMock(return_value=["--filter=blob:none"]))
class WorkareaTestCase(unittest.TestCase):

    @patch("os.path.exists")
    @patch("os.makedirs")
    @patch("alibuild_helpers.git")
    @patch("alibuild_helpers.workarea.is_writeable", new=MagicMock(return_value=False))
    def test_reference_sources_reused(self, mock_git, mock_makedirs, mock_exists):
        """Check mirrors are reused when pre-existing, but not writable.

        In this case, make sure nothing is fetched, even when requested.
        """
        mock_exists.return_value = True
        spec = MOCK_SPEC.copy()
        updateReferenceRepoSpec(referenceSources="sw/MIRROR", p="AliRoot",
                                spec=spec, fetch=True)
        mock_exists.assert_called_with("%s/sw/MIRROR/aliroot" % getcwd())
        mock_makedirs.assert_called_with("%s/sw/MIRROR" % getcwd(), exist_ok=True)
        mock_git.assert_not_called()
        self.assertEqual(spec.get("reference"), "%s/sw/MIRROR/aliroot" % getcwd())

    @patch("os.path.exists")
    @patch("os.makedirs")
    @patch("codecs.open")
    @patch("alibuild_helpers.git.git")
    @patch("alibuild_helpers.workarea.is_writeable", new=MagicMock(return_value=True))
    def test_reference_sources_updated(self, mock_git, mock_open, mock_makedirs, mock_exists):
        """Check mirrors are updated when possible and git output is logged."""
        mock_exists.return_value = True
        mock_git.return_value = 0, "sentinel output"
        mock_open.return_value = MagicMock(
            __enter__=lambda *args, **kw: MagicMock(
                write=lambda output: self.assertEqual(output, "sentinel output")))
        spec = MOCK_SPEC.copy()
        updateReferenceRepoSpec(referenceSources="sw/MIRROR", p="AliRoot",
                                spec=spec, fetch=True)
        mock_exists.assert_called_with("%s/sw/MIRROR/aliroot" % getcwd())
        mock_exists.assert_has_calls([])
        mock_makedirs.assert_called_with("%s/sw/MIRROR" % getcwd(), exist_ok=True)
        mock_git.assert_called_once_with([
            "fetch", "-f", "--prune", "--filter=blob:none", spec["source"], "+refs/tags/*:refs/tags/*", "+refs/heads/*:refs/heads/*",
        ], directory="%s/sw/MIRROR/aliroot" % getcwd(), check=False, prompt=True)
        self.assertEqual(spec.get("reference"), "%s/sw/MIRROR/aliroot" % getcwd())

    @patch("os.path.exists")
    @patch("os.makedirs")
    @patch("codecs.open")
    @patch("alibuild_helpers.git.git")
    @patch("alibuild_helpers.workarea.is_writeable", new=MagicMock(return_value=True))
    def test_reference_sources_updated_custom_refspec(self, mock_git, mock_open, mock_makedirs, mock_exists):
        """Check mirrors are updated with custom refspec when provided."""
        mock_exists.return_value = True
        mock_git.return_value = 0, "sentinel output"
        mock_open.return_value = MagicMock(
            __enter__=lambda *args, **kw: MagicMock(
                write=lambda output: self.assertEqual(output, "sentinel output")))
        spec = MOCK_SPEC.copy()
        spec["ref_match_rule"] = ["+refs/heads/master:refs/heads/master"]
        updateReferenceRepoSpec(referenceSources="sw/MIRROR", p="AliRoot",
                                spec=spec, fetch=True)
        mock_exists.assert_called_with("%s/sw/MIRROR/aliroot" % getcwd())
        mock_makedirs.assert_called_with("%s/sw/MIRROR" % getcwd(), exist_ok=True)
        mock_git.assert_called_once_with([
            "fetch", "-f", "--prune", "--filter=blob:none", spec["source"], "+refs/heads/master:refs/heads/master",
        ], directory="%s/sw/MIRROR/aliroot" % getcwd(), check=False, prompt=True)
        self.assertEqual(spec.get("reference"), "%s/sw/MIRROR/aliroot" % getcwd())

    @patch("os.path.exists")
    @patch("os.makedirs")
    @patch("alibuild_helpers.git")
    @patch("alibuild_helpers.workarea.is_writeable", new=MagicMock(return_value=False))
    def test_reference_sources_not_writable(self, mock_git, mock_makedirs, mock_exists):
        """Check nothing is fetched when mirror directory isn't writable."""
        mock_exists.side_effect = lambda path: not path.endswith("/aliroot")
        spec = MOCK_SPEC.copy()
        updateReferenceRepoSpec(referenceSources="sw/MIRROR", p="AliRoot",
                                spec=spec, fetch=True)
        mock_exists.assert_called_with("%s/sw/MIRROR/aliroot" % getcwd())
        mock_makedirs.assert_called_with("%s/sw/MIRROR" % getcwd(), exist_ok=True)
        mock_git.assert_not_called()
        self.assertNotIn("reference", spec,
                         "should delete spec['reference'], as no mirror exists")

    @patch("os.path.exists")
    @patch("os.makedirs")
    @patch("alibuild_helpers.git.git")
    @patch("alibuild_helpers.workarea.is_writeable", new=MagicMock(return_value=True))
    def test_reference_sources_created(self, mock_git, mock_makedirs, mock_exists):
        """Check the mirror directory is created when possible."""
        mock_git.return_value = 0, ""
        mock_exists.side_effect = lambda path: not path.endswith("/aliroot")
        spec = MOCK_SPEC.copy()
        updateReferenceRepoSpec(referenceSources="sw/MIRROR", p="AliRoot",
                                spec=spec, fetch=True)
        mock_exists.assert_called_with("%s/sw/MIRROR/aliroot" % getcwd())
        mock_makedirs.assert_called_with("%s/sw/MIRROR" % getcwd(), exist_ok=True)
        mock_git.assert_called_once_with([
            "clone", "--bare", spec["source"],
            "%s/sw/MIRROR/aliroot" % getcwd(), "--filter=blob:none",
        ], directory=".", check=False, prompt=True)
        self.assertEqual(spec.get("reference"), "%s/sw/MIRROR/aliroot" % getcwd())

    @patch("os.path.exists")
    @patch("os.makedirs")
    @patch("codecs.open")
    @patch("alibuild_helpers.git.git")
    @patch("alibuild_helpers.workarea.is_writeable", new=MagicMock(return_value=True))
    def test_pinned_commit_present_is_not_fetched(self, mock_git, mock_open,
                                                  mock_makedirs, mock_exists):
        """A tag that is a commit id cannot move, so a present object needs no fetch.

        The point of refreshing a mirror is to notice a moved tag. A commit id
        names its own content, so there is nothing to notice, and the fetch is
        pure cost -- it asks upstream for every ref, on every round, on every
        builder, and upstreams throttle that.
        """
        mock_exists.return_value = True
        mock_git.return_value = 0, ""    # cat-file -e succeeds: the commit is here
        spec = MOCK_SPEC.copy()
        spec["tag"] = "e7248b26a1ed53fa030c5c459f7ea095dfd276ac"
        updateReferenceRepoSpec(referenceSources="sw/MIRROR", p="AliRoot",
                                spec=spec, fetch=True)
        # called ONCE: the existence check, and no fetch after it
        mock_git.assert_called_once_with(
            ["cat-file", "-e", spec["tag"] + "^{commit}"],
            directory="%s/sw/MIRROR/aliroot" % getcwd(), check=False, prompt=False)
        self.assertEqual(spec.get("reference"), "%s/sw/MIRROR/aliroot" % getcwd())

    @patch("os.path.exists")
    @patch("os.makedirs")
    @patch("codecs.open")
    @patch("alibuild_helpers.git.git")
    @patch("alibuild_helpers.workarea.is_writeable", new=MagicMock(return_value=True))
    def test_pinned_commit_missing_is_fetched(self, mock_git, mock_open,
                                              mock_makedirs, mock_exists):
        """A pinned commit we do NOT have still has to be fetched."""
        mock_exists.return_value = True
        mock_git.side_effect = [(1, "not found"), (0, "sentinel output")]
        spec = MOCK_SPEC.copy()
        spec["tag"] = "0" * 40
        updateReferenceRepoSpec(referenceSources="sw/MIRROR", p="AliRoot",
                                spec=spec, fetch=True)
        self.assertEqual(mock_git.call_count, 2)
        self.assertEqual(mock_git.call_args_list[-1][0][0][0], "fetch")

    @patch("os.path.exists")
    @patch("os.makedirs")
    @patch("codecs.open")
    @patch("alibuild_helpers.git.git")
    @patch("alibuild_helpers.workarea.is_writeable", new=MagicMock(return_value=True))
    def test_movable_tag_is_always_fetched(self, mock_git, mock_open,
                                           mock_makedirs, mock_exists):
        """A named tag can be moved, so it is fetched without even asking."""
        mock_exists.return_value = True
        mock_git.return_value = 0, "sentinel output"
        spec = MOCK_SPEC.copy()
        spec["tag"] = "v3.4.0"
        updateReferenceRepoSpec(referenceSources="sw/MIRROR", p="AliRoot",
                                spec=spec, fetch=True)
        mock_git.assert_called_once_with([
            "fetch", "-f", "--prune", "--filter=blob:none", spec["source"],
            "+refs/tags/*:refs/tags/*", "+refs/heads/*:refs/heads/*",
        ], directory="%s/sw/MIRROR/aliroot" % getcwd(), check=False, prompt=True)


if __name__ == '__main__':
    unittest.main()
