import hashlib
import os
import os.path
import shutil
import subprocess
import tempfile
import unittest

from alibuild_helpers.source import (
    GitSourceStore, _repo_id, _is_ancestor,
    store_refs, load_refs, apply_refs)


class FakeCASSync:
    """In-memory stand-in for REAPIRemoteSync's CAS + pointer operations."""

    def __init__(self):
        self.blobs = {}      # content hash -> bytes
        self.objects = {}    # key -> JSON pointer dict
        self.uploads = 0     # number of blobs actually uploaded

    def put_file_as_blob(self, path, algo="sha256"):
        with open(path, "rb") as blobf:
            data = blobf.read()
        content_hash = hashlib.sha256(data).hexdigest()
        if content_hash not in self.blobs:
            self.blobs[content_hash] = data
            self.uploads += 1
        return content_hash

    def download_blob(self, content_hash, dest, algo="sha256"):
        with open(dest, "wb") as destf:
            destf.write(self.blobs[content_hash])

    def put_bytes_as_blob(self, data, algo="sha256"):
        content_hash = hashlib.sha256(data).hexdigest()
        if content_hash not in self.blobs:
            self.blobs[content_hash] = data
            self.uploads += 1
        return content_hash

    def read_blob(self, content_hash, algo="sha256"):
        return self.blobs[content_hash]

    def read_object_json(self, key):
        return self.objects.get(key)

    def write_object_json(self, key, obj):
        self.objects[key] = obj


def _git(args, cwd):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="a@b.c",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="a@b.c")
    return subprocess.run(["git"] + args, cwd=cwd, env=env, check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout.decode().strip()


@unittest.skipUnless(shutil.which("git"), "git is required for source tests")
class GitSourceStoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, "src")
        os.makedirs(self.repo)
        _git(["init", "-q"], self.repo)
        self._commit("a\n", "c1", tag="v1")
        self.c1 = _git(["rev-parse", "HEAD"], self.repo)
        self._commit("a\nb\n", "c2")
        self.c2 = _git(["rev-parse", "HEAD"], self.repo)
        self._commit("a\nb\nc\n", "c3")
        self.c3 = _git(["rev-parse", "HEAD"], self.repo)
        self.url = "https://example.com/repo"

    def _commit(self, content, msg, tag=None):
        with open(os.path.join(self.repo, "f.txt"), "w") as srcf:
            srcf.write(content)
        _git(["add", "."], self.repo)
        _git(["commit", "-qm", msg], self.repo)
        if tag:
            _git(["tag", tag], self.repo)

    def test_is_ancestor(self):
        self.assertTrue(_is_ancestor(self.repo, self.c1, self.c3))
        self.assertFalse(_is_ancestor(self.repo, self.c3, self.c1))
        self.assertFalse(_is_ancestor(self.repo, None, self.c3))

    def test_backfill_objects_fetches_when_missing(self):
        from unittest.mock import patch
        store = GitSourceStore(FakeCASSync())
        calls = []

        def fake_git(args, directory=None, check=True, **kw):
            calls.append(tuple(args))
            if args[0] == "rev-list":
                return ("", "abc f.txt\n?deadbeefdeadbeefdeadbeefdeadbeefdeadbeef missing\n")
            return ("", "")

        with patch("alibuild_helpers.source.git", side_effect=fake_git):
            store._backfill_objects("/repo", "commitX", None)
        # A missing object -> one bulk --refetch backfill (not per-object lazy fetch).
        self.assertTrue(any("--refetch" in c and "fetch" in c for c in calls))

    def test_backfill_objects_noop_on_full_mirror(self):
        from unittest.mock import patch
        store = GitSourceStore(FakeCASSync())
        calls = []

        def fake_git(args, directory=None, check=True, **kw):
            calls.append(tuple(args))
            return ("", "abc f.txt\ndef g.txt\n")   # no '?' lines -> nothing missing

        with patch("alibuild_helpers.source.git", side_effect=fake_git):
            store._backfill_objects("/repo", "commitX", "baseY")
        self.assertFalse(any("--refetch" in c for c in calls))   # no fetch issued

    def test_snapshot_and_restore_roundtrip(self):
        sync = FakeCASSync()
        store = GitSourceStore(sync)
        entry = store.snapshot(self.repo, self.url, self.c2)
        # First snapshot of the repo: one full base segment, no ancestor base.
        self.assertEqual(entry["baseCommit"], self.c2)
        self.assertEqual(len(entry["segments"]), 1)

        # Wipe the upstream entirely: restore must work from the CAS alone.
        shutil.rmtree(self.repo)
        dest = os.path.join(self.tmp, "restored")
        store.restore(entry, dest)
        self.assertEqual(_git(["rev-parse", "HEAD"], dest), self.c2)
        with open(os.path.join(dest, "f.txt")) as out:
            self.assertEqual(out.read(), "a\nb\n")

    def test_incremental_chain_dedups_shared_history(self):
        """Close commits share one base and store only their per-commit delta,
        instead of duplicating the whole source each time."""
        # A repo with a large incompressible file (lives in the base) plus a tiny
        # file that changes each "daily" commit.
        repo = os.path.join(self.tmp, "bigrepo")
        os.makedirs(repo)
        _git(["init", "-q"], repo)
        with open(os.path.join(repo, "core.bin"), "wb") as bf:
            bf.write(os.urandom(200000))         # incompressible -> stays big in the base
        for rev in ("r0", "r1", "r2"):
            with open(os.path.join(repo, "f.txt"), "w") as ff:
                ff.write(rev)
            _git(["add", "."], repo)
            _git(["commit", "-qm", rev], repo)
        k0 = _git(["rev-parse", "HEAD~2"], repo)
        k1 = _git(["rev-parse", "HEAD~1"], repo)
        k2 = _git(["rev-parse", "HEAD"], repo)
        url = "https://example.com/bigrepo"

        sync = FakeCASSync()
        store = GitSourceStore(sync)
        e0 = store.snapshot(repo, url, k0)   # base (holds core.bin)
        e1 = store.snapshot(repo, url, k1)   # thin against k0
        e2 = store.snapshot(repo, url, k2)   # thin against k1
        # The chain grows by exactly one segment per commit, all sharing the base.
        self.assertEqual(e1["segments"], e0["segments"] + [e1["segments"][-1]])
        self.assertEqual(e2["segments"], e1["segments"] + [e2["segments"][-1]])
        self.assertEqual(e2["baseCommit"], k0)
        # base + 2 deltas = 3 distinct blobs, nothing re-uploaded.
        self.assertEqual(len(sync.blobs), 3)
        self.assertEqual(sync.uploads, 3)
        # The big file is stored once (in the base); the per-daily deltas are tiny.
        base_blob = sync.blobs[e0["segments"][0]]
        self.assertGreater(len(base_blob), 150000)
        for entry in (e1, e2):
            self.assertLess(len(sync.blobs[entry["segments"][-1]]), 2000)

        # Restoring the tip fetches the whole chain and checks out k2 offline.
        shutil.rmtree(repo)
        dest = os.path.join(self.tmp, "restored3")
        store.restore(e2, dest)
        self.assertEqual(_git(["rev-parse", "HEAD"], dest), k2)
        with open(os.path.join(dest, "f.txt")) as out:
            self.assertEqual(out.read(), "r2")

    def test_snapshot_is_idempotent(self):
        sync = FakeCASSync()
        store = GitSourceStore(sync)
        store.snapshot(self.repo, self.url, self.c1)
        store.snapshot(self.repo, self.url, self.c2)
        uploads_before = sync.uploads
        again = store.snapshot(self.repo, self.url, self.c2)   # same commit again
        self.assertEqual(sync.uploads, uploads_before)         # nothing re-uploaded
        self.assertEqual(again["commit"], self.c2)
        self.assertEqual(len(again["segments"]), 2)

    def test_restore_falls_back_to_upstream(self):
        """A broken CAS chain must not be fatal: restore clones upstream instead
        (the snapshot is a backup/speedup, upstream is normally available)."""
        sync = FakeCASSync()
        store = GitSourceStore(sync)
        entry = store.snapshot(self.repo, self.url, self.c2)
        # Corrupt the archive: drop its blobs so the CAS path must fail.
        sync.blobs.clear()
        entry = dict(entry, source=self.repo)   # a reachable "upstream" to clone
        dest = os.path.join(self.tmp, "fallback")
        store.restore(entry, dest)
        self.assertEqual(_git(["rev-parse", "HEAD"], dest), self.c2)

    def test_store_and_load_refs(self):
        sync = FakeCASSync()
        refs = {"refs/tags/v1": "a" * 40, "refs/heads/master": "b" * 40}
        artifact = store_refs(sync, self.url, refs)
        self.assertEqual(artifact["type"], "git-refs")
        self.assertEqual(load_refs(sync, artifact), refs)
        # No refs -> no artifact.
        self.assertIsNone(store_refs(sync, self.url, {}))

    def test_apply_refs_recreates_tags(self):
        # apply_refs recreates the tag refs (only refs/tags/*) in a repo.
        apply_refs(self.repo, {"refs/tags/recovered": self.c3,
                               "refs/heads/ignored": self.c1})
        self.assertEqual(_git(["rev-parse", "refs/tags/recovered"], self.repo), self.c3)
        # Branch refs are not recreated.
        out = subprocess.run(["git", "rev-parse", "--verify", "-q",
                              "refs/heads/ignored"], cwd=self.repo,
                             stdout=subprocess.PIPE).returncode
        self.assertNotEqual(out, 0)

    def test_restore_to_source_dir_path(self):
        sync = FakeCASSync()
        store = GitSourceStore(sync)
        art = store.snapshot(self.repo, self.url, self.c2)
        refs = store_refs(sync, self.url, {"refs/tags/v1": self.c1})
        entry = {"action": {"package": "zlib", "version": "v1.3.1",
                            "commit": {"ref": self.c2}, "tag": "abranch",
                            "sourceArtifact": art, "refsArtifact": refs}}
        work = os.path.join(self.tmp, "wd")
        src = store.restore_to_source_dir(entry, work)
        # tag != commit ref -> short = ref[:10], matching short_commit_hash().
        self.assertEqual(src, os.path.join(work, "SOURCES", "zlib", "v1.3.1",
                                           self.c2[:10]))
        self.assertEqual(_git(["rev-parse", "HEAD"], src), self.c2)

    def test_offline_checkout_from_restored_source(self):
        """The headline 'lost upstream' guarantee: after restoring into SOURCES,
        alibuild's own checkout_sources must check out with an UNREACHABLE
        upstream URL -- proving no upstream contact."""
        from alibuild_helpers.workarea import checkout_sources
        from alibuild_helpers.git import Git
        sync = FakeCASSync()
        store = GitSourceStore(sync)
        art = store.snapshot(self.repo, self.url, self.c1)        # c1 is tagged v1
        refs = store_refs(sync, self.url, {"refs/tags/v1": self.c1})
        entry = {"action": {"package": "zlib", "version": "v1.3.1",
                            "commit": {"ref": self.c1}, "tag": "v1",
                            "sourceArtifact": art, "refsArtifact": refs}}
        work = os.path.join(self.tmp, "wd2")
        store.restore_to_source_dir(entry, work)

        spec = {"scm": Git(), "source": "https://invalid.invalid/zlib.git",
                "commit_hash": self.c1, "tag": "v1", "package": "zlib",
                "version": "v1.3.1", "is_devel_pkg": False}
        reference_sources = os.path.join(self.tmp, "refsrc")
        os.makedirs(reference_sources)
        # Would fail/hang if it tried to reach the bogus URL.
        checkout_sources(spec, work, reference_sources, False)
        sdir = os.path.join(work, "SOURCES", "zlib", "v1.3.1", self.c1[:10])
        self.assertEqual(_git(["rev-parse", "HEAD"], sdir), self.c1)

    def test_first_snapshot_is_a_self_contained_base(self):
        # The first snapshot of a repo is one full base segment (baseCommit is
        # the commit itself), restorable standalone.
        repo2 = os.path.join(self.tmp, "src2")
        os.makedirs(repo2)
        _git(["init", "-q"], repo2)
        with open(os.path.join(repo2, "g.txt"), "w") as gf:
            gf.write("x\n")
        _git(["add", "."], repo2)
        _git(["commit", "-qm", "only"], repo2)
        commit = _git(["rev-parse", "HEAD"], repo2)

        sync = FakeCASSync()
        store = GitSourceStore(sync)
        entry = store.snapshot(repo2, "https://example.com/repo2", commit)
        self.assertEqual(entry["baseCommit"], commit)
        self.assertEqual(len(entry["segments"]), 1)

        shutil.rmtree(repo2)
        dest = os.path.join(self.tmp, "restored2")
        store.restore(entry, dest)
        self.assertEqual(_git(["rev-parse", "HEAD"], dest), commit)


if __name__ == "__main__":
    unittest.main()
