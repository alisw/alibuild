from __future__ import print_function
from argparse import Namespace
import os
import os.path
import re
import sys
import unittest
# Assuming you are using the mock library to ... mock things
try:
    from unittest.mock import patch, MagicMock, DEFAULT  # In Python 3, mock is built-in
    from io import StringIO
except ImportError:
    from mock import patch, MagicMock, DEFAULT  # Python 2
    from StringIO import StringIO
try:
    from collections import OrderedDict
except ImportError:
    from ordereddict import OrderedDict

git_mock = MagicMock(partialCloneFilter="--filter=blob:none")
sys.modules["alibuild_helpers.git"] = git_mock
sys.modules["alibuild_helpers.analytics"] = MagicMock()

from alibuild_helpers.utilities import parseRecipe, resolve_tag
from alibuild_helpers.build import doBuild, storeHashes


TEST_DEFAULT_RELEASE = """\
package: defaults-release
version: v1
---
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
TEST_ROOT_BUILD_HASH = ("96cf657d1a5e2d41f16dfe42ced8c3522ab4e413" if sys.version_info.major < 3 else
                        "8ec3f41b6b585ef86a02e9c595eed67f34d63f08")


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
TEST_EXTRA_BUILD_HASH = ("9f9eb8696b7722df52c4703f5fe7acc4b8000ba2" if sys.version_info.major < 3 else
                         "5afae57bfc6a374e74c1c4427698ab5edebce0bc")


def dummy_getstatusoutput(x):
    if re.match("/bin/bash --version", x):
        return (0, "GNU bash, version 3.2.57(1)-release (x86_64-apple-darwin17)\nCopyright (C) 2007 Free Software Foundation, Inc.\n")
    if re.match("(mkdir -p|ln -snf) [^;]+$", x):
        return (0, "")
    return {
        "GIT_DIR=/alidist/.git git rev-parse HEAD": (0, "6cec7b7b3769826219dfa85e5daa6de6522229a0"),
        'pip --disable-pip-version-check show alibuild | grep -e "^Version:" | sed -e \'s/.* //\'': (0, "v1.5.0"),
        'which pigz': (1, ""),
        'tar --ignore-failed-read -cvvf /dev/null /dev/zero': (0, ""),
        'GIT_DIR=/alidist/.git git symbolic-ref -q HEAD': (0, "master")
    }[x]


def dummy_getStatusOutputBash(x):
    return {
        'git ls-remote --heads --tags /sw/MIRROR/root': (0, TEST_ROOT_GIT_REFS),
        'git ls-remote --heads --tags /sw/MIRROR/zlib': (0, TEST_ZLIB_GIT_REFS)
    }[x]


TIMES_ASKED = {}


def dummy_open(x, mode="r"):
    if x.endswith("/alibuild_helpers/build_template.sh"):
        return DEFAULT  # actually open the real build_template.sh
    if mode == "r":
        threshold, result = {
            "/sw/BUILD/%s/defaults-release/.build_succeeded" % TEST_DEFAULT_RELEASE_BUILD_HASH: (0, StringIO("0")),
            "/sw/BUILD/%s/zlib/.build_succeeded" % TEST_ZLIB_BUILD_HASH: (0, StringIO("0")),
            "/sw/BUILD/%s/ROOT/.build_succeeded" % TEST_ROOT_BUILD_HASH: (0, StringIO("0")),
            "/sw/osx_x86-64/defaults-release/v1-1/.build-hash": (1, StringIO(TEST_DEFAULT_RELEASE_BUILD_HASH)),
            "/sw/osx_x86-64/zlib/v1.2.3-local1/.build-hash": (1, StringIO(TEST_ZLIB_BUILD_HASH)),
            "/sw/osx_x86-64/ROOT/v6-08-30-local1/.build-hash": (1, StringIO(TEST_ROOT_BUILD_HASH))
        }[x]
        if threshold > TIMES_ASKED.get(x, 0):
            result = None
        TIMES_ASKED[x] = TIMES_ASKED.get(x, 0) + 1
        if not result:
            raise IOError
        return result
    return StringIO()


def dummy_execute(x, mock_git_clone, mock_git_fetch, **kwds):
    s = " ".join(x) if isinstance(x, list) else x
    if re.match(".*ln -sfn.*TARS", s):
        return 0
    if re.search("^git clone --filter=blob:none --bare", s):
        mock_git_clone()
    elif re.search("&& git fetch -f --tags", s):
        mock_git_fetch()
        return 0
    return {
        "/bin/bash -e -x /sw/SPECS/osx_x86-64/defaults-release/v1-1/build.sh 2>&1": 0,
        '/bin/bash -e -x /sw/SPECS/osx_x86-64/zlib/v1.2.3-local1/build.sh 2>&1': 0,
        '/bin/bash -e -x /sw/SPECS/osx_x86-64/ROOT/v6-08-30-local1/build.sh 2>&1': 0,
        "git clone --filter=blob:none --bare https://github.com/star-externals/zlib /sw/MIRROR/zlib": 0,
        "git clone --filter=blob:none --bare https://github.com/root-mirror/root /sw/MIRROR/root": 0,
        "cat /sw/MIRROR/fetch-log.txt": 0,
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
        "/sw/SPECS": False,
        "/alidist/.git": True,
        "alibuild_helpers/.git": False,
        "/sw/MIRROR/root": True,
        "/sw/MIRROR/zlib": False,
        "/sw/MIRROR/fetch-log.txt": False,
    }[x]


# A few errors we should handle, together with the expected result
class BuildTestCase(unittest.TestCase):
    @patch("alibuild_helpers.sync.get", new=MagicMock())
    @patch("alibuild_helpers.build.execute")
    @patch("alibuild_helpers.workarea.execute")
    @patch("alibuild_helpers.sync.execute")
    @patch("alibuild_helpers.build.getstatusoutput", new=dummy_getstatusoutput)
    @patch("alibuild_helpers.build.exists", new=dummy_exists)
    @patch("alibuild_helpers.workarea.path.exists", new=dummy_exists)
    @patch("alibuild_helpers.build.sys")
    @patch("alibuild_helpers.build.dieOnError", new=MagicMock())
    @patch("alibuild_helpers.build.readDefaults",
           new=MagicMock(return_value=(OrderedDict({"package": "defaults-release", "disable": []}), "")))
    @patch("alibuild_helpers.build.makedirs", new=MagicMock(return_value=None))
    @patch("alibuild_helpers.utilities.open", new=lambda x: {
        "/alidist/root.sh": StringIO(TEST_ROOT_RECIPE),
        "/alidist/zlib.sh": StringIO(TEST_ZLIB_RECIPE),
        "/alidist/defaults-release.sh": StringIO(TEST_DEFAULT_RELEASE)
    }[x])
    @patch("alibuild_helpers.sync.open", new=MagicMock(side_effect=dummy_open))
    @patch("alibuild_helpers.build.open", new=MagicMock(side_effect=dummy_open))
    @patch("alibuild_helpers.build.shutil", new=MagicMock())
    @patch("alibuild_helpers.build.glob")
    @patch("alibuild_helpers.build.readlink", new=dummy_readlink)
    @patch("alibuild_helpers.build.banner", new=MagicMock(return_value=None))
    @patch("alibuild_helpers.build.debug", new=MagicMock(return_value=None))
    @patch("alibuild_helpers.build.getStatusOutputBash", new=dummy_getStatusOutputBash)
    @patch("alibuild_helpers.workarea.is_writeable", new=MagicMock(return_value=True))
    @patch("alibuild_helpers.build.basename", new=MagicMock(return_value="aliBuild"))
    def test_coverDoBuild(self, mock_glob, mock_sys, mock_sync_execute, mock_workarea_execute, mock_execute):
        mock_glob.side_effect = lambda x: {
            "*": ["zlib"],
            "/sw/TARS/osx_x86-64/defaults-release/defaults-release-v1-*.osx_x86-64.tar.gz": ["/sw/TARS/osx_x86-64/defaults-release/defaults-release-v1-1.osx_x86-64.tar.gz"],
            "/sw/TARS/osx_x86-64/zlib/zlib-v1.2.3-*.osx_x86-64.tar.gz": [],
            "/sw/TARS/osx_x86-64/ROOT/ROOT-v6-08-30-*.osx_x86-64.tar.gz": [],
            "/sw/TARS/osx_x86-64/store/%s/%s/*gz" % (TEST_DEFAULT_RELEASE_BUILD_HASH[:2],
                                                     TEST_DEFAULT_RELEASE_BUILD_HASH): [],
            "/sw/TARS/osx_x86-64/store/%s/%s/*gz" % (TEST_ZLIB_BUILD_HASH[:2], TEST_ZLIB_BUILD_HASH): [],
            "/sw/TARS/osx_x86-64/store/%s/%s/*gz" % (TEST_ROOT_BUILD_HASH[:2], TEST_ROOT_BUILD_HASH): [],
            "/sw/TARS/osx_x86-64/defaults-release/defaults-release-v1-1.osx_x86-64.tar.gz":
            ["../../osx_x86-64/store/%s/%s/defaults-release-v1-1.osx_x86-64.tar.gz" %
             (TEST_DEFAULT_RELEASE_BUILD_HASH[:2], TEST_DEFAULT_RELEASE_BUILD_HASH)],
        }[x]
        os.environ["ALIBUILD_NO_ANALYTICS"] = "1"

        mock_git_clone = MagicMock(return_value=None)
        mock_git_fetch = MagicMock(return_value=None)
        mock_execute.side_effect = lambda x, **kwds: dummy_execute(x, mock_git_clone, mock_git_fetch, **kwds)
        mock_workarea_execute.side_effect = lambda x, **kwds: dummy_execute(x, mock_git_clone, mock_git_fetch, **kwds)
        mock_sync_execute.side_effect = lambda x, **kwds: dummy_execute(x, mock_git_clone, mock_git_fetch, **kwds)

        mock_parser = MagicMock()
        args = Namespace(
            remoteStore="",
            writeStore="",
            referenceSources="/sw/MIRROR",
            docker=False,
            architecture="osx_x86-64",
            workDir="/sw",
            pkgname=["root"],
            configDir="/alidist",
            disable=[],
            defaults="release",
            jobs=2,
            preferSystem=[],
            noSystem=False,
            debug=True,
            dryRun=False,
            aggressiveCleanup=False,
            environment={},
            autoCleanup=False,
            noDevel=[],
            fetchRepos=False,
        )
        mock_sys.version_info = sys.version_info

        mock_git_clone.reset_mock()
        mock_git_fetch.reset_mock()
        fmt, msg, code = doBuild(args, mock_parser)
        mock_git_clone.assert_called_once()
        mock_git_fetch.assert_not_called()

        # Force fetching repos
        mock_git_clone.reset_mock()
        mock_git_fetch.reset_mock()
        args.fetchRepos = True
        fmt, msg, code = doBuild(args, mock_parser)
        mock_glob.assert_called_with("/sw/TARS/osx_x86-64/ROOT/ROOT-v6-08-30-*.osx_x86-64.tar.gz")
        self.assertEqual(msg, "Everything done")
        mock_git_clone.assert_called_once()
        mock_git_fetch.assert_called_once()

    def test_hashing(self):
        def setup_spec(script):
            err, spec, recipe = parseRecipe(lambda: script)
            self.assertIsNone(err)
            spec["recipe"] = recipe.strip("\n")
            spec.setdefault("tag", spec["version"])
            spec["tag"] = resolve_tag(spec)
            return spec

        default = setup_spec(TEST_DEFAULT_RELEASE)
        zlib = setup_spec(TEST_ZLIB_RECIPE)
        root = setup_spec(TEST_ROOT_RECIPE)
        extra = setup_spec(TEST_EXTRA_RECIPE)
        default["commit_hash"] = "0"
        for spec, refs in ((zlib, TEST_ZLIB_GIT_REFS),
                           (root, TEST_ROOT_GIT_REFS),
                           (extra, TEST_EXTRA_GIT_REFS)):
            spec.setdefault("requires", []).append(default["package"])
            spec["git_refs"] = {ref: hash for hash, _, ref in (
                line.partition("\t") for line in refs.splitlines()
            )}
            try:
                spec["commit_hash"] = spec["git_refs"]["refs/tags/" + spec["tag"]]
            except KeyError:
                spec["commit_hash"] = spec["git_refs"]["refs/heads/" + spec["tag"]]
        specs = {pkg["package"]: pkg for pkg in (default, zlib, root, extra)}

        storeHashes("defaults-release", specs, isDevelPkg=False, considerRelocation=False)
        default["hash"] = default["remote_revision_hash"]
        self.assertEqual(default["hash"], TEST_DEFAULT_RELEASE_BUILD_HASH)
        self.assertEqual(default["remote_hashes"], [TEST_DEFAULT_RELEASE_BUILD_HASH])

        storeHashes("zlib", specs, isDevelPkg=False, considerRelocation=False)
        zlib["hash"] = zlib["local_revision_hash"]
        self.assertEqual(zlib["hash"], TEST_ZLIB_BUILD_HASH)
        self.assertEqual(zlib["local_hashes"], [TEST_ZLIB_BUILD_HASH])

        storeHashes("ROOT", specs, isDevelPkg=False, considerRelocation=False)
        root["hash"] = root["local_revision_hash"]
        self.assertEqual(root["hash"], TEST_ROOT_BUILD_HASH)
        # Equivalent "commit hashes": "f7b336611753f1f4aaa94222b0d620748ae230c0"
        # (head of v6-08-00-patches and commit of test-tag), and "test-tag".
        self.assertEqual(len(root["local_hashes"]), 2)
        self.assertEqual(root["local_hashes"][0], TEST_ROOT_BUILD_HASH)

        storeHashes("Extra", specs, isDevelPkg=False, considerRelocation=False)
        extra["hash"] = extra["local_revision_hash"]
        self.assertEqual(extra["hash"], TEST_EXTRA_BUILD_HASH)
        # Equivalent "commit hashes": "v1", "v2", "ba22".
        self.assertEqual(len(extra["local_hashes"]), 3)
        self.assertEqual(len(extra["remote_hashes"]), 3)
        self.assertEqual(extra["local_hashes"][0], TEST_EXTRA_BUILD_HASH)


if __name__ == '__main__':
    unittest.main()
