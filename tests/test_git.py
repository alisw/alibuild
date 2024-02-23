import os
import unittest

from alibuild_helpers.git import git
from alibuild_helpers.scm import SCMError

EXISTING_REPO = "https://github.com/alisw/alibuild"
MISSING_REPO = "https://github.com/alisw/nonexistent"
PRIVATE_REPO = "https://gitlab.cern.ch/ALICEPrivateExternals/FLUKA.git"


err, out = git(("--help",), check=False)
@unittest.skipUnless(not err and out.startswith("usage:"),
                     "need a working git executable on the system")
class GitWrapperTestCase(unittest.TestCase):
    """Make sure the git() wrapper function is working."""

    def setUp(self):
        # Disable reading all git configuration files, including the user's, in
        # case they have access to PRIVATE_REPO.
        self._prev_git_config_global = os.environ.get("GIT_CONFIG_GLOBAL")
        os.environ["GIT_CONFIG_GLOBAL"] = os.devnull

    def tearDown(self):
        # Restore the original value of GIT_CONFIG_GLOBAL, if any.
        if self._prev_git_config_global is None:
            del os.environ["GIT_CONFIG_GLOBAL"]
        else:
            os.environ["GIT_CONFIG_GLOBAL"] = self._prev_git_config_global

    def test_git_existing_repo(self):
        """Check git can read an existing repo."""
        err, out = git(("ls-remote", "-ht", EXISTING_REPO),
                       check=False, prompt=False)
        self.assertEqual(err, 0, "git output:\n" + out)
        self.assertTrue(out, "expected non-empty output from git")

    def test_git_missing_repo(self):
        """Check we get the right exception when a repo doesn't exist."""
        self.assertRaises(SCMError, git, (
            "ls-remote", "-ht", MISSING_REPO,
        ), prompt=False)

    def test_git_private_repo(self):
        """Check we get the right exception when credentials are required."""
        self.assertRaises(SCMError, git, (
            "-c", "credential.helper=", "ls-remote", "-ht", PRIVATE_REPO,
        ), prompt=False)
