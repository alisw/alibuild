from __future__ import print_function
from textwrap import dedent
import unittest
try:                  # Python 3
    from unittest import mock
except ImportError:   # Python 2
    import mock

from alibuild_helpers.cmd import getstatusoutput
from alibuild_helpers.utilities import getPackageList


RECIPES = {
    "CONFIG_DIR/defaults-release.sh": dedent("""\
    package: defaults-release
    version: v1
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
}


class MockReader:
    def __init__(self, url, dist=None):
        self._contents = RECIPES[url]
        self.url = "mock://" + url

    def __call__(self):
        return self._contents


def getPackageListWithDefaults(packages):
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
        defaults="DEFAULTS",
        performPreferCheck=lambda spec, cmd: getstatusoutput(cmd),
        performRequirementCheck=lambda spec, cmd: getstatusoutput(cmd),
        performValidateDefaults=lambda spec: (True, "", ["DEFAULTS"]),
        overrides={"defaults-release": {}},
        taps={},
        log=lambda *_: None,
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
        specs, systemPkgs, ownPkgs, failedReqs, validDefaults = \
            getPackageListWithDefaults(["missing-spec"])
        mock_dieOnError.assert_any_call(True, "Could not find named replacement "
                                        "spec for missing-spec: missing_tag")


if __name__ == '__main__':
    unittest.main()
