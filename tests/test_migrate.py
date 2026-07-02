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

from alibuild_helpers import sync

from alibuild_helpers.migrate import (
    read_meta_json, recover_recipe, container_for_migration,
    ac_entry_from_meta, migrate_tarball, doMigrate, verify_recovered_recipe,
    download_from_old_store, enumerate_closure)


class _FakeResp:
    """Minimal streaming requests.Response stand-in."""
    def __init__(self, data=b"", text=""):
        self._data = data
        self.text = text
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

        def fake_get(url, stream=False, allow_redirects=False, timeout=None):
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
                    "zlib-v1.3.1-6.%s.tar.gz" % ARCH)]
            if prefix == pkg_prefix:
                # Note GCC and GCC-Toolchain both present -> longest match wins.
                return [pkg_prefix + n + "/" for n in ("O2", "GCC", "GCC-Toolchain", "zlib")]
            return []

        with patch("alibuild_helpers.migrate._list_old_store", side_effect=fake_list):
            specs = enumerate_closure("https://store", ARCH, "O2/daily-1")
        self.assertEqual(set(specs),
                         {"O2/daily-1", "GCC-Toolchain/v14-1", "zlib/v1.3.1-6"})

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

        fake_sync = MagicMock(spec=sync.REAPIRemoteSync)
        with patch("alibuild_helpers.migrate.remote_from_url", return_value=fake_sync), \
             patch("alibuild_helpers.migrate.migrate_tarball", side_effect=fake_migrate):
            ok = doMigrate(args, None)
        self.assertTrue(ok)
        # Every package was processed exactly once across the 4 worker threads.
        self.assertEqual(sorted(processed), ["a.tgz", "b.tgz", "c.tgz", "d.tgz", "e.tgz"])

    def test_doMigrate_requires_reapi_store(self):
        args = Namespace(remoteStore="https://s3.cern.ch/foo", architecture=ARCH,
                         workDir="/sw", insecure=False, tarballs=["x.tar.gz"],
                         alidist="/alidist", container=None)
        self.assertRaises(SystemExit, doMigrate, args, None)


if __name__ == "__main__":
    unittest.main()
