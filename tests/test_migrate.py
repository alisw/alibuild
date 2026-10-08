import hashlib
import io
import json
import os
import os.path
import shutil
import subprocess
import tarfile
import tempfile
import threading
import unittest
from argparse import Namespace
from unittest.mock import patch, MagicMock

from alibuild_helpers.migrate import strip_rw

from alibuild_helpers import sync
from alibuild_helpers import sync_reapi

from alibuild_helpers.migrate import (
    read_meta_json, recover_recipe, container_for_migration,
    ac_entry_from_meta, migrate_tarball, doMigrate, verify_recovered_recipe,
    download_from_old_store, enumerate_closure, enumerate_arch, enrich_source_snapshot)


class _FakeResp:
    """Minimal streaming requests.Response stand-in."""
    def __init__(self, data=b"", text=""):
        self._data = data
        self.text = text
        self.status_code = 200
        self.headers = {"content-length": str(len(data))}
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False
    def raise_for_status(self):
        pass
    def iter_content(self, chunk_size):
        yield self._data

ARCH = "slc7_x86-64"

META = {
    "alibuild_version": "1.0",
    "alidist": {"commit": None},   # filled in per-test
    "architecture": ARCH,
    "defaults": "o2",
    "package": {"name": "zlib", "tag": "v1.3.1", "source": "https://example/zlib",
                "version": "v1.3.1", "revision": "1", "hash": "z" * 40},
    "dependencies": {
        "direct": {"build": [], "runtime": []},
        "recursive": {
            "build": [{"name": "GCC", "tag": "v9", "source": "https://e/gcc",
                       "version": "v9", "revision": "2", "hash": "g" * 40}],
            "runtime": [{"name": "GCC", "tag": "v9", "source": "https://e/gcc",
                         "version": "v9", "revision": "2", "hash": "g" * 40}],
        },
    },
}


def make_tarball_with_meta(meta):
    """A legacy tarball laid out as <arch>/<pkg>/<ver>-<rev>/.meta.json + a file."""
    pkgpath = "%s/zlib/v1.3.1-1" % ARCH
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in ((pkgpath + "/.meta.json", json.dumps(meta).encode()),
                           (pkgpath + "/lib/libz.so", b"binary")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class FakeReapiSync:
    def __init__(self):
        self.calls = []
        self.blobs = {}
        self.objects = {}

    def migrate_put(self, ac_entry, tarball_path, recipe_text):
        self.calls.append((ac_entry, tarball_path, recipe_text))
        return "c" * 64

    # Enough of the CAS/source-store interface for GitSourceStore + store_refs.
    def put_file_as_blob(self, path, algo="sha256"):
        with open(path, "rb") as blobf:
            data = blobf.read()
        h = hashlib.sha256(data).hexdigest()
        self.blobs.setdefault(h, data)
        return h

    def put_bytes_as_blob(self, data, algo="sha256"):
        h = hashlib.sha256(data).hexdigest()
        self.blobs.setdefault(h, data)
        return h

    def read_blob(self, content_hash, algo="sha256"):
        return self.blobs[content_hash]

    def read_object_json(self, key):
        return self.objects.get(key)

    def write_object_json(self, key, obj):
        self.objects[key] = obj


class _EnrichSync:
    """Minimal ledger stand-in for enrich_source_snapshot: one AC entry keyed by
    a fixed action hash, plus a record of any in-place updates."""
    def __init__(self, entry, action_hash="a" * 40):
        self._entry = entry
        self._hash = action_hash
        self.updated = []

    def resolve_action_hash(self, package, version, revision=None):
        return self._hash

    def read_ac_entry(self, action_hash):
        return self._entry if action_hash == self._hash else None

    def update_ac_entry(self, entry):
        self.updated.append(entry)


def _ac_entry(source="https://example.invalid/zlib.git", tag="v1.3.1",
              source_artifact=None):
    return {"schemaVersion": 2, "action": {
        "package": "zlib", "version": "v1.3.1", "revision": "6",
        "architecture": ARCH, "actionHash": "a" * 40,
        "source": source, "tag": tag, "sourceArtifact": source_artifact,
        "refsArtifact": None,
        "commit": {"ref": tag, "commitHash": tag, "altRefs": {}}}}


class MigrateTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write_tarball(self, meta):
        path = os.path.join(self.tmp, "zlib-v1.3.1-1.%s.tar.gz" % ARCH)
        with open(path, "wb") as tarf:
            tarf.write(make_tarball_with_meta(meta))
        return path

    def _make_alidist(self):
        """A git alidist with a zlib.sh recipe; returns (dir, commit)."""
        alidist = os.path.join(self.tmp, "alidist")
        os.makedirs(alidist)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="a@b.c",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="a@b.c")
        run = lambda *a: subprocess.run(["git"] + list(a), cwd=alidist, env=env,
                                        check=True, stdout=subprocess.PIPE).stdout.decode().strip()
        run("init", "-q")
        with open(os.path.join(alidist, "zlib.sh"), "w") as recipef:
            recipef.write("package: zlib\nversion: v1.3.1\n---\nbuild zlib\n")
        run("add", ".")
        run("commit", "-qm", "recipes")
        return alidist, run("rev-parse", "HEAD")

    def test_read_meta_json(self):
        path = self._write_tarball(META)
        meta = read_meta_json(path)
        self.assertEqual(meta["package"]["name"], "zlib")
        self.assertEqual(meta["defaults"], "o2")

    def test_read_meta_json_absent(self):
        path = os.path.join(self.tmp, "nometa.tar.gz")
        with tarfile.open(path, "w:gz") as tar:
            data = b"x"
            info = tarfile.TarInfo("%s/zlib/v1.3.1-1/lib/libz.so" % ARCH)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        self.assertIsNone(read_meta_json(path))

    def test_recover_recipe(self):
        alidist, commit = self._make_alidist()
        recipe = recover_recipe(alidist, commit, "zlib")
        self.assertIn("build zlib", recipe)
        self.assertIn("package: zlib", recipe)

    def test_recover_recipe_github_fallback(self):
        alidist, _ = self._make_alidist()
        bogus = "0" * 40   # not in the local clone -> git show fails -> GitHub
        with patch("alibuild_helpers.migrate.requests.get",
                   return_value=_FakeResp(text="package: zlib\n---\nfrom github\n")) as get:
            recipe = recover_recipe(alidist, bogus, "zlib")
        self.assertIn("from github", recipe)
        url = get.call_args.args[0]
        self.assertIn("raw.githubusercontent.com", url)
        self.assertTrue(url.endswith(bogus + "/zlib.sh"))

    def test_container_for_migration(self):
        default = container_for_migration(ARCH)
        self.assertEqual(default["image"], "registry.cern.ch/alisw/slc7-builder")
        self.assertEqual(default["provenance"], "migration-default")
        override = container_for_migration(ARCH, "myreg/img:tag")
        self.assertEqual(override["image"], "myreg/img:tag")

    def test_ac_entry_from_meta(self):
        entry = ac_entry_from_meta(META, "package: zlib\n---\nbuild\n",
                                   container_for_migration(ARCH))
        action = entry["action"]
        self.assertEqual(entry["schemaVersion"], 2)
        self.assertEqual(action["actionHash"], "z" * 40)
        self.assertEqual(action["source"], "https://example/zlib")
        self.assertEqual(action["deps"], [{"package": "GCC", "actionHash": "g" * 40}])
        self.assertEqual(action["runtimeDeps"], [{"package": "GCC", "actionHash": "g" * 40}])
        self.assertEqual(action["container"]["provenance"], "migration-default")
        self.assertEqual(action["recipeDigest"], "sha256:" +
                         hashlib.sha256(b"package: zlib\n---\nbuild\n").hexdigest())

    def test_migrate_tarball(self):
        alidist, commit = self._make_alidist()
        meta = json.loads(json.dumps(META))
        meta["alidist"]["commit"] = commit
        path = self._write_tarball(meta)
        sync = FakeReapiSync()
        action_hash = migrate_tarball(sync, path, alidist)
        self.assertEqual(action_hash, "z" * 40)
        self.assertEqual(len(sync.calls), 1)
        entry, tarball_path, recipe = sync.calls[0]
        self.assertEqual(tarball_path, path)
        self.assertIn("build zlib", recipe)               # recovered from alidist
        self.assertEqual(entry["action"]["package"], "zlib")

    def test_migrate_tarball_skips_without_meta(self):
        alidist, _ = self._make_alidist()
        path = os.path.join(self.tmp, "nometa.tar.gz")
        with tarfile.open(path, "w:gz") as tar:
            info = tarfile.TarInfo("%s/zlib/v1.3.1-1/x" % ARCH)
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
        sync = FakeReapiSync()
        self.assertIsNone(migrate_tarball(sync, path, alidist))
        self.assertEqual(sync.calls, [])

    def test_enrich_source_snapshot_adds_source(self):
        s = _EnrichSync(_ac_entry())
        art = {"type": "git", "commit": "deadbeef", "baseDigest": None,
               "deltaDigest": "d" * 64}
        refs = {"type": "git-refs", "digest": "r" * 64}
        with patch("alibuild_helpers.migrate.snapshot_legacy_source",
                   return_value=(art, refs, "deadbeef")) as snap:
            result = enrich_source_snapshot(s, "zlib", "v1.3.1", "6", "/tmp/mirror")
        self.assertEqual(result, "migrated")
        # It clones/snapshots using the source+tag recorded in the AC entry,
        # never the tarball.
        _, meta_arg, mirror_arg = snap.call_args[0]
        self.assertEqual(meta_arg["package"]["source"],
                         "https://example.invalid/zlib.git")
        self.assertEqual(meta_arg["package"]["tag"], "v1.3.1")
        self.assertEqual(mirror_arg, "/tmp/mirror")
        # The AC entry is rewritten in place with the snapshot + resolved commit.
        self.assertEqual(len(s.updated), 1)
        action = s.updated[0]["action"]
        self.assertEqual(action["sourceArtifact"], art)
        self.assertEqual(action["refsArtifact"], refs)
        self.assertEqual(action["commit"]["commitHash"], "deadbeef")

    def test_enrich_source_snapshot_idempotent(self):
        # An entry that already has a snapshot is left untouched.
        s = _EnrichSync(_ac_entry(source_artifact={"type": "git", "commit": "x"}))
        with patch("alibuild_helpers.migrate.snapshot_legacy_source") as snap:
            result = enrich_source_snapshot(s, "zlib", "v1.3.1", "6", "/tmp/mirror")
        self.assertEqual(result, "present")
        snap.assert_not_called()
        self.assertEqual(s.updated, [])

    def test_enrich_source_snapshot_no_upstream_source(self):
        # Packages without an upstream source (e.g. defaults-release) are a no-op.
        s = _EnrichSync(_ac_entry(source=None))
        with patch("alibuild_helpers.migrate.snapshot_legacy_source") as snap:
            result = enrich_source_snapshot(s, "defaults-release", "v1", "1",
                                            "/tmp/mirror")
        self.assertEqual(result, "present")
        snap.assert_not_called()
        self.assertEqual(s.updated, [])

    def test_enrich_source_snapshot_upstream_gone(self):
        # If the upstream clone/snapshot fails, nothing is rewritten.
        s = _EnrichSync(_ac_entry())
        with patch("alibuild_helpers.migrate.snapshot_legacy_source",
                   return_value=(None, None, None)):
            result = enrich_source_snapshot(s, "zlib", "v1.3.1", "6", "/tmp/mirror")
        self.assertEqual(result, "skipped")
        self.assertEqual(s.updated, [])

    def test_enrich_source_snapshot_unresolved_hash(self):
        class _NoHash(_EnrichSync):
            def resolve_action_hash(self, *a, **k):
                return None
        s = _NoHash(_ac_entry())
        result = enrich_source_snapshot(s, "zlib", "v1.3.1", "6", "/tmp/mirror")
        self.assertEqual(result, "skipped")
        self.assertEqual(s.updated, [])

    def test_doEnrichSources_walks_ledger(self):
        # `migrate --snapshot-sources` with no TARBALL enriches every AC entry
        # from the ledger: sourced ones get snapshotted, source-less/already-done
        # ones are left alone -- no old store involved.
        from alibuild_helpers.migrate import doEnrichSources
        entries = {
            "h-zlib": _ac_entry(),                                   # has source, no snapshot
            "h-def": _ac_entry(source=None),                         # source-less
            "h-done": _ac_entry(source_artifact={"type": "git"}),    # already snapshotted
        }
        for h, e in entries.items():
            e["action"]["actionHash"] = h

        class _LedgerSync(sync_reapi.REAPIRemoteSync):
            def __init__(self): self.updated = []
            def iter_ac_entry_hashes(self, arch): return list(entries)
            def read_ac_entry(self, h): return entries[h]
            def update_ac_entry(self, e): self.updated.append(e["action"]["actionHash"])

        ledger = _LedgerSync()
        args = Namespace(remoteStore="reapi://localhost/cas", acStore="", architecture=ARCH,
                         workDir=self.tmp, insecure=False, storage="permanent",
                         source_mirror=os.path.join(self.tmp, "mir"), dryRun=False, jobs=1)
        with patch("alibuild_helpers.migrate.remote_from_url", return_value=ledger), \
             patch("alibuild_helpers.migrate.snapshot_legacy_source",
                   return_value=({"type": "git", "commit": "c"}, {"digest": "r"}, "c")) as snap:
            ok = doEnrichSources(args)
        # Only the sourced, un-snapshotted entry is cloned + rewritten.
        self.assertEqual(snap.call_count, 1)
        self.assertEqual(ledger.updated, ["h-zlib"])
        self.assertTrue(ok)

    @unittest.skipUnless(shutil.which("git"), "git required")
    def test_snapshot_falls_back_when_rc_branch_deleted(self):
        from alibuild_helpers.migrate import snapshot_legacy_source
        from alibuild_helpers.source import load_refs
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="a@b.c",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="a@b.c")

        def g(*a):
            return subprocess.run(["git", "-C", up, *a], env=env, check=True,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT).stdout.decode().strip()

        up = os.path.join(self.tmp, "upstream")
        os.makedirs(up)
        g("init", "-q")
        with open(os.path.join(up, "f.txt"), "w") as ff:
            ff.write("src")
        g("add", "-A")
        g("commit", "-qm", "daily")
        commit = g("rev-parse", "HEAD")
        # Built on rc/<tag>, with the real <tag> tag also created; then the rc
        # branch is deleted upstream (the failure this fallback handles).
        g("branch", "rc/daily-20260630-0000")
        g("tag", "daily-20260630-0000")
        g("branch", "-D", "rc/daily-20260630-0000")

        sync = FakeReapiSync()
        meta = {"architecture": ARCH,
                "package": {"name": "o2physics", "source": up,
                            "tag": "rc/daily-20260630-0000"}}
        art, refs, got = snapshot_legacy_source(
            sync, meta, os.path.join(self.tmp, "mirror"))
        # Resolved to the same commit via the surviving tag, and snapshotted.
        self.assertEqual(got, commit)
        self.assertIsNotNone(art)
        # The recipe's rc/ tag is pinned in the refs so offline checkout resolves
        # it at reconstruct time even though upstream deleted the branch.
        self.assertEqual(load_refs(sync, refs)["refs/tags/rc/daily-20260630-0000"],
                         commit)

    def test_ref_candidates_strips_rc_prefix(self):
        from alibuild_helpers.migrate import _ref_candidates
        self.assertEqual(_ref_candidates("rc/daily-20260630-0000"),
                         ["rc/daily-20260630-0000", "daily-20260630-0000"])
        self.assertEqual(_ref_candidates("v1.2.3"), ["v1.2.3"])

    def test_verify_recovered_recipe(self):
        recipe = "package: zlib\nversion: v1.3.1\n---\nbuild\n"
        ok, _ = verify_recovered_recipe(META, recipe)
        self.assertTrue(ok)
        # Wrong package field is caught.
        ok, reason = verify_recovered_recipe(META, "package: other\n---\nbuild\n")
        self.assertFalse(ok)
        self.assertIn("expected", reason)
        # A dependency without a recorded hash is caught.
        bad_meta = json.loads(json.dumps(META))
        bad_meta["dependencies"]["recursive"]["build"][0]["hash"] = ""
        ok, reason = verify_recovered_recipe(bad_meta, recipe)
        self.assertFalse(ok)
        self.assertIn("no recorded hash", reason)

    def test_migrate_tarball_skips_on_failed_verify(self):
        alidist, commit = self._make_alidist()   # provides recipe with package: zlib
        meta = json.loads(json.dumps(META))
        meta["alidist"]["commit"] = commit
        meta["package"]["name"] = "notzlib"       # mismatch -> recover gets zlib.sh? no
        # Point the package name at something whose recipe (zlib.sh) won't match.
        meta["package"]["name"] = "zlib"
        # Force a mismatch by tampering the recovered recipe's expectation:
        meta["dependencies"]["recursive"]["build"][0]["hash"] = ""
        path = self._write_tarball(meta)
        sync = FakeReapiSync()
        self.assertIsNone(migrate_tarball(sync, path, alidist))   # verify fails -> skip
        self.assertEqual(sync.calls, [])
        # With verification disabled, it is migrated.
        self.assertIsNotNone(migrate_tarball(sync, path, alidist, verify=False))

    def _make_source_repo(self, tag):
        """A git 'upstream' repo with a tagged commit; returns (path, sha)."""
        repo = os.path.join(self.tmp, "upstream")
        os.makedirs(repo)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="a@b.c",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="a@b.c")
        run = lambda *a: subprocess.run(["git"] + list(a), cwd=repo, env=env,
                                        check=True, stdout=subprocess.PIPE).stdout.decode().strip()
        run("init", "-q")
        with open(os.path.join(repo, "src.c"), "w") as srcf:
            srcf.write("int main(){}\n")
        run("add", ".")
        run("commit", "-qm", "code")
        run("tag", tag)
        return repo, run("rev-parse", "HEAD")

    def test_migrate_snapshots_source(self):
        alidist, commit = self._make_alidist()
        upstream, sha = self._make_source_repo("v1.3.1")
        meta = json.loads(json.dumps(META))
        meta["alidist"]["commit"] = commit
        meta["package"]["source"] = upstream      # local repo stands in for upstream
        path = self._write_tarball(meta)
        sync = FakeReapiSync()
        mirror = os.path.join(self.tmp, "mirror")
        migrate_tarball(sync, path, alidist, snapshot_sources=True, mirror_dir=mirror)

        entry = sync.calls[0][0]["action"]
        # Source + refs were archived, and the commit was resolved to a real SHA
        # (so the source-aware checkout's SOURCES path matches at rebuild).
        self.assertIsNotNone(entry["sourceArtifact"])
        self.assertIsNotNone(entry["refsArtifact"])
        self.assertEqual(entry["commit"]["commitHash"], sha)
        self.assertEqual(entry["commit"]["ref"], sha)

    def test_download_from_old_store(self):
        urls = []
        pointer = "%s/store/92/abc/ROOT-v6-28-04-1.%s.tar.gz" % (ARCH, ARCH)
        link_url = "https://store/repo/TARS/%s/ROOT/ROOT-v6-28-04-1.%s.tar.gz" % (ARCH, ARCH)

        def fake_get(url, **kwargs):
            urls.append(url)
            # First GET resolves the symlink pointer; second fetches the bytes.
            return _FakeResp(text=pointer) if url == link_url else _FakeResp(b"TARBALL-BYTES")

        with patch("alibuild_helpers.migrate.requests.get", side_effect=fake_get):
            dest = download_from_old_store("https://store/repo/", ARCH,
                                           "ROOT/v6-28-04-1", self.tmp)
        # Two-step: GET the symlink, then the resolved content-addressed object.
        self.assertEqual(urls[0], link_url)
        self.assertEqual(urls[1], "https://store/repo/TARS/" + pointer)
        with open(dest, "rb") as got:
            self.assertEqual(got.read(), b"TARBALL-BYTES")

    def test_enumerate_closure(self):
        # dist tree lists the closure; TARS/<arch>/ lists package dirs.
        dist_prefix = "TARS/%s/dist/O2/O2-daily-1/" % ARCH
        pkg_prefix = "TARS/%s/" % ARCH

        def fake_list(read_url, prefix):
            if prefix == dist_prefix:
                return [dist_prefix + n for n in (
                    "O2-daily-1.%s.tar.gz" % ARCH,
                    "GCC-Toolchain-v14-1.%s.tar.gz" % ARCH,
                    "ninja-fortran-v1.11.1.g9-25.%s.tar.gz" % ARCH,
                    "zlib-v1.3.1-6.%s.tar.gz" % ARCH)]
            if prefix == pkg_prefix:
                # Both GCC/GCC-Toolchain and ninja/ninja-fortran are packages that
                # prefix-match a filename -> disambiguated by which symlink exists.
                return [pkg_prefix + n + "/" for n in
                        ("O2", "GCC", "GCC-Toolchain", "ninja", "ninja-fortran", "zlib")]
            return []

        # The *correct* per-package symlink exists; the wrong-prefix one 404s.
        exists = {"GCC-Toolchain/GCC-Toolchain-v14-1",
                  "ninja/ninja-fortran-v1.11.1.g9-25"}

        def fake_head(url, timeout=None):
            parts = url.rstrip("/").split("/")
            base = parts[-1][:-len(".%s.tar.gz" % ARCH)]
            resp = MagicMock()
            resp.status_code = 200 if "%s/%s" % (parts[-2], base) in exists else 404
            return resp

        with patch("alibuild_helpers.migrate._list_old_store", side_effect=fake_list), \
             patch("alibuild_helpers.migrate.requests.head", side_effect=fake_head):
            specs = enumerate_closure("https://store", ARCH, "O2/daily-1")
        self.assertEqual(set(specs),
                         {"O2/daily-1", "GCC-Toolchain/v14-1",
                          "ninja/fortran-v1.11.1.g9-25", "zlib/v1.3.1-6"})

    def test_populate_system_deps(self):
        from alibuild_helpers.migrate import populate_system_deps
        probe_recipe = "package: probe\nversion: '1'\nrequires:\n  - make\n---\nbuild\n"
        probe_digest = hashlib.sha256(probe_recipe.encode()).hexdigest()
        make_recipe = ("package: make\nversion: '4'\nsystem_requirement: '.*'\n"
                       "system_requirement_check: |\n  type make\n---\n")
        make_digest = hashlib.sha256(make_recipe.encode()).hexdigest()
        probe_entry = {"schemaVersion": 2, "action": {
            "package": "probe", "version": "1", "revision": "1", "architecture": ARCH,
            "actionHash": "hp", "recipeDigest": "sha256:" + probe_digest, "deps": []}}
        put_entries, updated = {}, {}

        class FakeSync:
            def iter_ac_entry_hashes(self, architecture): return ["hp"]
            def read_ac_entry(self, h): return probe_entry if h == "hp" else None
            def read_blob(self, digest, algo="sha256"):
                return probe_recipe.encode() if digest == probe_digest else b""
            def put_ac_entry(self, entry, recipe_text=""):
                put_entries[entry["action"]["actionHash"]] = entry
            def update_ac_entry(self, entry):
                updated[entry["action"]["package"]] = entry

        with patch("alibuild_helpers.migrate.recover_recipe",
                   side_effect=lambda d, c, pkg: make_recipe if pkg == "make" else None):
            enriched, added = populate_system_deps(FakeSync(), ARCH, "/alidist", "HEAD")
        self.assertEqual((enriched, added), (1, 1))
        # make got a validate-system entry keyed by its recipe digest,
        self.assertEqual(put_entries[make_digest]["action"]["kind"], "validate-system")
        # and probe's deps now reference it by the same digest.
        self.assertEqual(updated["probe"]["action"]["deps"],
                         [{"package": "make", "actionHash": make_digest}])

    def test_recover_legacy_deps(self):
        from alibuild_helpers.migrate import recover_legacy_deps
        suffix = ".%s.tar.gz" % ARCH
        pkg_prefix = "TARS/%s/" % ARCH
        hashes = {"zlib/v1.2.8-1": "hz", "GCC-Toolchain/v14-1": "hg"}

        def fake_list(read_url, prefix):
            if prefix == pkg_prefix:
                return [pkg_prefix + n + "/" for n in
                        ["zlib", "GCC-Toolchain", "dist", "dist-direct", "dist-runtime", "store"]]
            if prefix == "TARS/%s/dist-direct/zlib/zlib-v1.2.8-1/" % ARCH:
                # includes self plus the one direct dep
                return ["x/GCC-Toolchain-v14-1" + suffix, "x/zlib-v1.2.8-1" + suffix]
            if prefix == "TARS/%s/dist-runtime/zlib/zlib-v1.2.8-1/" % ARCH:
                return ["x/GCC-Toolchain-v14-1" + suffix]
            return []   # GCC-Toolchain has no dist-direct/runtime folder

        updated = {}

        class FakeSync:
            def resolve_action_hash(self, pkg, version, revision=None):
                return hashes.get("%s/%s-%s" % (pkg, version, revision))

            def read_ac_entry(self, h):
                pkg = {"hz": "zlib", "hg": "GCC-Toolchain"}.get(h)
                return None if pkg is None else {
                    "schemaVersion": 2,
                    "action": {"kind": "legacy", "package": pkg, "actionHash": h}}

            def update_ac_entry(self, entry):
                updated[entry["action"]["package"]] = entry

        with patch("alibuild_helpers.migrate._list_old_store", side_effect=fake_list), \
             patch("alibuild_helpers.migrate.requests.head",
                   side_effect=lambda url, timeout=None: MagicMock(status_code=200)):
            n = recover_legacy_deps("https://store", ARCH,
                                    ["zlib/v1.2.8-1", "GCC-Toolchain/v14-1"], FakeSync())
        self.assertEqual(n, 2)
        # zlib's direct dep GCC is hash-linked; self is excluded.
        self.assertEqual(updated["zlib"]["action"]["deps"],
                         [{"package": "GCC-Toolchain", "actionHash": "hg"}])
        self.assertEqual(updated["zlib"]["action"]["runtimeDeps"],
                         [{"package": "GCC-Toolchain", "actionHash": "hg"}])
        # GCC has no dist folder -> empty (leaf) deps.
        self.assertEqual(updated["GCC-Toolchain"]["action"]["deps"], [])

    def test_enumerate_arch(self):
        pkg_prefix = "TARS/%s/" % ARCH
        suffix = ".%s.tar.gz" % ARCH
        per_pkg = {"zlib": ["zlib-v1.3.1-6", "zlib-v1.2.11-1"],
                   "RapidJSON": ["RapidJSON-v1.1.0-3"],
                   "ninja-fortran": ["ninja-fortran-v1.11.1.g9-25"]}

        def fake_list(read_url, prefix):
            if prefix == pkg_prefix:
                # real package dirs plus publisher/store subtrees that must be excluded
                return [pkg_prefix + n + "/" for n in
                        list(per_pkg) + ["dist", "dist-direct", "dist-runtime", "store"]]
            for pkg, builds in per_pkg.items():
                if prefix == "%s%s/" % (pkg_prefix, pkg):
                    return ["%s%s/%s%s" % (pkg_prefix, pkg, b, suffix) for b in builds] + \
                           ["%s%s/latest" % (pkg_prefix, pkg)]   # non-tarball -> skipped
            return []

        with patch("alibuild_helpers.migrate._list_old_store", side_effect=fake_list), \
             patch("alibuild_helpers.migrate.requests.head",
                   side_effect=lambda url, timeout=None: MagicMock(status_code=200)):
            allspecs = enumerate_arch("https://store", ARCH)
            only_rj = enumerate_arch("https://store", ARCH, r"^RapidJSON/")
        self.assertEqual(set(allspecs),
                         {"zlib/v1.3.1-6", "zlib/v1.2.11-1",
                          "RapidJSON/v1.1.0-3", "ninja-fortran/v1.11.1.g9-25"})
        self.assertEqual(set(only_rj), {"RapidJSON/v1.1.0-3"})   # regex filters; dist/store excluded

    def test_enumerate_closure_no_dist_tolerant(self):
        # A dependency-only package (no dist/ tree): strict raises, non-strict
        # (--match-driven) falls back to migrating the package alone.
        with patch("alibuild_helpers.migrate._list_old_store", return_value=[]):
            self.assertEqual(
                enumerate_closure("https://store", ARCH, "ninja/fortran-v1.8.2.g3b-1",
                                  strict=False),
                ["ninja/fortran-v1.8.2.g3b-1"])
            with self.assertRaises(SystemExit):
                enumerate_closure("https://store", ARCH, "ninja/fortran-v1.8.2.g3b-1")

    def test_migrate_tarball_dry_run(self):
        alidist, commit = self._make_alidist()
        meta = json.loads(json.dumps(META))
        meta["alidist"]["commit"] = commit
        path = self._write_tarball(meta)
        sync = FakeReapiSync()
        action_hash = migrate_tarball(sync, path, alidist, dry_run=True)
        self.assertEqual(action_hash, META["package"]["hash"])
        self.assertEqual(sync.calls, [])   # dry-run writes nothing

    def test_doMigrate_parallel_processes_all(self):
        args = Namespace(
            tarballs=["a.tgz", "b.tgz", "c.tgz", "d.tgz", "e.tgz"],
            remoteStore="reapi://localhost/cas", acStore="", architecture=ARCH,
            workDir="/sw", insecure=False, alidist="/alidist", container=None,
            no_verify=False, snapshot_sources=False, source_mirror=None,
            read_store=None, closure=False, storage="ephemeral", jobs=4)

        processed, lock = [], threading.Lock()

        def fake_migrate(sync_, tarball, *a, **kw):
            with lock:
                processed.append(tarball)
            return True

        fake_sync = MagicMock(spec=sync_reapi.REAPIRemoteSync)
        with patch("alibuild_helpers.migrate.remote_from_url", return_value=fake_sync), \
             patch("alibuild_helpers.migrate.migrate_tarball", side_effect=fake_migrate):
            ok = doMigrate(args, None)
        self.assertTrue(ok)
        # Every package was processed exactly once across the 4 worker threads.
        self.assertEqual(sorted(processed), ["a.tgz", "b.tgz", "c.tgz", "d.tgz", "e.tgz"])

    def test_download_resumes_after_interruption(self):
        from requests.exceptions import ChunkedEncodingError
        from alibuild_helpers.migrate import _download_with_resume
        full = b"0123456789" * 10        # 100 bytes
        ranges = []

        def fake_get(url, stream=False, headers=None, timeout=None):
            ranges.append((headers or {}).get("Range"))
            first = len(ranges) == 1
            resp = MagicMock()
            resp.__enter__ = lambda s: s
            resp.__exit__ = lambda s, *a: False
            resp.raise_for_status = lambda: None
            if first:
                resp.status_code = 200
                resp.headers = {"content-length": str(len(full))}
                def it(_n):
                    yield full[:40]
                    raise ChunkedEncodingError("connection dropped")
                resp.iter_content = it
            else:
                start = int(ranges[-1].split("=")[1].rstrip("-"))
                resp.status_code = 206
                resp.headers = {"content-length": str(len(full) - start)}
                resp.iter_content = lambda _n: iter([full[start:]])
            return resp

        dest = os.path.join(self.tmp, "resume.bin")
        with patch("alibuild_helpers.migrate.requests.get", side_effect=fake_get), \
             patch("alibuild_helpers.migrate.time.sleep"):
            _download_with_resume("http://x/obj", dest, retries=3)

        with open(dest, "rb") as got:
            self.assertEqual(got.read(), full)       # fully reassembled
        self.assertIsNone(ranges[0])                 # first attempt: no Range
        self.assertEqual(ranges[1], "bytes=40-")     # resumed from the 40 bytes on disk

    def test_byte_progress(self):
        from alibuild_helpers import log
        with patch.object(log, "debug") as dbg:
            prog = log.byte_progress("upload x", total=1000 << 20,
                                     every_bytes=200 << 20, every_seconds=10 ** 9)
            for _ in range(4):
                prog(100 << 20)   # 100 MB each -> crosses 200 MB twice (at 200, 400)
        self.assertEqual(dbg.call_count, 2)

    def test_doMigrate_requires_reapi_store(self):
        args = Namespace(remoteStore="https://s3.cern.ch/foo", architecture=ARCH,
                         workDir="/sw", insecure=False, tarballs=["x.tar.gz"],
                         alidist="/alidist", container=None)
        self.assertRaises(SystemExit, doMigrate, args, None)


class StripRwTestCase(unittest.TestCase):
    """`migrate` must accept the same store URL `build` does.

    finaliseArgs() normalises the ::rw suffix only for build and doctor, so every
    other subcommand saw it verbatim and handed boto3 a bucket literally named
    "alibuild-cas::rw", which fails parameter validation before any request goes
    out. Copying a working --remote-store from a build invocation into a migrate
    one is the obvious thing to do, so it has to work.
    """

    def test_suffix_is_dropped(self):
        self.assertEqual(strip_rw("reapi://h/alibuild-cas::rw"), "reapi://h/alibuild-cas")

    def test_url_without_the_suffix_is_untouched(self):
        self.assertEqual(strip_rw("reapi://h/alibuild-cas"), "reapi://h/alibuild-cas")

    def test_trailing_whitespace_does_not_hide_the_suffix(self):
        self.assertEqual(strip_rw("reapi://h/alibuild-cas::rw  "), "reapi://h/alibuild-cas")

    def test_empty_and_none_become_empty(self):
        for value in ("", None):
            self.assertEqual(strip_rw(value), "")

    def test_rw_elsewhere_in_the_url_is_kept(self):
        """Only a SUFFIX is the marker."""
        self.assertEqual(strip_rw("reapi://h/rw-cas"), "reapi://h/rw-cas")

if __name__ == "__main__":
    unittest.main()

