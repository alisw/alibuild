"""Content-addressed git sources for hermetic builds and reconstruction.

A source is stored in the CAS as a **base bundle** (full history up to the
nearest ancestor tag) plus a **thin delta bundle** (the objects between the base
and the wanted commit). The base is deduplicated by its commit, so many commits
sharing a release tag reuse one base; deltas are deduplicated by commit. This
lets a build's source be restored later with no access to the upstream repo,
which is what makes reconstruction independent of upstream git. See
REMOTE_STORE_CAS_AC.md (Phase 6).

The base-selection rule (nearest ancestor tag) is a pure storage optimisation:
each source artifact records the exact base/delta digests it used, so a restore
follows those pointers and never re-derives the rule.
"""

import hashlib
import json
import os
import os.path
import tempfile

from alibuild_helpers.git import git


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


def _nearest_tag_commit(repo_dir, commit):
  """Return the commit of the nearest ancestor tag of `commit`, or None."""
  err, out = git(("describe", "--tags", "--abbrev=0", commit),
                 directory=repo_dir, check=False)
  if err or not out.strip():
    return None
  return git(("rev-parse", out.strip() + "^{commit}"), directory=repo_dir).strip()


class GitSourceStore:
  """Store and restore git sources as base + thin-delta bundles in the CAS."""

  def __init__(self, sync):
    self.sync = sync

  def _bundle(self, repo_dir, commit, base_commit, out_path):
    """Write a git bundle of `commit` (thin against base_commit if given) to
    out_path. Uses throwaway tags, since `git bundle` advertises refs, not bare
    SHAs, and cleans them up afterwards."""
    snap = "_alibuild_snap_" + commit
    git(("tag", "-f", snap, commit), directory=repo_dir)
    try:
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

  def snapshot(self, repo_dir, source_url, commit):
    """Capture source_url@commit (present in the git repo at repo_dir) into the
    CAS, deduplicating the base and delta. Returns a source-artifact dict."""
    repo_id = _repo_id(source_url)
    base_commit = _nearest_tag_commit(repo_dir, commit)
    if base_commit == commit:
      base_commit = None   # commit is itself a tag: just store it as one bundle

    base_digest = None
    if base_commit:
      base_key = "sources/git/%s/base/%s.json" % (repo_id, base_commit)
      pointer = self.sync.read_object_json(base_key)
      if pointer:
        base_digest = pointer["digest"]
      else:
        with tempfile.TemporaryDirectory() as tmp:
          bundle = os.path.join(tmp, "base.bundle")
          self._bundle(repo_dir, base_commit, None, bundle)
          base_digest = self.sync.put_file_as_blob(bundle)
        self.sync.write_object_json(base_key, {"digest": base_digest})

    delta_key = "sources/git/%s/delta/%s.json" % (repo_id, commit)
    pointer = self.sync.read_object_json(delta_key)
    if pointer:
      delta_digest = pointer["digest"]
    else:
      with tempfile.TemporaryDirectory() as tmp:
        bundle = os.path.join(tmp, "delta.bundle")
        self._bundle(repo_dir, commit, base_commit, bundle)
        delta_digest = self.sync.put_file_as_blob(bundle)
      self.sync.write_object_json(delta_key, {"digest": delta_digest})

    return {"type": "git", "source": source_url, "commit": commit,
            "baseCommit": base_commit, "baseDigest": base_digest,
            "deltaDigest": delta_digest}

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
    """Materialise the source described by `entry` into dest_dir as a checkout,
    with no access to the upstream repo."""
    os.makedirs(dest_dir, exist_ok=True)
    git(("init", "-q"), directory=dest_dir)
    with tempfile.TemporaryDirectory() as tmp:
      if entry.get("baseDigest"):
        base = os.path.join(tmp, "base.bundle")
        self.sync.download_blob(entry["baseDigest"], base)
        git(("fetch", "-q", base, "refs/*:refs/_recon/base/*"), directory=dest_dir)
      delta = os.path.join(tmp, "delta.bundle")
      self.sync.download_blob(entry["deltaDigest"], delta)
      git(("fetch", "-q", delta, "refs/*:refs/_recon/delta/*"), directory=dest_dir)
    git(("-c", "advice.detachedHead=false", "checkout", "-q", entry["commit"]),
        directory=dest_dir)
