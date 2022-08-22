import unittest

from alibuild_helpers.git import git

MISSING_REPO = "https://github.com/alisw/nonexistent"
MISSING_REPO_ERROR_MSG = (
    "Error 128 from git ls-remote -ht " + MISSING_REPO + ": fatal: could "
    "not read Username for 'https://github.com': terminal prompts disabled"
)


err, out = git(("--help",), check=False)
@unittest.skipUnless(not err and out.startswith("usage:"),
                     "need a working git executable on the system")
class GitWrapperTestCase(unittest.TestCase):
    """Make sure the git() wrapper function is working."""

    def test_git_missing_repo(self):
        """Check we get the right exception when credentials are required."""
        try:
            git(("ls-remote", "-ht", MISSING_REPO), prompt=False)
        except RuntimeError as exc:
            self.assertTupleEqual(exc.args, (MISSING_REPO_ERROR_MSG,))
        else:
            self.fail("expected git(...) to raise a RuntimeError")
