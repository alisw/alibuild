from __future__ import print_function
from argparse import Namespace
import os
import os.path
import re
import sys
import unittest
# Assuming you are using the mock library to ... mock things
from unittest.mock import call, patch, MagicMock, DEFAULT
from io import StringIO
from collections import OrderedDict

from alibuild_helpers.utilities import parseRecipe, resolve_tag
from alibuild_helpers.build import doBuild, storeHashes, generate_initdotsh


TEST_DEFAULT_RELEASE = """\
package: defaults-release
version: v1
---
: this line should trigger a warning
"""
TEST_DEFAULT_RELEASE_BUILD_HASH = "27ce49698e818e8efb56b6eff6dd785e503df341"

TEST_ZLIB_RECIPE = """\
package: zlib
version: v1.2.3
source: https://github.com/star-externals/zlib
tag: master
---
./configure
make
make install
"""
TEST_ZLIB_GIT_REFS = "8822efa61f2a385e0bc83ca5819d608111b2168a\trefs/heads/master"
TEST_ZLIB_BUILD_HASH = "8cd1f56c450f05ffbba3276bad08eae30f814999"

TEST_ROOT_RECIPE = """\
package: ROOT
version: v6-08-30
source: https://github.com/root-mirror/root
tag: v6-08-00-patches
requires:
  - zlib
env:
  ROOT_TEST_1: "root test 1"
  ROOT_TEST_2: "root test 2"
  ROOT_TEST_3: "root test 3"
  ROOT_TEST_4: "root test 4"
  ROOT_TEST_5: "root test 5"
  ROOT_TEST_6: "root test 6"
prepend_path:
  PREPEND_ROOT_1: "prepend root 1"
  PREPEND_ROOT_2: "prepend root 2"
  PREPEND_ROOT_3: "prepend root 3"
  PREPEND_ROOT_4: "prepend root 4"
  PREPEND_ROOT_5: "prepend root 5"
  PREPEND_ROOT_6: "prepend root 6"
append_path:
  APPEND_ROOT_1: "append root 1"
  APPEND_ROOT_2: "append root 2"
  APPEND_ROOT_3: "append root 3"
  APPEND_ROOT_4: "append root 4"
  APPEND_ROOT_5: "append root 5"
  APPEND_ROOT_6: "append root 6"
---
./configure
make
make install
"""
TEST_ROOT_GIT_REFS = """\
87b87c4322d2a3fad315c919cb2e2dd73f2154dc\trefs/heads/master
f7b336611753f1f4aaa94222b0d620748ae230c0\trefs/heads/v6-08-00-patches
f7b336611753f1f4aaa94222b0d620748ae230c0\trefs/tags/test-tag"""
TEST_ROOT_BUILD_HASH = ("8ec3f41b6b585ef86a02e9c595eed67f34d63f08")


TEST_EXTRA_RECIPE = """\
package: Extra
version: v1
tag: v1
source: file:///dev/null
requires:
  - ROOT
---
"""
TEST_EXTRA_GIT_REFS = """\
f000\trefs/heads/master
ba22\trefs/tags/v1
ba22\trefs/tags/v2
baad\trefs/tags/v3"""
TEST_EXTRA_BUILD_HASH = ("5afae57bfc6a374e74c1c4427698ab5edebce0bc")


GIT_CLONE_REF_ZLIB_ARGS = ("clone", "--bare", "https://github.com/star-externals/zlib",
                           "/sw/MIRROR/zlib", "--filter=blob:none"), ".", False
GIT_CLONE_SRC_ZLIB_ARGS = ("clone", "-n", "https://github.com/star-externals/zlib",
                           "/sw/SOURCES/zlib/v1.2.3/8822efa61f",
                           "--dissociate", "--reference", "/sw/MIRROR/zlib", "--filter=blob:none"), ".", False
GIT_SET_URL_ZLIB_ARGS = ("remote", "set-url", "--push", "origin", "https://github.com/star-externals/zlib"), \
    "/sw/SOURCES/zlib/v1.2.3/8822efa61f", False
GIT_CHECKOUT_ZLIB_ARGS = ("checkout", "-f", "master"), \
    "/sw/SOURCES/zlib/v1.2.3/8822efa61f", False

GIT_FETCH_REF_ROOT_ARGS = ("fetch", "-f", "--filter=blob:none", "https://github.com/root-mirror/root", "+refs/tags/*:refs/tags/*",
                           "+refs/heads/*:refs/heads/*"), "/sw/MIRROR/root", False
GIT_CLONE_SRC_ROOT_ARGS = ("clone", "-n", "https://github.com/root-mirror/root",
                           "/sw/SOURCES/ROOT/v6-08-30/f7b3366117",
                           "--dissociate", "--reference", "/sw/MIRROR/root", "--filter=blob:none"), ".", False
GIT_SET_URL_ROOT_ARGS = ("remote", "set-url", "--push", "origin", "https://github.com/root-mirror/root"), \
    "/sw/SOURCES/ROOT/v6-08-30/f7b3366117", False
GIT_CHECKOUT_ROOT_ARGS = ("checkout", "-f", "v6-08-00-patches"), \
    "/sw/SOURCES/ROOT/v6-08-30/f7b3366117", False


def dummy_git(args, directory=".", check=True, prompt=True):
    return {
        (("symbolic-ref", "-q", "HEAD"), "/alidist", False): (0, "master"),
        (("rev-parse", "HEAD"), "/alidist", True): "6cec7b7b3769826219dfa85e5daa6de6522229a0",
        (("ls-remote", "--heads", "--tags", "/sw/MIRROR/root"), ".", False): (0, TEST_ROOT_GIT_REFS),
        (("ls-remote", "--heads", "--tags", "/sw/MIRROR/zlib"), ".", False): (0, TEST_ZLIB_GIT_REFS),
        GIT_CLONE_REF_ZLIB_ARGS: (0, ""),
        GIT_CLONE_SRC_ZLIB_ARGS: (0, ""),
        GIT_SET_URL_ZLIB_ARGS: (0, ""),
        GIT_CHECKOUT_ZLIB_ARGS: (0, ""),
        GIT_FETCH_REF_ROOT_ARGS: (0, ""),
        GIT_CLONE_SRC_ROOT_ARGS: (0, ""),
        GIT_SET_URL_ROOT_ARGS: (0, ""),
        GIT_CHECKOUT_ROOT_ARGS: (0, ""),
    }[(tuple(args), directory, check)]


TIMES_ASKED = {}


def dummy_open(x, mode="r", encoding=None, errors=None):
    if x.endswith("/fetch-log.txt") and mode == "w":
        return MagicMock(__enter__=lambda _: StringIO())
    if x.endswith("/alibuild_helpers/build_template.sh"):
        return DEFAULT  # actually open the real build_template.sh
    if mode == "r":
        try:
            threshold, result = {
                "/sw/BUILD/%s/defaults-release/.build_succeeded" % TEST_DEFAULT_RELEASE_BUILD_HASH: (0, StringIO("0")),
                "/sw/BUILD/%s/zlib/.build_succeeded" % TEST_ZLIB_BUILD_HASH: (0, StringIO("0")),
                "/sw/BUILD/%s/ROOT/.build_succeeded" % TEST_ROOT_BUILD_HASH: (0, StringIO("0")),
                "/sw/osx_x86-64/defaults-release/v1-1/.build-hash": (1, StringIO(TEST_DEFAULT_RELEASE_BUILD_HASH)),
                "/sw/osx_x86-64/zlib/v1.2.3-local1/.build-hash": (1, StringIO(TEST_ZLIB_BUILD_HASH)),
                "/sw/osx_x86-64/ROOT/v6-08-30-local1/.build-hash": (1, StringIO(TEST_ROOT_BUILD_HASH))
            }[x]
        except KeyError:
            return DEFAULT
        if threshold > TIMES_ASKED.get(x, 0):
            result = None
        TIMES_ASKED[x] = TIMES_ASKED.get(x, 0) + 1
        if not result:
            raise IOError
        return result
    return DEFAULT


def dummy_execute(x, **kwds):
    s = " ".join(x) if isinstance(x, list) else x
    if re.match(".*ln -sfn.*TARS", s):
        return 0
    return {
        "/bin/bash -e -x /sw/SPECS/osx_x86-64/defaults-release/v1-1/build.sh 2>&1": 0,
        '/bin/bash -e -x /sw/SPECS/osx_x86-64/zlib/v1.2.3-local1/build.sh 2>&1': 0,
        '/bin/bash -e -x /sw/SPECS/osx_x86-64/ROOT/v6-08-30-local1/build.sh 2>&1': 0,
    }[s]


def dummy_readlink(x):
    return {
        "/sw/TARS/osx_x86-64/defaults-release/defaults-release-v1-1.osx_x86-64.tar.gz":
        "../../osx_x86-64/store/%s/%s/defaults-release-v1-1.osx_x86-64.tar.gz" %
        (TEST_DEFAULT_RELEASE_BUILD_HASH[:2], TEST_DEFAULT_RELEASE_BUILD_HASH)
    }[x]


def dummy_exists(x):
    if x.endswith("alibuild_helpers/.git"):
        return False
    return {
        "/alidist": True,
        "/alidist/.git": True,
        "/alidist/.sl": False,
        "/sw": True,
        "/sw/SPECS": False,
        "/sw/MIRROR/root": True,
        "/sw/MIRROR/zlib": False,
    }.get(x, DEFAULT)


# A few errors we should handle, together with the expected result
@patch("alibuild_helpers.git.clone_speedup_options",
       new=MagicMock(return_value=["--filter=blob:none"]))
@patch("alibuild_helpers.build.BASH", new="/bin/bash")
class BuildTestCase(unittest.TestCase):
    @patch("alibuild_helpers.analytics", new=MagicMock())
    @patch("requests.Session.get", new=MagicMock())
    @patch("alibuild_helpers.sync.execute", new=dummy_execute)
    @patch("alibuild_helpers.git.git")
    @patch("alibuild_helpers.build.exists", new=MagicMock(side_effect=dummy_exists))
    @patch("os.path.exists", new=MagicMock(side_effect=dummy_exists))
    @patch("alibuild_helpers.build.sys")
    @patch("alibuild_helpers.build.dieOnError", new=MagicMock())
    @patch("alibuild_helpers.utilities.dieOnError", new=MagicMock())
    @patch("alibuild_helpers.utilities.warning")
    @patch("alibuild_helpers.build.readDefaults",
           new=MagicMock(return_value=(OrderedDict({"package": "defaults-release", "disable": []}), "")))
    @patch("shutil.rmtree", new=MagicMock(return_value=None))
    @patch("os.makedirs", new=MagicMock(return_value=None))
    @patch("alibuild_helpers.build.makedirs", new=MagicMock(return_value=None))
    @patch("alibuild_helpers.build.symlink", new=MagicMock(return_value=None))
    @patch("alibuild_helpers.workarea.symlink", new=MagicMock(return_value=None))
    @patch("alibuild_helpers.utilities.open", new=lambda x: {
        "/alidist/root.sh": StringIO(TEST_ROOT_RECIPE),
        "/alidist/zlib.sh": StringIO(TEST_ZLIB_RECIPE),
        "/alidist/defaults-release.sh": StringIO(TEST_DEFAULT_RELEASE)
    }[x])
    @patch("alibuild_helpers.sync.open", new=MagicMock(side_effect=dummy_open))
    @patch("alibuild_helpers.build.open", new=MagicMock(side_effect=dummy_open))
    @patch("codecs.open", new=MagicMock(side_effect=dummy_open))
    @patch("alibuild_helpers.build.shutil", new=MagicMock())
    @patch("os.listdir")
    @patch("alibuild_helpers.build.glob", new=lambda pattern: {
        "*": ["zlib"],
        "/sw/TARS/osx_x86-64/store/%s/%s/*gz" % (TEST_DEFAULT_RELEASE_BUILD_HASH[:2],
                                                 TEST_DEFAULT_RELEASE_BUILD_HASH): [],
        "/sw/TARS/osx_x86-64/store/%s/%s/*gz" % (TEST_ZLIB_BUILD_HASH[:2], TEST_ZLIB_BUILD_HASH): [],
        "/sw/TARS/osx_x86-64/store/%s/%s/*gz" % (TEST_ROOT_BUILD_HASH[:2], TEST_ROOT_BUILD_HASH): [],
        "/sw/TARS/osx_x86-64/defaults-release/defaults-release-v1-1.osx_x86-64.tar.gz":
        ["../../osx_x86-64/store/%s/%s/defaults-release-v1-1.osx_x86-64.tar.gz" %
         (TEST_DEFAULT_RELEASE_BUILD_HASH[:2], TEST_DEFAULT_RELEASE_BUILD_HASH)],
    }[pattern])
    @patch("alibuild_helpers.build.readlink", new=dummy_readlink)
    @patch("alibuild_helpers.build.banner", new=MagicMock(return_value=None))
    @patch("alibuild_helpers.build.debug")
    @patch("alibuild_helpers.workarea.is_writeable", new=MagicMock(return_value=True))
    @patch("alibuild_helpers.build.basename", new=MagicMock(return_value="aliBuild"))
    @patch("alibuild_helpers.build.install_wrapper_script", new=MagicMock())
    def test_coverDoBuild(self, mock_debug, mock_listdir, mock_warning, mock_sys, mock_git_git):
        mock_git_git.side_effect = dummy_git
        mock_debug.side_effect = lambda *args: None
        mock_warning.side_effect = lambda *args: None
        mock_listdir.side_effect = lambda directory: {
            "/sw/TARS/osx_x86-64/defaults-release": ["defaults-release-v1-1.osx_x86-64.tar.gz"],
            "/sw/TARS/osx_x86-64/zlib": [],
            "/sw/TARS/osx_x86-64/ROOT": [],
        }.get(directory, DEFAULT)
        os.environ["ALIBUILD_NO_ANALYTICS"] = "1"

        mock_parser = MagicMock()
        args = Namespace(
            remoteStore="",
            writeStore="",
            referenceSources="/sw/MIRROR",
            docker=False,
            dockerImage=None,
            docker_extra_args=["--network=host"],
            architecture="osx_x86-64",
            workDir="/sw",
            pkgname=["root"],
            configDir="/alidist",
            disable=[],
            force_rebuild=[],
            defaults="release",
            jobs=2,
            annotate={},
            preferSystem=[],
            noSystem=False,
            debug=True,
            dryRun=False,
            aggressiveCleanup=False,
            environment={},
            autoCleanup=False,
            noDevel=[],
            onlyDeps=False,
            fetchRepos=False,
            forceTracked=False,
            plugin="legacy"
        )
        mock_sys.version_info = sys.version_info

        def mkcall(args):
            cmd, directory, check = args
            return call(list(cmd), directory=directory, check=check, prompt=False)

        common_calls = [
            call(("rev-parse", "HEAD"), args.configDir),
            mkcall(GIT_CLONE_REF_ZLIB_ARGS),
            call(["ls-remote", "--heads", "--tags", args.referenceSources + "/zlib"],
                 directory=".", check=False, prompt=False),
            call(["ls-remote", "--heads", "--tags", args.referenceSources + "/root"],
                 directory=".", check=False, prompt=False),
        ]

        mock_git_git.reset_mock()
        mock_debug.reset_mock()
        mock_warning.reset_mock()
        doBuild(args, mock_parser)
        mock_warning.assert_called_with("%s.sh contains a recipe, which will be ignored", "defaults-release")
        mock_debug.assert_called_with("Everything done")
        # After this run, .build-hash files will be simulated to exist
        # already, so sw/SOURCES repos must only be checked out on this run.
        mock_git_git.assert_has_calls(common_calls + [
            mkcall(GIT_CLONE_SRC_ZLIB_ARGS),
            mkcall(GIT_SET_URL_ZLIB_ARGS),
            mkcall(GIT_CHECKOUT_ZLIB_ARGS),
            mkcall(GIT_CLONE_SRC_ROOT_ARGS),
            mkcall(GIT_SET_URL_ROOT_ARGS),
            mkcall(GIT_CHECKOUT_ROOT_ARGS),
        ], any_order=True)
        self.assertEqual(mock_git_git.call_count, len(common_calls) + 6)

        # Force fetching repos
        mock_git_git.reset_mock()
        mock_debug.reset_mock()
        mock_warning.reset_mock()
        args.fetchRepos = True
        doBuild(args, mock_parser)
        mock_warning.assert_called_with("%s.sh contains a recipe, which will be ignored", "defaults-release")
        mock_debug.assert_called_with("Everything done")
        mock_listdir.assert_called_with("/sw/TARS/osx_x86-64/ROOT")
        # We can't compare directly against the list of calls here as they
        # might happen in any order.
        mock_git_git.assert_has_calls(common_calls + [
            mkcall(GIT_FETCH_REF_ROOT_ARGS),
        ], any_order=True)
        self.assertEqual(mock_git_git.call_count, len(common_calls) + 1)

    def setup_spec(self, script):
        """Parse the alidist recipe in SCRIPT and return its spec."""
        err, spec, recipe = parseRecipe(lambda: script)
        self.assertIsNone(err)
        spec["recipe"] = "" if spec["package"].startswith("defaults-") else recipe.strip("\n")
        spec.setdefault("tag", spec["version"])
        spec["tag"] = resolve_tag(spec)
        return spec

    def test_hashing(self):
        """Check that the hashes assigned to packages remain constant."""
        default = self.setup_spec(TEST_DEFAULT_RELEASE)
        zlib = self.setup_spec(TEST_ZLIB_RECIPE)
        root = self.setup_spec(TEST_ROOT_RECIPE)
        extra = self.setup_spec(TEST_EXTRA_RECIPE)
        default["commit_hash"] = "0"
        for spec, refs in ((zlib, TEST_ZLIB_GIT_REFS),
                           (root, TEST_ROOT_GIT_REFS),
                           (extra, TEST_EXTRA_GIT_REFS)):
            spec.setdefault("requires", []).append(default["package"])
            spec["scm_refs"] = {ref: hash for hash, _, ref in (
                line.partition("\t") for line in refs.splitlines()
            )}
            try:
                spec["commit_hash"] = spec["scm_refs"]["refs/tags/" + spec["tag"]]
            except KeyError:
                spec["commit_hash"] = spec["scm_refs"]["refs/heads/" + spec["tag"]]
        specs = {pkg["package"]: pkg for pkg in (default, zlib, root, extra)}
        for spec in specs.values():
            spec["is_devel_pkg"] = False

        storeHashes("defaults-release", specs, considerRelocation=False)
        default["hash"] = default["remote_revision_hash"]
        self.assertEqual(default["hash"], TEST_DEFAULT_RELEASE_BUILD_HASH)
        self.assertEqual(default["remote_hashes"], [TEST_DEFAULT_RELEASE_BUILD_HASH])

        storeHashes("zlib", specs, considerRelocation=False)
        zlib["hash"] = zlib["local_revision_hash"]
        self.assertEqual(zlib["hash"], TEST_ZLIB_BUILD_HASH)
        self.assertEqual(zlib["local_hashes"], [TEST_ZLIB_BUILD_HASH])

        storeHashes("ROOT", specs, considerRelocation=False)
        root["hash"] = root["local_revision_hash"]
        self.assertEqual(root["hash"], TEST_ROOT_BUILD_HASH)
        # Equivalent "commit hashes": "f7b336611753f1f4aaa94222b0d620748ae230c0"
        # (head of v6-08-00-patches and commit of test-tag), and "test-tag".
        self.assertEqual(len(root["local_hashes"]), 2)
        self.assertEqual(root["local_hashes"][0], TEST_ROOT_BUILD_HASH)

        storeHashes("Extra", specs, considerRelocation=False)
        extra["hash"] = extra["local_revision_hash"]
        self.assertEqual(extra["hash"], TEST_EXTRA_BUILD_HASH)
        # Equivalent "commit hashes": "v1", "v2", "ba22".
        self.assertEqual(len(extra["local_hashes"]), 3)
        self.assertEqual(len(extra["remote_hashes"]), 3)
        self.assertEqual(extra["local_hashes"][0], TEST_EXTRA_BUILD_HASH)

    def test_initdotsh(self):
        """Sanity-check the generated init.sh for a few variables."""
        specs = {
            # Add some attributes that are normally set by doBuild(), but
            # required by generate_initdotsh().
            spec["package"]: dict(spec, revision="1", commit_hash="424242", hash="010101")
            for spec in map(self.setup_spec, (
                    TEST_DEFAULT_RELEASE,
                    TEST_ZLIB_RECIPE,
                    TEST_ROOT_RECIPE,
                    TEST_EXTRA_RECIPE,
            ))
        }

        setup_initdotsh = generate_initdotsh("ROOT", specs, "slc7_x86-64", post_build=False)
        complete_initdotsh = generate_initdotsh("ROOT", specs, "slc7_x86-64", post_build=True)

        # We only generate init.sh for ROOT, so Extra should not appear at all.
        self.assertNotIn("Extra", setup_initdotsh)
        self.assertNotIn("Extra", complete_initdotsh)

        # Dependencies must be loaded both for this build and for subsequent ones.
        self.assertIn('. "$WORK_DIR/$ALIBUILD_ARCH_PREFIX"/zlib/v1.2.3-1/etc/profile.d/init.sh', setup_initdotsh)
        self.assertIn('. "$WORK_DIR/$ALIBUILD_ARCH_PREFIX"/zlib/v1.2.3-1/etc/profile.d/init.sh', complete_initdotsh)

        # ROOT-specific variables must not be set during ROOT's build yet...
        self.assertNotIn("export ROOT_VERSION=", setup_initdotsh)
        self.assertNotIn("export ROOT_TEST_1=", setup_initdotsh)
        self.assertNotIn("export APPEND_ROOT_1=", setup_initdotsh)
        self.assertNotIn("export PREPEND_ROOT_1=", setup_initdotsh)

        # ...but they must be set once ROOT's build has completed.
        self.assertIn("export ROOT_VERSION=v6-08-30", complete_initdotsh)
        self.assertIn('export ROOT_TEST_1="root test 1"', complete_initdotsh)
        self.assertIn("export APPEND_ROOT_1=", complete_initdotsh)
        self.assertIn("export PREPEND_ROOT_1=", complete_initdotsh)


if __name__ == '__main__':
    unittest.main()
