"""Content-addressed git sources for hermetic builds and reconstruction.

A source is stored in the CAS as an **incremental chain of thin git bundles**: a
one-off **base bundle** (the full history the first time a repo is snapshotted or
after a re-baseline) followed by tiny **delta bundles**, each thin against the
repo's previous snapshot. So a stream of close commits -- e.g. daily builds of
the same package -- shares one base and stores only its per-commit delta, instead
of duplicating the whole source every day.

Each source artifact records the ordered list of segment digests needed to
restore its commit (`segments`), so a restore just fetches and applies them in
order -- no re-derivation of the chain. Restore prefers this CAS path (fast,
offline) and falls back to cloning upstream on any failure: under normal
conditions upstream is available, so the snapshot is a backup + fetch speedup
rather than the sole source of truth. See REMOTE_STORE_CAS_AC.md (Phase 6).
"""

import hashlib
import json
import os
import os.path
import shutil
import tempfile

from alibuild_helpers.git import git, clone_speedup_options
from alibuild_helpers.log import warning, debug


def _repo_id(source_url):
  return hashlib.sha256(source_url.encode("utf-8")).hexdigest()


def store_refs(sync, source_url, scm_refs):
  """Store the ref->commit mapping (scm_refs, as produced by `git ls-remote`)
  as a content-addressed CAS blob, so tag resolution can happen offline at
  reconstruct time without contacting upstream. Returns a refs-artifact dict or
  None when there are no refs."""
  if not scm_refs:
    return None
  blob = json.dumps(scm_refs, sort_keys=True).encode("utf-8")
  return {"type": "git-refs", "source": source_url,
          "digest": sync.put_bytes_as_blob(blob)}


def load_refs(sync, artifact):
  """Return the ref->commit mapping stored in a refs artifact."""
  return json.loads(sync.read_blob(artifact["digest"]))


def apply_refs(repo_dir, scm_refs):
  """Recreate tag refs in a restored repo from the cached mapping, so
  `git ls-remote` against it resolves tags offline. Best-effort: refs whose
  objects are not present in the restored repo are skipped."""
  for ref, sha in scm_refs.items():
    if ref.startswith("refs/tags/"):
      git(("update-ref", ref, sha), directory=repo_dir, check=False)


def _is_ancestor(repo_dir, maybe_ancestor, commit):
  """Whether maybe_ancestor is an ancestor of commit (both present in repo_dir).
  Used to decide whether a new snapshot can be a thin delta against the current
  chain head; a False (branch switch, force-push, missing commit) re-baselines."""
  if not maybe_ancestor:
    return False
  err, _ = git(("merge-base", "--is-ancestor", maybe_ancestor, commit),
               directory=repo_dir, check=False)
  return err == 0


class GitSourceStore:
  """Store and restore git sources as base + thin-delta bundles in the CAS."""

  def __init__(self, sync):
    self.sync = sync

  def _backfill_objects(self, repo_dir, commit, base_commit):
    """Materialise the objects a bundle of `commit` (minus base_commit) needs.

    aliBuild mirrors are treeless/blobless partial clones, so a bundle's trees and
    blobs are absent locally; `git bundle create` would otherwise lazily fetch them
    from the promisor remote one object at a time -- thousands of serial round-trips
    that look like a hang. Instead, fetch the whole needed closure in a single
    packfile. `--refetch` bypasses negotiation (so already-"present" commits don't
    suppress the transfer), and the permissive filter override lifts the mirror's
    tree:0/blob:none filter for this one fetch. Guarded on there being missing
    objects, so it is a no-op on a full mirror (e.g. the migrate path's clones)."""
    rev = ["rev-list", "--objects", "--missing=print", commit]
    if base_commit:
      rev += ["--not", base_commit]
    err, out = git(tuple(rev), directory=repo_dir, check=False)
    if err or not any(line.startswith("?") for line in out.splitlines()):
      return   # full mirror / already backfilled -> nothing to fetch
    debug("Backfilling partial-clone objects for %s before bundling", commit)
    # Bound the backfill explicitly: a first full-history backfill for a monster
    # repo can be very large, and we would rather fall back to upstream (a caught,
    # non-fatal skip of the snapshot) than stall the build. Tunable for such repos
    # via ALIBUILD_GIT_BACKFILL_TIMEOUT; a materialised incremental delta is small
    # and completes well within it.
    git(("-c", "remote.origin.partialclonefilter=blob:limit=1t",
         "fetch", "--refetch", "--no-tags", "origin", commit), directory=repo_dir,
        timeout=int(os.environ.get("ALIBUILD_GIT_BACKFILL_TIMEOUT", "600")))

  def _bundle(self, repo_dir, commit, base_commit, out_path):
    """Write a git bundle of `commit` (thin against base_commit if given) to
    out_path. Uses throwaway tags, since `git bundle` advertises refs, not bare
    SHAs, and cleans them up afterwards."""
    snap = "_alibuild_snap_" + commit
    git(("tag", "-f", snap, commit), directory=repo_dir)
    try:
      # Ensure the objects the bundle must contain are present locally, so bundle
      # create doesn't hang lazily fetching them from a partial mirror one at a time.
      self._backfill_objects(repo_dir, commit, base_commit)
      if base_commit:
        base_tag = "_alibuild_base_" + base_commit
        git(("tag", "-f", base_tag, base_commit), directory=repo_dir)
        try:
          git(("bundle", "create", out_path, snap, "--not", base_tag),
              directory=repo_dir)
        finally:
          git(("tag", "-d", base_tag), directory=repo_dir, check=False)
      else:
        git(("bundle", "create", out_path, snap), directory=repo_dir)
    finally:
      git(("tag", "-d", snap), directory=repo_dir, check=False)

  # Re-baseline (store a fresh full base bundle) once the incremental chain gets
  # this long: bounds the number of bundles a restore must fetch. Each fetch is a
  # small local CAS blob, so this can be generous; a fresh base costs storage
  # once. Daily builds hit this roughly twice a year at the default.
  MAX_CHAIN = 250

  def snapshot(self, repo_dir, source_url, commit):
    """Capture source_url@commit (present in repo_dir) into the CAS as an
    incremental segment, thin against the repo's previous snapshot when possible.
    Returns a source-artifact dict recording the ordered `segments` to restore.

    Idempotent per commit; deduplicating by content hash means re-snapshotting an
    unchanged commit, or one whose delta bytes already exist, re-uploads nothing.
    Advances a per-repo rolling head so the next snapshot deltas against this one."""
    repo_id = _repo_id(source_url)

    # Already snapshotted this exact commit -> reuse its recorded chain.
    seg_key = "sources/git/%s/segment/%s.json" % (repo_id, commit)
    existing = self.sync.read_object_json(seg_key)
    if existing:
      return {"type": "git", "source": source_url, "commit": commit,
              "baseCommit": existing.get("baseCommit"),
              "segments": existing["segments"]}

    # Thin against the chain head when it is an ancestor of `commit` (the common
    # "next daily" case) and the chain is not too long; otherwise re-baseline.
    head_key = "sources/git/%s/head.json" % repo_id
    head = self.sync.read_object_json(head_key) or {}
    prior = head.get("segments", [])
    if (head.get("commit") and len(prior) < self.MAX_CHAIN and
        _is_ancestor(repo_dir, head["commit"], commit)):
      base_commit = head["commit"]
      base_of_chain = head.get("baseCommit") or head["commit"]
    else:
      base_commit, prior, base_of_chain = None, [], commit   # start a new chain

    with tempfile.TemporaryDirectory() as tmp:
      bundle = os.path.join(tmp, "segment.bundle")
      self._bundle(repo_dir, commit, base_commit, bundle)
      digest = self.sync.put_file_as_blob(bundle)

    segments = prior + [digest]
    record = {"digest": digest, "parent": base_commit,
              "baseCommit": base_of_chain, "segments": segments}
    self.sync.write_object_json(seg_key, record)
    self.sync.write_object_json(head_key, {"commit": commit,
                                           "baseCommit": base_of_chain,
                                           "segments": segments})
    return {"type": "git", "source": source_url, "commit": commit,
            "baseCommit": base_of_chain, "segments": segments}

  def restore_to_source_dir(self, entry, work_dir):
    """Restore an entry's archived git source into the SOURCES layout that
    checkout_sources expects (work_dir/SOURCES/<pkg>/<version>/<short>), with the
    original tags applied, so a rebuild checks out it offline (the isdir branch
    of checkout_sources) instead of cloning the upstream URL. Returns the source
    dir, or None if the entry has no source artifact.

    The <short> directory name replicates short_commit_hash(): the recorded
    commit.ref is exactly spec["commit_hash"] from the original build, so this
    matches what checkout_sources will compute at rebuild time."""
    action = entry["action"]
    artifact = action.get("sourceArtifact")
    ref = action.get("commit", {}).get("ref")
    if not artifact or not ref:
      return None
    tag = action.get("tag")
    short = ref if tag == ref else ref[:10]
    source_dir = os.path.join(work_dir, "SOURCES", action["package"],
                              action["version"], short)
    self.restore(artifact, source_dir)
    refs_artifact = action.get("refsArtifact")
    if refs_artifact:
      apply_refs(source_dir, load_refs(self.sync, refs_artifact))
    return source_dir

  def restore(self, entry, dest_dir):
    """Materialise the source described by `entry` into dest_dir as a checkout.

    Prefers the archived CAS chain (fast, offline). On any failure -- a missing
    blob, a broken chain, an unexpected bundle error -- falls back to cloning
    upstream, since under normal conditions upstream is available and the
    snapshot is a backup/speedup, not the sole source of truth."""
    os.makedirs(dest_dir, exist_ok=True)
    try:
      self._restore_from_cas(entry, dest_dir)
    except Exception as exc:   # pylint: disable=broad-except
      source = entry.get("source")
      if not source:
        raise
      warning("Restoring %s@%s from the CAS failed (%s); cloning upstream instead",
              source, entry.get("commit", "?"), exc)
      self._restore_from_upstream(entry, dest_dir)

  def _restore_from_cas(self, entry, dest_dir):
    """Rebuild the checkout from the archived bundle chain in the CAS."""
    git(("init", "-q"), directory=dest_dir)
    with tempfile.TemporaryDirectory() as tmp:
      segments = entry.get("segments")
      if segments:
        # Fetch the chain in order: each thin segment's prerequisites are
        # supplied by the segments before it.
        for idx, digest in enumerate(segments):
          bundle = os.path.join(tmp, "seg%d.bundle" % idx)
          self.sync.download_blob(digest, bundle)
          git(("fetch", "-q", bundle, "refs/*:refs/_recon/s%d/*" % idx),
              directory=dest_dir)
      else:
        # Backward compatibility: pre-chain base/delta artifacts.
        if entry.get("baseDigest"):
          base = os.path.join(tmp, "base.bundle")
          self.sync.download_blob(entry["baseDigest"], base)
          git(("fetch", "-q", base, "refs/*:refs/_recon/base/*"), directory=dest_dir)
        delta = os.path.join(tmp, "delta.bundle")
        self.sync.download_blob(entry["deltaDigest"], delta)
        git(("fetch", "-q", delta, "refs/*:refs/_recon/delta/*"), directory=dest_dir)
    git(("-c", "advice.detachedHead=false", "checkout", "-q", entry["commit"]),
        directory=dest_dir)

  def _restore_from_upstream(self, entry, dest_dir):
    """Fallback: clone the source from upstream and check out the commit."""
    shutil.rmtree(dest_dir, ignore_errors=True)
    os.makedirs(os.path.dirname(dest_dir) or ".", exist_ok=True)
    git(("clone", "-q", *clone_speedup_options(), entry["source"], dest_dir))
    git(("-c", "advice.detachedHead=false", "checkout", "-q", entry["commit"]),
        directory=dest_dir)
