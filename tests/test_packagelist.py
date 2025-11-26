from textwrap import dedent
import unittest
from unittest import mock
from unittest.mock import patch
import os.path
import tempfile

from alibuild_helpers.cmd import getstatusoutput
from alibuild_helpers.utilities import getPackageList


RECIPES = {
    "CONFIG_DIR/defaults-release.sh": dedent("""\
    package: defaults-release
    version: v1
    force_rebuild: false
    ---
    """),
    "CONFIG_DIR/disable.sh": dedent("""\
    package: disable
    version: v1
    prefer_system: '.*'
    prefer_system_check: 'true'
    ---
    """),
    "CONFIG_DIR/with-replacement.sh": dedent("""\
    package: with-replacement
    version: v1
    prefer_system: '.*'
    prefer_system_check: |
        echo 'alibuild_system_replace: replacement'
    prefer_system_replacement_specs:
        replacement:
            env:
                SENTINEL_VAR: magic
    ---
    """),
    "CONFIG_DIR/with-replacement-recipe.sh": dedent("""\
    package: with-replacement-recipe
    version: v1
    prefer_system: '.*'
    prefer_system_check: |
        echo 'alibuild_system_replace: replacement'
    prefer_system_replacement_specs:
        replacement:
            recipe: 'true'
    ---
    """),
    "CONFIG_DIR/missing-spec.sh": dedent("""\
    package: missing-spec
    version: v1
    prefer_system: '.*'
    prefer_system_check: |
        echo 'alibuild_system_replace: missing_tag'
    prefer_system_replacement_specs: {}
    ---
    """),
    "CONFIG_DIR/sentinel-command.sh": dedent("""\
    package: sentinel-command
    version: v1
    prefer_system: '.*'
    prefer_system_check: |
        : magic sentinel command
    ---
    """),
    "CONFIG_DIR/force-rebuild.sh": dedent("""\
    package: force-rebuild
    version: v1
    force_rebuild: true
    ---
    """),
    "CONFIG_DIR/dirty_prefer_system_check.sh": dedent("""\
    package: dirty_prefer_system_check
    version: v1
    prefer_system: .*
    prefer_system_check: |
      pwd > HEREE
      exit 0
    ---
    """),
}

class MockReader:
    def __init__(self, url: str, dist=None):
        self._contents = RECIPES[url]
        self.url = "mock://" + url

    def __call__(self):
        return self._contents



def getPackageListWithDefaults(packages, force_rebuild=()):
    specs = {}   # getPackageList will mutate this
    def performPreferCheckWithTempDir(pkg, cmd):
      with tempfile.TemporaryDirectory(prefix=f"alibuild_prefer_check_{pkg['package']}_") as temp_dir:
        return getstatusoutput(cmd, cwd=temp_dir)
    return_values = getPackageList(
        packages=packages,
        specs=specs,
        configDir="CONFIG_DIR",
        # Make sure getPackageList considers prefer_system_check.
        # (Even with preferSystem=False + noSystem=None, it is sufficient
        # if the prefer_system regex matches the architecture.)
        preferSystem=True,
        noSystem=None,
        architecture="ARCH",
        disable=[],
        defaults="release",
        # Mock recipes just run "echo" or ":", so this is safe.
        performPreferCheck=performPreferCheckWithTempDir,
        performRequirementCheck=performPreferCheckWithTempDir,
        performValidateDefaults=lambda spec: (True, "", ["release"]),
        overrides={"defaults-release": {}},
        taps={},
        log=lambda *_: None,
        force_rebuild=force_rebuild,
    )
    return (specs, *return_values)


@mock.patch("alibuild_helpers.utilities.getRecipeReader", new=MockReader)
class ReplacementTestCase(unittest.TestCase):
    """Test that system package replacements are working."""

    def test_disable(self):
        """Check that not specifying any replacement disables the package.

        This is was the only available behaviour in previous aliBuild versions
        and must be preserved for backward compatibility.
        """
        def fake_exists(n):
            return n in RECIPES.keys()
        with patch.object(os.path, "exists", fake_exists):
            specs, systemPkgs, ownPkgs, failedReqs, validDefaults = \
                getPackageListWithDefaults(["disable"])
            self.assertIn("disable", systemPkgs)
            self.assertNotIn("disable", ownPkgs)
            self.assertNotIn("disable", specs)

    def test_replacement_given(self):
        """Check that specifying a replacement spec means it is used.

        This also checks that if no recipe is given, we report the package as
        a system package to the user.
        """
        def fake_exists(n):
            return n in RECIPES.keys()
        with patch.object(os.path, "exists", fake_exists):
            specs, systemPkgs, ownPkgs, failedReqs, validDefaults = \
                getPackageListWithDefaults(["with-replacement"])
            self.assertIn("with-replacement", specs)
            self.assertEqual(specs["with-replacement"]["env"]["SENTINEL_VAR"], "magic")
            # Make sure nothing is run by default.
            self.assertEqual(specs["with-replacement"]["recipe"], "")
            # If the replacement spec has no recipe, report to the user that we're
            # taking the package from the system.
            self.assertIn("with-replacement", systemPkgs)
            self.assertNotIn("with-replacement", ownPkgs)

    def test_replacement_recipe_given(self) -> None:
        """Check that specifying a replacement recipe means it is used.

        Also check that we report to the user that a package will be compiled
        when a replacement recipe is given.
        """
        def fake_exists(n):
            return n in RECIPES.keys()
        with patch.object(os.path, "exists", fake_exists):
            specs, systemPkgs, ownPkgs, failedReqs, validDefaults = \
                getPackageListWithDefaults(["with-replacement-recipe"])
            self.assertIn("with-replacement-recipe", specs)
            self.assertIn("recipe", specs["with-replacement-recipe"])
            self.assertEqual("true", specs["with-replacement-recipe"]["recipe"])
            # If the replacement spec has a recipe, report to the user that we're
            # compiling the package.
            self.assertNotIn("with-replacement-recipe", systemPkgs)
            self.assertIn("with-replacement-recipe", ownPkgs)

    @mock.patch("alibuild_helpers.utilities.warning")
    def test_missing_replacement_spec(self, mock_warning) -> None:
        """Check a warning is displayed when the replacement spec is not found."""
        warning_msg = "falling back to building the package ourselves"
        warning_exists = False
        def fake_exists(n):
            return n in RECIPES.keys()
        with patch.object(os.path, "exists", fake_exists):
            def side_effect(msg, *args, **kwargs):
                nonlocal warning_exists
                if warning_msg in str(msg):
                    warning_exists = True
            mock_warning.side_effect = side_effect
            specs, systemPkgs, ownPkgs, failedReqs, validDefaults = \
                getPackageListWithDefaults(["missing-spec"])
            self.assertTrue(warning_exists)

    def test_dirty_system_check(self) -> None:
        """Check that prefer_system_check runs in isolation and doesn't create files in cwd."""
        def fake_exists(n):
            return n in RECIPES.keys()
        with patch.object(os.path, "exists", fake_exists):
            getPackageListWithDefaults(["dirty_prefer_system_check"])
            # can't use os.path.exists() ourselves, as we just mocked it
            self.assertFalse("HEREE" in os.listdir())


@mock.patch("alibuild_helpers.utilities.getRecipeReader", new=MockReader)
class ForceRebuildTestCase(unittest.TestCase):
    """Test that force_rebuild keys are applied properly."""

    def test_force_rebuild_recipe(self) -> None:
        """If the recipe specifies force_rebuild, it must be applied."""
        def fake_exists(n):
            return n in RECIPES.keys()
        with patch.object(os.path, "exists", fake_exists):
            specs, _, _, _, _ = getPackageListWithDefaults(["force-rebuild"])
            self.assertTrue(specs["force-rebuild"]["force_rebuild"])
            self.assertFalse(specs["defaults-release"]["force_rebuild"])

    def test_force_rebuild_command_line(self) -> None:
        """The --force-rebuild option must take precedence, if given."""
        def fake_exists(n):
            return n in RECIPES.keys()
        with patch.object(os.path, "exists", fake_exists):
            specs, _, _, _, _ = getPackageListWithDefaults(
                ["force-rebuild"], force_rebuild=["defaults-release", "force-rebuild"],
            )
            self.assertTrue(specs["force-rebuild"]["force_rebuild"])
            self.assertTrue(specs["defaults-release"]["force_rebuild"])




if __name__ == '__main__':
    unittest.main()
