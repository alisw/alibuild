import hashlib
import os
import os.path
import shutil
import tempfile
import unittest
from argparse import Namespace
from unittest.mock import patch, MagicMock

from alibuild_helpers import sync
from alibuild_helpers import sync_reapi
from alibuild_helpers.reconstruct import (
    walk_build_closure, find_missing_blobs, materialize_recipes, doReconstruct,
    recipe_package_name, defaults_from_closure,
    restore_sources, verify_closure, verify_rebuild, _rebuilt_tarball,
    _rebuild_verdict, do_rebaseline, do_persist, RebuildResult)

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


class FakeSync(sync_reapi.REAPIRemoteSync):
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
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

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

    def _use_o2_defaults(self):
        """alibuild injects every defaults flavour under the single node name
        `defaults-release`, so the archived recipe legitimately declares a
        different package. Reproduce that shape."""
        self.recipes["rdef"] = b"package: defaults-o2\n---\n"

    def test_recipe_package_name_reads_the_header_only(self):
        self.assertEqual(recipe_package_name(b"package: defaults-o2\n---\n"),
                         "defaults-o2")
        # A `package:` line in the *body* must not be mistaken for the header.
        self.assertEqual(recipe_package_name(b"---\npackage: nonsense\n"), "")
        self.assertEqual(recipe_package_name(b"version: v1\n---\n"), "")

    def test_materialize_names_defaults_after_the_declared_package(self):
        # Writing an o2 defaults recipe out as defaults-release.sh makes the
        # rebuild reject the file for disagreeing with its own package field.
        self._use_o2_defaults()
        s = self.make_sync(present=())
        with tempfile.TemporaryDirectory() as cfg:
            materialize_recipes(s, walk_build_closure(s, "hash-zlib"), cfg)
            self.assertTrue(os.path.exists(os.path.join(cfg, "defaults-o2.sh")))
            self.assertFalse(os.path.exists(os.path.join(cfg, "defaults-release.sh")))

    def test_defaults_recovered_from_the_archived_recipe(self):
        self._use_o2_defaults()
        s = self.make_sync(present=())
        closure = walk_build_closure(s, "hash-zlib")
        # The AC entries carry no `defaults` field (migrated ones never do), so
        # the flavour has to come from the recipe the ledger archived.
        self.assertEqual(defaults_from_closure(s, closure), "o2")

    def test_defaults_recovery_is_release_for_a_plain_build(self):
        s = self.make_sync(present=())
        self.assertEqual(
            defaults_from_closure(s, walk_build_closure(s, "hash-zlib")), "release")

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

    def _verify_sync(self, present, sources=None, break_recipe=None):
        """A FakeSync whose recipe blobs have *real* sha256 digests (so recipe
        integrity checks are meaningful), with a configurable set of present CAS
        blobs, per-package sources, and an optionally-corrupted recipe."""
        recipes = {"zlib": b"r-zlib", "GCC": b"r-gcc", "defaults-release": b"r-def"}
        dig = {p: hashlib.sha256(b).hexdigest() for p, b in recipes.items()}

        def entry(pkg, ver, rev, chash, deps=()):
            e = make_entry(pkg, ver, rev, chash, dig[pkg], deps=deps)
            if sources and pkg in sources:
                e["action"]["source"] = sources[pkg]
            return e

        entries = {
            "hash-zlib": entry("zlib", "v1", "1", "czlib", deps=["GCC"]),
            "hash-GCC": entry("GCC", "v9", "2", "cgcc", deps=["defaults-release"]),
            "hash-defaults-release": entry("defaults-release", "v1", "1", "cdef"),
        }
        recipe_blobs = {dig[p]: b for p, b in recipes.items()}
        if break_recipe:
            recipe_blobs[dig[break_recipe]] = b"tampered"   # sha256 no longer matches
        labels = {("zlib", "v1", None): "hash-zlib", ("zlib", "v1", "1"): "hash-zlib"}
        return FakeSync(entries, present, recipe_blobs, labels)

    def test_find_missing_blobs_skips_validate_system(self):
        # A validate-system entry has no output digest; it must be skipped, not
        # flagged as a missing blob.
        s = self.make_sync(present=set())
        sys_entry = {"action": {"kind": "validate-system", "package": "yacc-like",
                                "recipeDigest": "sha256:ryacc"}}
        build_entry = make_entry("zlib", "v1", "1", "czlib", "rzlib")
        missing = find_missing_blobs(s, [sys_entry, build_entry])
        self.assertEqual([e["action"]["package"] for e in missing], ["zlib"])

    def test_verify_closure_reports_system(self):
        yacc_recipe = b"package: yacc-like\nsystem_requirement: yacc\n"
        zlib_recipe = b"package: zlib\n"
        yd = hashlib.sha256(yacc_recipe).hexdigest()
        zd = hashlib.sha256(zlib_recipe).hexdigest()
        zlib_entry = make_entry("zlib", "v1", "1", "czlib", zd)
        sys_entry = {"schemaVersion": 2, "action": {
            "kind": "validate-system", "package": "yacc-like", "version": "v1",
            "revision": "1", "architecture": ARCH, "actionHash": "hash-yacc",
            "recipeDigest": "sha256:" + yd, "deps": []}}
        s = FakeSync(entries={}, blobs_present={"czlib"},
                     recipe_blobs={yd: yacc_recipe, zd: zlib_recipe}, label_to_hash={})
        rows, ok = verify_closure(s, [sys_entry, zlib_entry])
        self.assertTrue(ok)
        by = {r["package"]: r for r in rows}
        # The system package is reported as 'system' (revalidated on host), never
        # reused/rebuilt, with its recipe verified and no source.
        self.assertEqual(by["yacc-like"]["action"], "system")
        self.assertTrue(by["yacc-like"]["recipe_ok"])
        self.assertEqual(by["yacc-like"]["source"], "n/a")
        self.assertEqual(by["zlib"]["action"], "reuse")

    def test_verify_closure_reports_legacy(self):
        # A legacy (pre-provenance) entry: no recipe, keyed by content hash. It is
        # reported as 'legacy', skipped by find_missing_blobs, and only "ok" while
        # its blob survives (it can never be rebuilt).
        legacy_entry = {"schemaVersion": 2, "action": {
            "kind": "legacy", "package": "bz2", "version": "1.0.8", "revision": "1",
            "architecture": ARCH, "actionHash": "chash-bz2"},
            "result": {"tarball": "bz2-1.0.8-1.%s.tar.gz" % ARCH,
                       "outputDigest": "sha256:chash-bz2", "size": 1}}
        present = FakeSync(entries={}, blobs_present={"chash-bz2"},
                           recipe_blobs={}, label_to_hash={})
        rows, ok = verify_closure(present, [legacy_entry])
        self.assertTrue(ok)
        self.assertEqual(rows[0]["action"], "legacy")
        self.assertEqual(rows[0]["source"], "n/a")
        self.assertTrue(rows[0]["regenerable"])          # present -> fine
        self.assertEqual(find_missing_blobs(present, [legacy_entry]), [])  # never a rebuild target
        # If its blob is lost, it is flagged non-regenerable (gone for good).
        lost = FakeSync(entries={}, blobs_present=set(), recipe_blobs={}, label_to_hash={})
        rows, ok = verify_closure(lost, [legacy_entry])
        self.assertFalse(ok)
        self.assertFalse(rows[0]["regenerable"])

    def test_legacy_is_never_rebuildable_even_when_present(self):
        # `regenerable` means "satisfiable right now" (the blob is there);
        # `rebuildable` means "could be regenerated if the blob were lost". A
        # legacy entry has no recipe, so it is never the latter -- conflating the
        # two made a closure of purely legacy entries report SUCCESS.
        legacy_entry = {"schemaVersion": 2, "action": {
            "kind": "legacy", "package": "bz2", "version": "1.0.8", "revision": "1",
            "architecture": ARCH, "actionHash": "chash-bz2"},
            "result": {"outputDigest": "sha256:chash-bz2", "size": 1}}
        present = FakeSync(entries={}, blobs_present={"chash-bz2"},
                           recipe_blobs={}, label_to_hash={})
        rows, _ = verify_closure(present, [legacy_entry])
        self.assertTrue(rows[0]["regenerable"])
        self.assertFalse(rows[0]["rebuildable"])

    def test_healthy_closure_is_rebuildable(self):
        s = self._verify_sync(present={"czlib", "cgcc", "cdef"})
        rows, ok = verify_closure(s, walk_build_closure(s, "hash-zlib"))
        self.assertTrue(ok)
        self.assertTrue(all(r["rebuildable"] for r in rows))

    def test_verify_all_present_reuses_everything(self):
        s = self._verify_sync(present={"czlib", "cgcc", "cdef"})
        rows, ok = verify_closure(s, walk_build_closure(s, "hash-zlib"))
        self.assertTrue(ok)
        self.assertTrue(all(r["action"] == "reuse" for r in rows))
        self.assertTrue(all(r["recipe_ok"] for r in rows))

    def test_verify_missing_blob_is_regenerable(self):
        # zlib's tarball is gone; GCC + defaults are present -> only zlib rebuilds,
        # and it's regenerable (recipe intact, deps consistent).
        s = self._verify_sync(present={"cgcc", "cdef"})
        rows, ok = verify_closure(s, walk_build_closure(s, "hash-zlib"))
        self.assertTrue(ok)
        by_pkg = {r["package"]: r for r in rows}
        self.assertEqual(by_pkg["zlib"]["action"], "rebuild")
        self.assertTrue(by_pkg["zlib"]["regenerable"])
        self.assertEqual(by_pkg["GCC"]["action"], "reuse")           # toolchain reused
        self.assertEqual(by_pkg["defaults-release"]["action"], "reuse")

    def test_verify_flags_unregenerable_missing_blob(self):
        # zlib missing AND its recipe blob is corrupt -> not regenerable -> not ok.
        s = self._verify_sync(present={"cgcc", "cdef"}, break_recipe="zlib")
        rows, ok = verify_closure(s, walk_build_closure(s, "hash-zlib"))
        self.assertFalse(ok)
        zlib = next(r for r in rows if r["package"] == "zlib")
        self.assertFalse(zlib["recipe_ok"])
        self.assertFalse(zlib["regenerable"])

    def test_ensure_defaults_recipe(self):
        from alibuild_helpers.reconstruct import ensure_defaults_recipe
        cfg = os.path.join(self.tmp, "cfg")
        os.makedirs(cfg)
        # No defaults name -> nothing to do.
        self.assertTrue(ensure_defaults_recipe(cfg, None))
        # 'release' is already present as a materialised package recipe.
        open(os.path.join(cfg, "defaults-release.sh"), "w").close()
        self.assertTrue(ensure_defaults_recipe(cfg, "release"))
        # 'o2' is missing and there's no alidist to supply it.
        self.assertFalse(ensure_defaults_recipe(cfg, "o2"))
        # ...but an alidist that has defaults-o2.sh gets it copied in.
        ad = os.path.join(self.tmp, "alidist")
        os.makedirs(ad)
        with open(os.path.join(ad, "defaults-o2.sh"), "w") as df:
            df.write("O2 DEFAULTS")
        self.assertTrue(ensure_defaults_recipe(cfg, "o2", ad))
        with open(os.path.join(cfg, "defaults-o2.sh")) as df:
            self.assertEqual(df.read(), "O2 DEFAULTS")
        # An alidist missing the file still reports False.
        self.assertFalse(ensure_defaults_recipe(cfg, "o3", ad))

    def test_supply_recipes_from_alidist(self):
        from alibuild_helpers.reconstruct import supply_recipes_from_alidist
        cfg = os.path.join(self.tmp, "cfg")
        alidist = os.path.join(self.tmp, "alidist")
        os.makedirs(cfg)
        os.makedirs(alidist)
        # Archived recipe already materialised for a built package.
        with open(os.path.join(cfg, "zlib.sh"), "w") as zf:
            zf.write("ARCHIVED")
        # alidist has the built package (should NOT overwrite) plus system/defaults.
        for name, body in (("zlib.sh", "CURRENT"), ("yacc-like.sh", "SYS"),
                           ("defaults-o2.sh", "O2")):
            with open(os.path.join(alidist, name), "w") as af:
                af.write(body)
        copied = supply_recipes_from_alidist(cfg, alidist)
        self.assertEqual(copied, 2)   # yacc-like + defaults-o2, not zlib
        with open(os.path.join(cfg, "zlib.sh")) as zf:
            self.assertEqual(zf.read(), "ARCHIVED")   # archived recipe preserved
        self.assertTrue(os.path.exists(os.path.join(cfg, "yacc-like.sh")))
        self.assertTrue(os.path.exists(os.path.join(cfg, "defaults-o2.sh")))

    def test_rebuilt_tarball_glob(self):
        store = os.path.join(self.tmp, "w", "TARS", ARCH, "store", "ab", "abcd")
        os.makedirs(store)
        tar = os.path.join(store, "zlib-v1-1.%s.tar.gz" % ARCH)
        open(tar, "wb").close()
        wd = os.path.join(self.tmp, "w")
        self.assertEqual(_rebuilt_tarball(wd, ARCH, "zlib"), tar)
        self.assertIsNone(_rebuilt_tarball(wd, ARCH, "other"))

    def test_rebuild_verdict(self):
        self.assertEqual(_rebuild_verdict("a", "a", False), (True, "match"))
        self.assertEqual(_rebuild_verdict("a", "a", True), (True, "match"))
        # Differ is a soft pass by default, a failure under --strict.
        self.assertEqual(_rebuild_verdict("a", "b", False), (True, "differ"))
        self.assertEqual(_rebuild_verdict("a", "b", True), (False, "differ"))

    def _rebuild_args(self, strict=False):
        return Namespace(package="zlib", version="v1", revision="1", architecture=ARCH,
                         remoteStore="reapi://x/cas", acStore="", insecure=False,
                         workDir=self.tmp, outputConfig=None, strict=strict)

    def _fake_builder(self, content):
        """A build_runner that drops `content` where _rebuilt_tarball will find it."""
        def run(cmd):
            d = os.path.join(self.tmp, "verify-rebuild-zlib", "TARS", ARCH,
                             "store", "ab", "abcdef")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "zlib-v1-1.%s.tar.gz" % ARCH), "wb") as tf:
                tf.write(content)
            return 0
        return run

    def test_verify_rebuild_match(self):
        content = b"reproduced-bytes"
        recorded = hashlib.sha256(content).hexdigest()
        closure = [make_entry("zlib", "v1", "1", recorded, "rz")]
        with patch("alibuild_helpers.reconstruct.materialize_recipes"), \
             patch("alibuild_helpers.reconstruct.restore_sources", return_value=([], [])), \
             patch("alibuild_helpers.reconstruct.GitSourceStore"):
            ok = verify_rebuild(self._rebuild_args(), MagicMock(), closure,
                                build_runner=self._fake_builder(content))
        self.assertTrue(ok)   # byte-identical rebuild

    def test_verify_rebuild_differ_soft_and_strict(self):
        recorded = hashlib.sha256(b"original").hexdigest()      # differs from rebuilt
        closure = [make_entry("zlib", "v1", "1", recorded, "rz")]
        builder = self._fake_builder(b"rebuilt-differently")
        with patch("alibuild_helpers.reconstruct.materialize_recipes"), \
             patch("alibuild_helpers.reconstruct.restore_sources", return_value=([], [])), \
             patch("alibuild_helpers.reconstruct.GitSourceStore"):
            self.assertTrue(verify_rebuild(self._rebuild_args(strict=False),
                                           MagicMock(), closure, build_runner=builder))
            self.assertFalse(verify_rebuild(self._rebuild_args(strict=True),
                                            MagicMock(), closure, build_runner=builder))

    def test_verify_rebuild_build_failure(self):
        closure = [make_entry("zlib", "v1", "1", "c" * 64, "rz")]
        with patch("alibuild_helpers.reconstruct.materialize_recipes"), \
             patch("alibuild_helpers.reconstruct.restore_sources", return_value=([], [])), \
             patch("alibuild_helpers.reconstruct.GitSourceStore"):
            ok = verify_rebuild(self._rebuild_args(), MagicMock(), closure,
                                build_runner=lambda cmd: 1)   # build fails
        self.assertFalse(ok)

    def test_verify_rebuild_result_carries_tarball(self):
        content = b"rebuilt-differently"
        recorded = hashlib.sha256(b"original").hexdigest()
        closure = [make_entry("zlib", "v1", "1", recorded, "rz")]
        with patch("alibuild_helpers.reconstruct.materialize_recipes"), \
             patch("alibuild_helpers.reconstruct.restore_sources", return_value=([], [])), \
             patch("alibuild_helpers.reconstruct.GitSourceStore"):
            result = verify_rebuild(self._rebuild_args(), MagicMock(), closure,
                                    build_runner=self._fake_builder(content))
        self.assertTrue(result)                 # soft pass, still truthy
        self.assertEqual(result.kind, "differ")
        self.assertEqual(result.recorded, recorded)
        self.assertEqual(result.rebuilt, hashlib.sha256(content).hexdigest())
        self.assertTrue(os.path.exists(result.tarball))

    def _rebaseline_entry(self):
        return make_entry("zlib", "v1", "1", "a" * 64, "rz")

    def test_do_rebaseline_match_is_noop(self):
        result = RebuildResult(True, kind="match", algo="sha256",
                               recorded="a" * 64, rebuilt="a" * 64, tarball="/x")
        sync_mock = MagicMock()
        ok = do_rebaseline(Namespace(package="zlib", version="v1", apply=True,
                                     delete_old=False), sync_mock,
                           [self._rebaseline_entry()], result)
        self.assertTrue(ok)
        sync_mock.rebaseline_ac_entry.assert_not_called()

    def test_do_rebaseline_dry_run_writes_nothing(self):
        result = RebuildResult(True, kind="differ", algo="sha256",
                               recorded="a" * 64, rebuilt="b" * 64, tarball="/x")
        sync_mock = MagicMock()
        ok = do_rebaseline(Namespace(package="zlib", version="v1", apply=False,
                                     delete_old=False), sync_mock,
                           [self._rebaseline_entry()], result)
        self.assertTrue(ok)   # dry run is not a failure
        sync_mock.rebaseline_ac_entry.assert_not_called()
        sync_mock.delete_artifact_blob.assert_not_called()

    def test_do_rebaseline_apply_rewrites_and_keeps_old(self):
        result = RebuildResult(True, kind="differ", algo="sha256",
                               recorded="a" * 64, rebuilt="b" * 64, tarball="/x")
        sync_mock = MagicMock()
        sync_mock.read_blob.return_value = b"recipe"
        sync_mock.rebaseline_ac_entry.return_value = ("a" * 64, "b" * 64, "cas/old")
        ok = do_rebaseline(Namespace(package="zlib", version="v1", apply=True,
                                     delete_old=False), sync_mock,
                           [self._rebaseline_entry()], result)
        self.assertTrue(ok)
        sync_mock.rebaseline_ac_entry.assert_called_once()
        sync_mock.delete_artifact_blob.assert_not_called()   # old blob kept

    def test_do_rebaseline_apply_delete_old(self):
        result = RebuildResult(True, kind="differ", algo="sha256",
                               recorded="a" * 64, rebuilt="b" * 64, tarball="/x")
        sync_mock = MagicMock()
        sync_mock.read_blob.return_value = b"recipe"
        sync_mock.rebaseline_ac_entry.return_value = ("a" * 64, "b" * 64, "cas/old")
        ok = do_rebaseline(Namespace(package="zlib", version="v1", apply=True,
                                     delete_old=True), sync_mock,
                           [self._rebaseline_entry()], result)
        self.assertTrue(ok)
        sync_mock.delete_artifact_blob.assert_called_once_with("a" * 64, "sha256")

    def test_do_rebaseline_failed_rebuild(self):
        ok = do_rebaseline(Namespace(package="zlib", version="v1", apply=True,
                                     delete_old=False), MagicMock(),
                           [self._rebaseline_entry()], RebuildResult(False))
        self.assertFalse(ok)   # no tarball -> cannot re-baseline

    def _persist_args(self, apply):
        return Namespace(package="zlib", version="v1", apply=apply, storage="permanent")

    def test_do_persist_apply_restores_blob(self):
        result = RebuildResult(True, kind="match", algo="sha256",
                               recorded="a" * 64, rebuilt="a" * 64, tarball="/x")
        sync_mock = MagicMock()
        sync_mock.artifact_blob_exists.return_value = False   # blob is missing
        sync_mock.put_artifact_blob.return_value = "a" * 64   # restores identical hash
        ok = do_persist(self._persist_args(apply=True), sync_mock, [], result)
        self.assertTrue(ok)
        sync_mock.put_artifact_blob.assert_called_once_with("/x", "sha256")

    def test_do_persist_dry_run_writes_nothing(self):
        result = RebuildResult(True, kind="match", algo="sha256",
                               recorded="a" * 64, rebuilt="a" * 64, tarball="/x")
        sync_mock = MagicMock()
        sync_mock.artifact_blob_exists.return_value = False
        ok = do_persist(self._persist_args(apply=False), sync_mock, [], result)
        self.assertTrue(ok)   # dry run is not a failure
        sync_mock.put_artifact_blob.assert_not_called()

    def test_do_persist_already_present_is_noop(self):
        result = RebuildResult(True, kind="match", algo="sha256",
                               recorded="a" * 64, rebuilt="a" * 64, tarball="/x")
        sync_mock = MagicMock()
        sync_mock.artifact_blob_exists.return_value = True    # already there
        ok = do_persist(self._persist_args(apply=True), sync_mock, [], result)
        self.assertTrue(ok)
        sync_mock.put_artifact_blob.assert_not_called()

    def test_do_persist_refuses_differ(self):
        # A rebuild that does not reproduce the recorded hash must not be persisted
        # (that would upload a blob under a key that no AC entry references).
        result = RebuildResult(True, kind="differ", algo="sha256",
                               recorded="a" * 64, rebuilt="b" * 64, tarball="/x")
        sync_mock = MagicMock()
        ok = do_persist(self._persist_args(apply=True), sync_mock, [], result)
        self.assertFalse(ok)
        sync_mock.put_artifact_blob.assert_not_called()

    def test_do_persist_failed_rebuild(self):
        ok = do_persist(self._persist_args(apply=True), MagicMock(), [],
                        RebuildResult(False))
        self.assertFalse(ok)

    def test_doReconstruct_verify_mode(self):
        s = self._verify_sync(present={"czlib", "cgcc", "cdef"})
        args = Namespace(package="zlib", version="v1", revision=None, architecture=ARCH,
                         remoteStore="reapi://localhost/bucket", insecure=False,
                         workDir="/sw", outputConfig=None, verify=True)
        with patch("alibuild_helpers.reconstruct.remote_from_url", return_value=s):
            # Verify mode returns True and materialises nothing.
            self.assertTrue(doReconstruct(args, None))

    def test_doReconstruct_requires_reapi_store(self):
        args = Namespace(package="zlib", version="v1", revision=None, architecture=ARCH,
                         remoteStore="https://s3.cern.ch/foo", insecure=False,
                         workDir="/sw", outputConfig=None)
        self.assertRaises(SystemExit, doReconstruct, args, None)


if __name__ == "__main__":
    unittest.main()
