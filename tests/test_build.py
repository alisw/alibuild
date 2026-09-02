from argparse import Namespace
import os
import os.path
import platform
import re
import sys
import unittest
# Assuming you are using the mock library to ... mock things
from unittest.mock import call, patch, MagicMock, DEFAULT
from io import StringIO
from collections import OrderedDict

from alibuild_helpers.utilities import parseRecipe, resolve_tag
from alibuild_helpers import sync_reapi
from alibuild_helpers.build import doBuild, storeHashes, generate_initdotsh, build_ac_entry, select_cached_tarball, bound_unpublished_rebuild

# Determine architecture based on platform
def get_test_architecture():
    if sys.platform == 'darwin':
        machine = platform.machine()
        if machine == 'arm64':
            return 'osx_arm64'
        else:
            return 'osx_x86-64'
    else:
        return 'slc7_x86-64'

TEST_ARCHITECTURE = os.environ.get('ARCHITECTURE', get_test_architecture())


TEST_DEFAULT_RELEASE = """\
package: defaults-release
version: v1
---
: this line should trigger a warning
"""
TEST_DEFAULT_RELEASE_BUILD_HASH = "27ce49698e818e8efb56b6eff6dd785e503df341"

TEST_ZLIB_RECIPE = """\
package: zlib
version: v1.3.1
source: https://github.com/madler/zlib
tag: master
---
./configure
make
make install
"""
TEST_ZLIB_GIT_REFS = "8822efa61f2a385e0bc83ca5819d608111b2168a\trefs/heads/master"
TEST_ZLIB_BUILD_HASH = "4d6a75f214dc7931a2a7d5ba82ea0568e652cd84"

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
TEST_ROOT_BUILD_HASH = ("1f3c771080f71b6c0d2e3d7a285698a20035da12")


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
TEST_EXTRA_BUILD_HASH = ("6e7bc4976abf77b558cf7faf575ec51670f8d0e5")


GIT_CLONE_REF_ZLIB_ARGS = ("clone", "--bare", "https://github.com/madler/zlib",
                           "/sw/MIRROR/zlib", "--filter=blob:none"), ".", False
GIT_CLONE_SRC_ZLIB_ARGS = ("clone", "-n", "https://github.com/madler/zlib",
                           "/sw/SOURCES/zlib/v1.3.1/8822efa61f",
                           "--dissociate", "--reference", "/sw/MIRROR/zlib", "--filter=blob:none"), ".", False
GIT_SET_URL_ZLIB_ARGS = ("remote", "set-url", "--push", "origin", "https://github.com/madler/zlib"), \
    "/sw/SOURCES/zlib/v1.3.1/8822efa61f", False
GIT_CHECKOUT_ZLIB_ARGS = ("checkout", "-f", "master"), \
    "/sw/SOURCES/zlib/v1.3.1/8822efa61f", False

GIT_FETCH_REF_ROOT_ARGS = ("fetch", "-f", "--prune", "--filter=blob:none", "https://github.com/root-mirror/root", "+refs/tags/*:refs/tags/*",
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
                f"/sw/{TEST_ARCHITECTURE}/defaults-release/v1-1/.build-hash": (1, StringIO(TEST_DEFAULT_RELEASE_BUILD_HASH)),
                f"/sw/{TEST_ARCHITECTURE}/zlib/v1.3.1-local1/.build-hash": (1, StringIO(TEST_ZLIB_BUILD_HASH)),
                f"/sw/{TEST_ARCHITECTURE}/ROOT/v6-08-30-local1/.build-hash": (1, StringIO(TEST_ROOT_BUILD_HASH))
            }[x]
        except KeyError:
            return DEFAULT
        if threshold > TIMES_ASKED.get(x, 0):
            result = None
        TIMES_ASKED[x] = TIMES_ASKED.get(x, 0) + 1
        if not result:
            raise OSError
        return result
    return DEFAULT


def dummy_execute(x, **kwds):
    s = " ".join(x) if isinstance(x, list) else x
    if re.match(".*ln -sfn.*TARS", s):
        return 0
    return {
        f"/bin/bash -e -x /sw/SPECS/{TEST_ARCHITECTURE}/defaults-release/v1-1/build.sh 2>&1": 0,
        f'/bin/bash -e -x /sw/SPECS/{TEST_ARCHITECTURE}/zlib/v1.3.1-local1/build.sh 2>&1': 0,
        f'/bin/bash -e -x /sw/SPECS/{TEST_ARCHITECTURE}/ROOT/v6-08-30-local1/build.sh 2>&1': 0,
    }[s]


def dummy_readlink(x):
    return {
        f"/sw/TARS/{TEST_ARCHITECTURE}/defaults-release/defaults-release-v1-1.{TEST_ARCHITECTURE}.tar.gz":
        f"../../{TEST_ARCHITECTURE}/store/{TEST_DEFAULT_RELEASE_BUILD_HASH[:2]}/{TEST_DEFAULT_RELEASE_BUILD_HASH}/defaults-release-v1-1.{TEST_ARCHITECTURE}.tar.gz"
    }[x]


def dummy_exists(x):
    # Convert Path objects to strings for comparison
    path_str = str(x) if hasattr(x, '__fspath__') else x
    if path_str.endswith("alibuild_helpers/.git"):
        return False
    # Return False for any sapling-related paths
    if ".sl" in path_str or path_str.endswith("/sl"):
        return False
    return {
        "/alidist": True,
        "/alidist/.git": True,
        "/sw": True,
        "/sw/SPECS": False,
        "/sw/MIRROR/root": True,
        "/sw/MIRROR/root/.git": True,
        "/sw/MIRROR/zlib": False,
    }.get(path_str, DEFAULT)


# A few errors we should handle, together with the expected result
@patch("alibuild_helpers.git.clone_speedup_options",
       new=MagicMock(return_value=["--filter=blob:none"]))
@patch("alibuild_helpers.build.BASH", new="/bin/bash")
class BuildTestCase(unittest.TestCase):
    @patch("alibuild_helpers.analytics", new=MagicMock())
    @patch("requests.Session.get", new=MagicMock())
    @patch("alibuild_helpers.sync.execute", new=dummy_execute)
    @patch("alibuild_helpers.build.snapshot_source")
    @patch("alibuild_helpers.build.build_ac_entry")
    @patch("alibuild_helpers.git.git")
    @patch("alibuild_helpers.build.exists", new=MagicMock(side_effect=dummy_exists))
    @patch("os.path.exists", new=MagicMock(side_effect=dummy_exists))
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
        f"/sw/TARS/{TEST_ARCHITECTURE}/store/{TEST_DEFAULT_RELEASE_BUILD_HASH[:2]}/{TEST_DEFAULT_RELEASE_BUILD_HASH}/*gz": [],
        f"/sw/TARS/{TEST_ARCHITECTURE}/store/{TEST_ZLIB_BUILD_HASH[:2]}/{TEST_ZLIB_BUILD_HASH}/*gz": [],
        f"/sw/TARS/{TEST_ARCHITECTURE}/store/{TEST_ROOT_BUILD_HASH[:2]}/{TEST_ROOT_BUILD_HASH}/*gz": [],
        f"/sw/TARS/{TEST_ARCHITECTURE}/defaults-release/defaults-release-v1-1.{TEST_ARCHITECTURE}.tar.gz":
        [f"../../{TEST_ARCHITECTURE}/store/{TEST_DEFAULT_RELEASE_BUILD_HASH[:2]}/{TEST_DEFAULT_RELEASE_BUILD_HASH}/defaults-release-v1-1.{TEST_ARCHITECTURE}.tar.gz"],
    }[pattern])
    @patch("alibuild_helpers.build.readlink", new=dummy_readlink)
    @patch("alibuild_helpers.build.banner", new=MagicMock(return_value=None))
    @patch("alibuild_helpers.build.debug")
    @patch("alibuild_helpers.workarea.is_writeable", new=MagicMock(return_value=True))
    @patch("alibuild_helpers.build.basename", new=MagicMock(return_value="aliBuild"))
    @patch("alibuild_helpers.build.install_wrapper_script", new=MagicMock())
    def test_coverDoBuild(self, mock_debug, mock_listdir, mock_warning, mock_git_git,
                          mock_build_ac_entry, mock_snapshot_source) -> None:
        mock_git_git.side_effect = dummy_git
        mock_debug.side_effect = lambda *args: None
        mock_warning.side_effect = lambda *args: None
        mock_listdir.side_effect = lambda directory: {
            f"/sw/TARS/{TEST_ARCHITECTURE}/defaults-release": [f"defaults-release-v1-1.{TEST_ARCHITECTURE}.tar.gz"],
            f"/sw/TARS/{TEST_ARCHITECTURE}/zlib": [],
            f"/sw/TARS/{TEST_ARCHITECTURE}/ROOT": [],
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
            architecture=TEST_ARCHITECTURE,
            workDir="/sw",
            pkgname=["root"],
            configDir="/alidist",
            disable=[],
            force_rebuild=[],
            defaults="release",
            jobs=2,
            annotate={},
            preferSystem=[],
            noSystem=None,
            debug=True,
            dryRun=False,
            aggressiveCleanup=False,
            environment=[],
            autoCleanup=False,
            noDevel=[],
            onlyDeps=False,
            fetchRepos=False,
            forceTracked=False,
            plugin="legacy"
        )

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
        mock_listdir.assert_called_with(f"/sw/TARS/{TEST_ARCHITECTURE}/ROOT")
        # We can't compare directly against the list of calls here as they
        # might happen in any order.
        mock_git_git.assert_has_calls(common_calls + [
            mkcall(GIT_FETCH_REF_ROOT_ARGS),
        ], any_order=True)
        self.assertEqual(mock_git_git.call_count, len(common_calls) + 1)

        # Isolation guard (Layer 2): a non-reapi build (here no remote store) must
        # never touch the reapi Action Cache / source-snapshot machinery -- the
        # existing build+upload path stays byte-identical for b3://, s3://, ... .
        mock_build_ac_entry.assert_not_called()
        mock_snapshot_source.assert_not_called()

    def setup_spec(self, script):
        """Parse the alidist recipe in SCRIPT and return its spec."""
        err, spec, recipe = parseRecipe(lambda: script)
        self.assertIsNone(err)
        spec["recipe"] = "" if spec["package"].startswith("defaults-") else recipe.strip("\n")
        spec.setdefault("tag", spec["version"])
        spec["tag"] = resolve_tag(spec)
        return spec

    def test_hashing(self) -> None:
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

    def test_build_validate_system_entry(self) -> None:
        """build_validate_system_entry records a tarball-less validate-system
        action: the recipe (with its system check), keyed by the recipe digest so
        dependents that reference it (also by recipe digest) resolve to it."""
        import hashlib
        from alibuild_helpers.build import build_validate_system_entry
        recipe = "package: yacc-like\nsystem_requirement: yacc\n"
        digest = hashlib.sha256(recipe.encode("utf-8")).hexdigest()
        yacc = {"package": "yacc-like", "version": "v1", "fullRecipe": recipe}
        entry = build_validate_system_entry(yacc, {}, "slc7_x86-64")
        action = entry["action"]
        self.assertEqual(action["kind"], "validate-system")
        self.assertEqual(action["package"], "yacc-like")
        # Keyed by the recipe digest (not a build action hash), and defaults
        # revision to "1" when the system spec has none.
        self.assertEqual(action["actionHash"], digest)
        self.assertEqual(action["recipeDigest"], "sha256:" + digest)
        self.assertEqual(action["revision"], "1")
        self.assertEqual(action["architecture"], "slc7_x86-64")
        self.assertNotIn("result", entry)   # produces no tarball
        self.assertEqual(action["deps"], [])

    def test_build_ac_entry_references_system_deps(self) -> None:
        """A built package's AC entry references its satisfied system deps by their
        recipe digest, so reconstruct walks to the validate-system entry."""
        import hashlib
        from alibuild_helpers.build import build_ac_entry, system_recipe_digest
        make_recipe = "package: make\nsystem_requirement: '.*'\n"
        make_spec = {"package": "make", "fullRecipe": make_recipe}
        spec = {"package": "probe", "version": "1", "revision": "1",
                "remote_revision_hash": "p" * 40, "commit_hash": "0",
                "scm_refs": {}, "full_requires": [], "system_requires": ["make"]}
        entry = build_ac_entry(spec, {"probe": spec}, "slc7_x86-64",
                               system_specs={"make": make_spec})
        self.assertEqual(entry["action"]["deps"],
                         [{"package": "make",
                           "actionHash": system_recipe_digest(make_spec)}])

    def test_build_ac_entry(self) -> None:
        """build_ac_entry records the provenance needed to rebuild/install."""
        import hashlib
        default = self.setup_spec(TEST_DEFAULT_RELEASE)
        zlib = self.setup_spec(TEST_ZLIB_RECIPE)
        default["commit_hash"] = "0"
        zlib.setdefault("requires", []).append(default["package"])
        zlib["scm_refs"] = {ref: githash for githash, _, ref in (
            line.partition("\t") for line in TEST_ZLIB_GIT_REFS.splitlines())}
        try:
            zlib["commit_hash"] = zlib["scm_refs"]["refs/tags/" + zlib["tag"]]
        except KeyError:
            zlib["commit_hash"] = zlib["scm_refs"]["refs/heads/" + zlib["tag"]]
        specs = {pkg["package"]: pkg for pkg in (default, zlib)}
        for spec in specs.values():
            spec["is_devel_pkg"] = False

        storeHashes("defaults-release", specs, considerRelocation=False)
        default["hash"] = default["remote_revision_hash"]
        storeHashes("zlib", specs, considerRelocation=False)
        zlib["hash"] = zlib["remote_revision_hash"]
        zlib["revision"] = "1"
        # These closures are normally computed in doBuild() before upload.
        zlib["full_requires"] = {"defaults-release"}
        zlib["full_runtime_requires"] = set()
        zlib["relocate_paths"] = ["lib", "bin"]

        container = {"runtime": "docker", "image": "alisw/slc7-builder:latest",
                     "digest": "sha256:abc"}
        refs_artifact = {"type": "git-refs", "source": "u", "digest": "r" * 64}
        entry = build_ac_entry(zlib, specs, "slc7_x86-64", container=container,
                               refs_artifact=refs_artifact)
        self.assertEqual(entry["schemaVersion"], 2)
        action = entry["action"]
        # Container + refs provenance are recorded verbatim for a reproducible env.
        self.assertEqual(action["container"], container)
        self.assertEqual(action["refsArtifact"], refs_artifact)
        self.assertEqual(action["package"], "zlib")
        self.assertEqual(action["version"], zlib["version"])
        self.assertEqual(action["revision"], "1")
        self.assertEqual(action["architecture"], "slc7_x86-64")
        # The entry is keyed by the action hash, and deps are referenced by
        # *their* action hash, so the recorded DAG matches storeHashes().
        self.assertEqual(action["actionHash"], zlib["remote_revision_hash"])
        self.assertEqual(action["deps"],
                         [{"package": "defaults-release", "actionHash": default["hash"]}])
        self.assertEqual(action["runtimeDeps"], [])
        self.assertEqual(action["depsHash"], zlib["deps_hash"])
        # The recipe digest is the sha256 of the *full* recipe (a CAS blob),
        # so the build can be reconstructed without an alidist checkout.
        self.assertEqual(action["recipeDigest"], "sha256:" +
                         hashlib.sha256(zlib["fullRecipe"].encode("utf-8")).hexdigest())
        self.assertEqual(action["source"], zlib.get("source"))
        self.assertEqual(action["relocatePaths"], ["bin", "lib"])  # sorted
        self.assertEqual(action["commit"]["ref"], zlib["commit_hash"])
        # The output digest/size are filled in by the backend at upload time.
        self.assertNotIn("result", entry)

    def test_snapshot_source_gating(self) -> None:
        """snapshot_source only archives for git, non-devel packages going to a
        reapi store; everything else is a no-op (and never touches git)."""
        from alibuild_helpers.build import snapshot_source
        from alibuild_helpers import sync
        # Not a reapi store -> never snapshots.
        self.assertIsNone(snapshot_source({"package": "x"}, sync.NoRemoteSync()))
        # reapi store, but devel / source-less packages are skipped before git.
        with patch.object(sync_reapi.REAPIRemoteSync, "_s3_init", lambda self: None):
            reapi = sync_reapi.REAPIRemoteSync("reapi://h/b", "reapi://h/b",
                                         "slc7_x86-64", "/sw")
        self.assertIsNone(snapshot_source(
            {"package": "x", "is_devel_pkg": True, "source": "u", "reference": "r"}, reapi))
        self.assertIsNone(snapshot_source(
            {"package": "x", "is_devel_pkg": False}, reapi))  # no source

    def test_snapshot_source_resolves_commit_from_refs(self) -> None:
        """A reconstruct rebuild's restored source is a working checkout without the
        tag ref, so `git rev-parse <tag>^{commit}` fails. snapshot_source must instead
        resolve commit_hash via scm_refs (idempotent snapshot then preserves the
        archived-source reference in the regenerated AC entry)."""
        from alibuild_helpers.build import snapshot_source
        from alibuild_helpers import sync
        from alibuild_helpers.git import Git
        with patch.object(sync_reapi.REAPIRemoteSync, "_s3_init", lambda self: None):
            reapi = sync_reapi.REAPIRemoteSync("reapi://h/b", "reapi://h/b", "slc7_x86-64", "/sw")
        spec = {"package": "zlib", "is_devel_pkg": False, "source": "https://x/zlib",
                "reference": "/ref", "commit_hash": "v1.3.1", "scm": Git(),
                "scm_refs": {"refs/tags/v1.3.1": "d" * 40}}
        captured = {}

        class FakeStore:
            def __init__(self, _sync): pass
            def snapshot(self, repo, url, commit):
                captured["commit"] = commit
                return {"type": "git", "commit": commit}

        def fake_git(args, directory=None, check=True, **kw):
            if args[:2] == ("config", "--get"):
                return ("", "")   # not a partial clone
            raise AssertionError("git rev-parse must not run when scm_refs resolves")

        with patch("alibuild_helpers.build.GitSourceStore", FakeStore), \
             patch("alibuild_helpers.build.git", side_effect=fake_git):
            art = snapshot_source(spec, reapi)
        self.assertEqual(captured["commit"], "d" * 40)   # resolved from scm_refs
        self.assertEqual(art["commit"], "d" * 40)

    def test_snapshot_refs_gating(self) -> None:
        """snapshot_refs only archives scm_refs for non-devel packages going to
        a reapi store."""
        from alibuild_helpers.build import snapshot_refs
        from alibuild_helpers import sync
        self.assertIsNone(snapshot_refs({"package": "x"}, sync.NoRemoteSync()))
        with patch.object(sync_reapi.REAPIRemoteSync, "_s3_init", lambda self: None):
            reapi = sync_reapi.REAPIRemoteSync("reapi://h/b", "reapi://h/b",
                                         "slc7_x86-64", "/sw")
        self.assertIsNone(snapshot_refs(
            {"package": "x", "is_devel_pkg": True, "scm_refs": {"a": "b"}}, reapi))
        self.assertIsNone(snapshot_refs({"package": "x"}, reapi))  # no scm_refs

    def test_initdotsh(self) -> None:
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
        self.assertIn('. "$WORK_DIR/$ALIBUILD_ARCH_PREFIX"/zlib/v1.3.1-1/etc/profile.d/init.sh', setup_initdotsh)
        self.assertIn('. "$WORK_DIR/$ALIBUILD_ARCH_PREFIX"/zlib/v1.3.1-1/etc/profile.d/init.sh', complete_initdotsh)

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

    def test_build_template_percent_format(self) -> None:
        """build_template.sh is interpolated via printf-style % formatting in
        doBuild(), so every literal '%' in it must be doubled. A stray '%'
        raises at build time but is not covered by the unit tests that mock the
        build out, so check the real template formats cleanly here."""
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "alibuild_helpers", "build_template.sh")
        with open(template_path) as templatef:
            template = templatef.read()
        # These are exactly the keys doBuild() substitutes (see build.py).
        keys = ("provenance", "initdotsh_deps", "initdotsh_full", "develPrefix",
                "workDir", "configDir", "incremental_recipe", "requires",
                "build_requires", "runtime_requires")
        try:
            template % {key: "" for key in keys}
        except (TypeError, ValueError, KeyError) as exc:
            self.fail("build_template.sh does not %%-format cleanly (likely an "
                      "unescaped '%%' that should be '%%%%'): %s" % exc)


class AlidistHashFallbackTestCase(unittest.TestCase):
    """doBuild honours a pre-set ALIBUILD_ALIDIST_HASH when there is no SCM
    checkout to read (the `aliBuild reconstruct` path), and still dies otherwise.
    Only the ALIBUILD_ALIDIST_HASH block is exercised: install_wrapper_script,
    which runs just after it, raises _Bound to stop doBuild there."""

    class _Bound(Exception):
        """Marker: doBuild reached just past the ALIBUILD_ALIDIST_HASH block."""

    def _run_reaching_scm_block(self):
        from alibuild_helpers.scm import SCMError
        from alibuild_helpers.git import Git
        args = Namespace(
            remoteStore="", writeStore="", architecture=TEST_ARCHITECTURE,
            docker=False, dockerImage=None, workDir="/sw", pkgname=["zlib"],
            configDir="/no-such-alidist", disable=[], defaults="release", jobs=2,
        )
        with patch("alibuild_helpers.build.exists", new=MagicMock(return_value=True)), \
             patch("alibuild_helpers.build.pruneWorkdirFromPaths", new=MagicMock()), \
             patch("alibuild_helpers.build.makedirs", new=MagicMock()), \
             patch("alibuild_helpers.build.git",
                   new=MagicMock(return_value=("", "refs/heads/master"))), \
             patch("alibuild_helpers.build.parseDefaults",
                   new=MagicMock(return_value=(None, {}, {}))), \
             patch.object(Git, "checkedOutCommitName",
                          side_effect=SCMError("no checkout")), \
             patch("alibuild_helpers.build.install_wrapper_script",
                   side_effect=self._Bound()):
            doBuild(args, MagicMock())

    def test_preset_hash_is_honoured_without_checkout(self) -> None:
        """A pre-set value survives when checkedOutCommitName raises (no die)."""
        os.environ["ALIBUILD_ALIDIST_HASH"] = "preset123"
        try:
            with self.assertRaises(self._Bound):
                self._run_reaching_scm_block()
            self.assertEqual(os.environ["ALIBUILD_ALIDIST_HASH"], "preset123")
        finally:
            os.environ.pop("ALIBUILD_ALIDIST_HASH", None)

    def test_missing_hash_without_checkout_dies(self) -> None:
        """With no checkout and nothing pre-set, doBuild still dies (old behaviour)."""
        os.environ.pop("ALIBUILD_ALIDIST_HASH", None)
        with self.assertRaises(SystemExit):
            self._run_reaching_scm_block()




class SelectCachedTarballTestCase(unittest.TestCase):
    """A cached tarball is only reusable at the revision it was packaged under.

    The store is keyed by hash, so a rebuilt package lands in the same directory
    as the one built before it; only the file name carries the revision. Picking
    the wrong one used to skip packaging (build_template.sh tars only when there
    is no cached tarball) and then crash in the upload -- after the symlink claim
    and the dist links had already gone out, so the store was left advertising a
    tarball that was never written.
    """

    WANTED = "QualityControl-v1.195.4-2.slc10_x86-64.tar.gz"
    DIR = "sw/TARS/slc10_x86-64/store/7e/7e875fbe"

    def path(self, name):
        return os.path.join(self.DIR, name)

    def test_exact_revision_is_reused(self):
        self.assertEqual(
            select_cached_tarball([self.path(self.WANTED)], self.WANTED, uploading=True),
            self.path(self.WANTED))

    def test_other_revision_is_rejected_when_uploading(self):
        """The regression: -1 on disk, -2 to publish. Rebuild instead."""
        stale = self.path("QualityControl-v1.195.4-1.slc10_x86-64.tar.gz")
        self.assertEqual(select_cached_tarball([stale], self.WANTED, uploading=True), "")

    def test_other_revision_is_fine_when_not_uploading(self):
        """Without a write store nothing needs the name to match, and the unpack
        path relocates whatever revision it finds -- so keep the cheap reuse."""
        stale = self.path("QualityControl-v1.195.4-1.slc10_x86-64.tar.gz")
        self.assertEqual(select_cached_tarball([stale], self.WANTED, uploading=False), stale)

    def test_exact_match_wins_over_a_stale_neighbour(self):
        """Both present: the old code took glob order, which is arbitrary."""
        stale = self.path("QualityControl-v1.195.4-1.slc10_x86-64.tar.gz")
        for order in ([stale, self.path(self.WANTED)], [self.path(self.WANTED), stale]):
            for uploading in (True, False):
                self.assertEqual(
                    select_cached_tarball(order, self.WANTED, uploading=uploading),
                    self.path(self.WANTED))

    def test_no_tarballs_means_no_cache(self):
        for uploading in (True, False):
            self.assertEqual(select_cached_tarball([], self.WANTED, uploading=uploading), "")



class BoundUnpublishedRebuildTestCase(unittest.TestCase):
    """A package that cannot be published must not be rebuilt forever.

    upload_symlinks_and_tarball adopts an existing legacy tarball as
    already-uploaded without writing an Action Cache entry, while is_published()
    only asks the AC. For a pre-2.0 tarball both stay true forever, and the
    rebuild-to-fix-it path loops -- 1743 rebuilds of defaults-release in 26
    minutes on the first ubuntu2204 release attempt.
    """

    def test_first_visit_allows_the_rebuild(self):
        rebuilt = set()
        bound_unpublished_rebuild("defaults-release", rebuilt, "alibuild-ac")
        self.assertEqual(rebuilt, {"defaults-release"})

    def test_second_visit_dies_rather_than_looping(self):
        rebuilt = {"defaults-release"}
        with self.assertRaises(SystemExit):
            bound_unpublished_rebuild("defaults-release", rebuilt, "alibuild-ac")

    def test_the_error_says_how_to_fix_it(self):
        """A bare 'cannot publish' would leave the reader nowhere: the remedy is
        migration, not a retry, so the message has to name it."""
        rebuilt = {"defaults-release"}
        # dieOnError logs through alibuild_helpers.log.error; build.py never
        # imports `error` itself, so patching it there raises AttributeError.
        with self.assertRaises(SystemExit), \
             patch("alibuild_helpers.log.error") as mock_error:
            bound_unpublished_rebuild("defaults-release", rebuilt, "alibuild-ac")
        msg = " ".join(str(a) for a in mock_error.call_args[0])
        self.assertIn("aliBuild migrate", msg)
        self.assertIn("defaults-release", msg)
        self.assertIn("alibuild-ac", msg)

    def test_packages_are_bounded_independently(self):
        """One package exhausting its rebuild must not block another's first."""
        rebuilt = {"defaults-release"}
        bound_unpublished_rebuild("zlib", rebuilt, "alibuild-ac")
        self.assertEqual(rebuilt, {"defaults-release", "zlib"})

if __name__ == '__main__':
    unittest.main()

