from __future__ import print_function
from textwrap import dedent
import unittest
from unittest import mock

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
}


class MockReader:
    def __init__(self, url, dist=None):
        self._contents = RECIPES[url]
        self.url = "mock://" + url

    def __call__(self):
        return self._contents


def getPackageListWithDefaults(packages, force_rebuild=()):
    specs = {}   # getPackageList will mutate this
    return_values = getPackageList(
        packages=packages,
        specs=specs,
        configDir="CONFIG_DIR",
        # Make sure getPackageList considers prefer_system_check.
        # (Even with preferSystem=False + noSystem=False, it is sufficient
        # if the prefer_system regex matches the architecture.)
        preferSystem=True,
        noSystem=False,
        architecture="ARCH",
        disable=[],
        defaults="release",
        # Mock recipes just run "echo" or ":", so this is safe.
        performPreferCheck=lambda spec, cmd: getstatusoutput(cmd),
        performRequirementCheck=lambda spec, cmd: getstatusoutput(cmd),
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

    def test_replacement_recipe_given(self):
        """Check that specifying a replacement recipe means it is used.

        Also check that we report to the user that a package will be compiled
        when a replacement recipe is given.
        """
        specs, systemPkgs, ownPkgs, failedReqs, validDefaults = \
            getPackageListWithDefaults(["with-replacement-recipe"])
        self.assertIn("with-replacement-recipe", specs)
        self.assertIn("recipe", specs["with-replacement-recipe"])
        self.assertEqual("true", specs["with-replacement-recipe"]["recipe"])
        # If the replacement spec has a recipe, report to the user that we're
        # compiling the package.
        self.assertNotIn("with-replacement-recipe", systemPkgs)
        self.assertIn("with-replacement-recipe", ownPkgs)

    @mock.patch("alibuild_helpers.utilities.dieOnError")
    def test_missing_replacement_spec(self, mock_dieOnError):
        """Check an error is thrown when the replacement spec is not found."""
        assert_msg = "Could not find named replacement spec for missing-spec: missing_tag"
        # Change the behaviour from sys.exit to a regular exception. Without it
        # we don't stop execution properly and other asserts might trigger
        mock_dieOnError.side_effect = lambda cond, _: (_ for _ in ()).throw(Exception("dieOnError called")) if cond else None
        with self.assertRaises(Exception, msg=assert_msg) as context:
            specs, systemPkgs, ownPkgs, failedReqs, validDefaults = \
                getPackageListWithDefaults(["missing-spec"])
        self.assertEqual(str(context.exception), "dieOnError called", msg=assert_msg)


@mock.patch("alibuild_helpers.utilities.getRecipeReader", new=MockReader)
class ForceRebuildTestCase(unittest.TestCase):
    """Test that force_rebuild keys are applied properly."""

    def test_force_rebuild_recipe(self):
        """If the recipe specifies force_rebuild, it must be applied."""
        specs, _, _, _, _ = getPackageListWithDefaults(["force-rebuild"])
        self.assertTrue(specs["force-rebuild"]["force_rebuild"])
        self.assertFalse(specs["defaults-release"]["force_rebuild"])

    def test_force_rebuild_command_line(self):
        """The --force-rebuild option must take precedence, if given."""
        specs, _, _, _, _ = getPackageListWithDefaults(
            ["force-rebuild"], force_rebuild=["defaults-release", "force-rebuild"],
        )
        self.assertTrue(specs["force-rebuild"]["force_rebuild"])
        self.assertTrue(specs["defaults-release"]["force_rebuild"])


if __name__ == '__main__':
    unittest.main()
