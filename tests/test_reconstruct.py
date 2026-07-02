import os
import os.path
import tempfile
import unittest
from argparse import Namespace
from unittest.mock import patch

from alibuild_helpers import sync
from alibuild_helpers.reconstruct import (
    walk_build_closure, find_missing_blobs, materialize_recipes, doReconstruct,
    restore_sources)

ARCH = "slc7_x86-64"


def make_entry(pkg, version, revision, content_hash, recipe_hash,
               deps=(), container=None):
    return {
        "schemaVersion": 2,
        "action": {
            "package": pkg, "version": version, "revision": revision,
            "architecture": ARCH, "actionHash": "hash-" + pkg,
            "recipeDigest": "sha256:" + recipe_hash,
            "container": container,
            "deps": [{"package": p, "actionHash": "hash-" + p} for p in deps],
            "runtimeDeps": [],
        },
        "result": {"tarball": "%s-%s-%s.%s.tar.gz" % (pkg, version, revision, ARCH),
                   "outputDigest": "sha256:" + content_hash, "size": 1},
    }


class FakeSync(sync.REAPIRemoteSync):
    """A REAPIRemoteSync whose CAS/AC reads come from in-memory fixtures."""

    def __init__(self, entries, blobs_present, recipe_blobs, label_to_hash):
        self.architecture = ARCH
        self._entries = entries              # action hash -> AC entry
        self._present = set(blobs_present)   # content hashes present in the CAS
        self._recipes = recipe_blobs         # recipe content hash -> bytes
        self._labels = label_to_hash

    def read_ac_entry(self, action_hash):
        return self._entries.get(action_hash)

    def resolve_action_hash(self, package, version, revision=None):
        return self._labels.get((package, version, revision))

    def artifact_blob_exists(self, content_hash, algo="sha256"):
        return content_hash in self._present

    def read_blob(self, content_hash, algo="sha256"):
        return self._recipes[content_hash]


class ReconstructTestCase(unittest.TestCase):
    def setUp(self):
        # zlib depends on GCC; GCC depends on defaults-release.
        self.entries = {
            "hash-zlib": make_entry("zlib", "v1", "1", "czlib", "rzlib",
                                    deps=["GCC"],
                                    container={"runtime": "docker",
                                               "image": "alisw/slc7-builder:latest",
                                               "digest": "alisw/slc7-builder@sha256:abc"}),
            "hash-GCC": make_entry("GCC", "v9", "2", "cgcc", "rgcc",
                                   deps=["defaults-release"]),
            "hash-defaults-release": make_entry("defaults-release", "v1", "1",
                                                "cdef", "rdef"),
        }
        self.recipes = {"rzlib": b"package: zlib\n---\nbuild zlib\n",
                        "rgcc": b"package: GCC\n---\nbuild gcc\n",
                        "rdef": b"package: defaults-release\n---\n"}
        self.labels = {("zlib", "v1", None): "hash-zlib",
                       ("zlib", "v1", "1"): "hash-zlib"}

    def make_sync(self, present):
        return FakeSync(self.entries, present, self.recipes, self.labels)

    def test_walk_build_closure_postorder(self):
        s = self.make_sync(present=())
        closure = walk_build_closure(s, "hash-zlib")
        names = [e["action"]["package"] for e in closure]
        # Dependencies must come before the packages that need them.
        self.assertEqual(names, ["defaults-release", "GCC", "zlib"])

    def test_find_missing_blobs(self):
        # Only GCC's blob is present; the other two are missing.
        s = self.make_sync(present={"cgcc"})
        missing = find_missing_blobs(s, walk_build_closure(s, "hash-zlib"))
        self.assertEqual({e["action"]["package"] for e in missing},
                         {"zlib", "defaults-release"})

    def test_materialize_recipes(self):
        s = self.make_sync(present=())
        with tempfile.TemporaryDirectory() as cfg:
            written = materialize_recipes(s, walk_build_closure(s, "hash-zlib"), cfg)
            self.assertEqual(len(written), 3)
            # Files are named <package>.sh (lowercased) and hold the full recipe.
            with open(os.path.join(cfg, "zlib.sh"), "rb") as zf:
                self.assertEqual(zf.read(), self.recipes["rzlib"])
            self.assertTrue(os.path.exists(os.path.join(cfg, "gcc.sh")))
            self.assertTrue(os.path.exists(os.path.join(cfg, "defaults-release.sh")))

    def test_doReconstruct_nothing_missing(self):
        s = self.make_sync(present={"czlib", "cgcc", "cdef"})
        args = Namespace(package="zlib", version="v1", revision=None, architecture=ARCH,
                         remoteStore="reapi://localhost/bucket", insecure=False,
                         workDir="/sw", outputConfig=None)
        with patch("alibuild_helpers.reconstruct.remote_from_url", return_value=s):
            # All blobs present -> succeeds without materialising anything.
            self.assertTrue(doReconstruct(args, None))

    def test_doReconstruct_materializes_when_missing(self):
        s = self.make_sync(present=())
        with tempfile.TemporaryDirectory() as workdir:
            args = Namespace(package="zlib", version="v1", revision=None, architecture=ARCH,
                             remoteStore="reapi://localhost/bucket", insecure=False,
                             workDir=workdir, outputConfig=None)
            with patch("alibuild_helpers.reconstruct.remote_from_url", return_value=s):
                self.assertTrue(doReconstruct(args, None))
            cfg = os.path.join(workdir, "reconstruct-zlib")
            self.assertTrue(os.path.exists(os.path.join(cfg, "zlib.sh")))
            self.assertTrue(os.path.exists(os.path.join(cfg, "gcc.sh")))

    def test_restore_sources(self):
        s = self.make_sync(present=())
        # zlib has an archived source artifact (and refs); the others don't.
        self.entries["hash-zlib"]["action"]["sourceArtifact"] = {
            "type": "git", "commit": "deadbeef", "baseDigest": None,
            "deltaDigest": "abc"}
        self.entries["hash-zlib"]["action"]["refsArtifact"] = {
            "type": "git-refs", "digest": "r" * 64}
        closure = walk_build_closure(s, "hash-zlib")
        with patch("alibuild_helpers.reconstruct.GitSourceStore") as gss, \
             patch("alibuild_helpers.reconstruct.load_refs", return_value={}) as load, \
             patch("alibuild_helpers.reconstruct.apply_refs") as apply_:
            restored, from_upstream = restore_sources(s, closure, "/tmp/ref")
        self.assertEqual(restored, ["zlib"])
        self.assertEqual(set(from_upstream), {"GCC", "defaults-release"})
        gss.return_value.restore.assert_called_once()
        # The cached tag mapping is reapplied so tags resolve offline.
        load.assert_called_once()
        apply_.assert_called_once()

    def test_doReconstruct_requires_reapi_store(self):
        args = Namespace(package="zlib", version="v1", revision=None, architecture=ARCH,
                         remoteStore="https://s3.cern.ch/foo", insecure=False,
                         workDir="/sw", outputConfig=None)
        self.assertRaises(SystemExit, doReconstruct, args, None)


if __name__ == "__main__":
    unittest.main()
