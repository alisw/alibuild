"""Migrate legacy (action-addressed) releases into the reapi CAS + AC layout.

Every aliBuild tarball embeds its own provenance in a `.meta.json` written by
create_provenance_info(): the alidist commit that produced it, the defaults
name, the package's tag/source, and the full dependency DAG with hashes. So
migration is mostly metadata extraction, not archaeology: read `.meta.json`,
recover the full recipe from the recorded alidist commit, and synthesise a
reconstruct-complete Action Cache entry, with the tarball preserved in the CAS.
See REMOTE_STORE_CAS_AC.md (Migration).

Legacy builds did not record their container, so migration supplies one (an
explicit override or the architecture's current default builder), marked
`"provenance": "migration-default"` so assumed environment is never confused
with captured environment.
"""

import hashlib
import json
import os
import os.path
import re
import shutil
import tarfile
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from requests.exceptions import (ChunkedEncodingError,
                                 ConnectionError as RequestsConnectionError, Timeout)

from alibuild_helpers.git import git, Git
from alibuild_helpers.log import info, debug, warning, dieOnError, byte_progress
from alibuild_helpers.sync import remote_from_url
from alibuild_helpers.sync_reapi import REAPIRemoteSync, add_reapi_store_args
from alibuild_helpers.source import GitSourceStore, store_refs
from alibuild_helpers.utilities import default_builder_image, parseRecipe


def add_parser(subparsers, detected_arch, work_dir_default):
  """Register the `migrate` subcommand's parser -- its options live with the command,
  keeping the migration surface out of the shared top-level argument parser."""
  p = subparsers.add_parser(
    "migrate", help="migrate legacy tarballs into a reapi:// store",
    description="Migrate legacy (action-addressed) release tarballs into a "
                "reapi:// CAS + Action Cache, using each tarball's embedded "
                ".meta.json provenance and the recorded alidist commit.")
  p.add_argument("tarballs", metavar="TARBALL", nargs="*",
                 help="Legacy tarball(s) to migrate: local paths, or PACKAGE/VERSION-REVISION "
                      "specs when --read-store is given. Not needed with --enrich-sources.")
  p.add_argument("--read-store", dest="read_store", default=None, metavar="URL",
                 help="Read-only http(s) old store to fetch tarballs from (e.g. "
                      "https://s3.cern.ch/swift/v1/alibuild-repo). The old store is never "
                      "written to.")
  p.add_argument("--alidist", default=None, metavar="DIR",
                 help="Path to an alidist git checkout/mirror from which to recover recipes at "
                      "the recorded commits. Required to migrate tarballs; not needed for "
                      "ledger-only source recovery (--snapshot-sources with no TARBALL).")
  add_reapi_store_args(
    p, remote_help="reapi:// store to migrate into.",
    arch_help="Architecture being migrated. Default '%(default)s'.",
    detected_arch=detected_arch, work_dir_default=work_dir_default)
  p.add_argument("--container", dest="container", default=None, metavar="IMAGE",
                 help="Container image to record for the migrated builds (marked as assumed). "
                      "Defaults to the architecture's default builder.")
  p.add_argument("--storage", dest="storage", choices=("ephemeral", "permanent"),
                 default="ephemeral",
                 help="Retention for migrated tarball blobs: 'ephemeral' (default) or 'permanent' "
                      "(pinned; use for real production releases).")
  p.add_argument("--no-verify", dest="no_verify", action="store_true",
                 help="Skip the structural self-check of recovered recipes.")
  p.add_argument("--populate-system", dest="populate_system", action="store_true",
                 help="Bulk-retroactive: walk the WHOLE reapi ledger and add validate-system "
                      "nodes (make, yacc-like, ... recovered from --alidist) to every build entry. "
                      "Normal migrations already do this automatically for what they migrate; use "
                      "this to backfill entries migrated before the feature existed. Idempotent; "
                      "honours -n/--dry-run.")
  p.add_argument("--allow-no-provenance", dest="allow_no_provenance", action="store_true",
                 help="For pre-provenance tarballs (no .meta.json, so no recipe/AC entry can be "
                      "recovered), still store the tarball and its store redirect + per-package "
                      "link, reserving the version-revision so a later fresh build doesn't shadow "
                      "it. Such packages are preserved and installable but NOT reconstructable "
                      "(no ledger entry).")
  p.add_argument("--closure", dest="closure", action="store_true",
                 help="Treat each TARBALL as a top package (PACKAGE/VERSION-REVISION) and migrate "
                      "its whole build closure, read from the old store's dist tree. Requires "
                      "--read-store.")
  p.add_argument("--match", dest="match", default=None, metavar="REGEX",
                 help="Instead of (or in addition to) explicit TARBALLs, migrate every "
                      "PACKAGE/VERSION-REVISION published for the architecture in the old store "
                      "whose spec matches REGEX (Python re.search). '.*' migrates the whole arch. "
                      "Requires --read-store; composes with --closure (each match is expanded to "
                      "its closure) and -n/--dry-run (preview the selection without writing).")
  p.add_argument("-j", "--jobs", dest="jobs", type=int, default=1,
                 help="Migrate this many packages in parallel (overlaps the downloads/uploads). "
                      "Peak disk scales with the number of jobs. Default %(default)d.")
  p.add_argument("--snapshot-sources", dest="snapshot_sources", action="store_true",
                 help="Archive each release's git source into the ledger (clones upstream once "
                      "per package) so releases become offline-reconstructible. Idempotent: "
                      "already-migrated releases are enriched in place from the Action Cache (no "
                      "tarball re-download, no CAS rewrite). With no TARBALL given, walks the whole "
                      "ledger to recover sources -- works even after the old store has pruned it.")
  p.add_argument("--source-mirror", dest="source_mirror", default=None, metavar="DIR",
                 help="Where to cache source clones for --snapshot-sources. Defaults to "
                      "WORKDIR/MIRROR-migrate.")
  return p


class _TextReader:
  """Minimal recipe reader over an in-memory string, for parseRecipe."""
  url = "<recovered recipe>"

  def __init__(self, text):
    self.text = text

  def __call__(self):
    return self.text


def verify_recovered_recipe(meta, recipe_text):
  """Structural self-check that the recipe recovered from the recorded alidist
  commit matches the tarball's metadata: it parses, its package field matches,
  and every recorded dependency carries a hash. Returns (ok, reason).

  This is a structural check, not a full action-hash recompute (which would
  require replaying defaults + scm_refs, i.e. alibuild's planning phase). It
  catches the realistic failure modes -- wrong/renamed recipe, corrupt metadata,
  a missing dependency hash -- without risking false mismatches."""
  try:
    err, spec, _ = parseRecipe(_TextReader(recipe_text))
  except Exception as exc:   # pylint: disable=broad-except
    return False, "recovered recipe does not parse: %s" % exc
  if err or not spec:
    return False, "recovered recipe does not parse: %s" % err
  if spec.get("package", "").lower() != meta["package"]["name"].lower():
    return False, "recovered recipe is for %r, expected %r" % (
      spec.get("package"), meta["package"]["name"])
  recursive = meta.get("dependencies", {}).get("recursive", {})
  for kind in ("build", "runtime"):
    for dep in recursive.get(kind, []):
      if not dep.get("hash"):
        return False, "dependency %r has no recorded hash" % dep.get("name")
  return True, ""


def read_meta_json(tarball_path):
  """Extract and parse the package's .meta.json from a legacy tarball, or None
  if the tarball predates embedded provenance. Iterates members lazily and stops
  at .meta.json, rather than getmembers() which decompresses the whole archive."""
  with tarfile.open(tarball_path) as tar:
    for member in tar:
      if os.path.basename(member.name) == ".meta.json":
        return json.loads(tar.extractfile(member).read())
  return None


def download_from_old_store(read_url, architecture, spec, dest_dir):
  """Download a tarball from a read-only HTTP old store. `spec` is
  PACKAGE/VERSION-REVISION (e.g. 'ROOT/v6-28-04-1').

  The per-package object is a *symlink pointer* (its body is a store-relative
  path like '<arch>/store/<hh>/<hash>/<file>'), not the tarball -- the swift
  REST endpoint serves the body, not a redirect. So we GET the pointer, resolve
  it to the content-addressed store object, and download that. The old store is
  only ever read here, never written."""
  pkg, _, verrev = spec.partition("/")
  dieOnError(not verrev, "expected PACKAGE/VERSION-REVISION, got %r" % spec)
  tarball = "%s-%s.%s.tar.gz" % (pkg, verrev, architecture)
  base = read_url.rstrip("/")
  link_url = "%s/TARS/%s/%s/%s" % (base, architecture, pkg, tarball)

  debug("HTTP GET %s (resolve symlink)", link_url)
  link = requests.get(link_url, timeout=(30, 60))
  link.raise_for_status()
  target = re.sub(r"^(\.\./)+", "", link.text.strip())   # tolerate ../.. prefixes
  dieOnError("store/" not in target,
             "could not resolve %s via its symlink at %s (got %r)" %
             (spec, link_url, target[:120]))
  if not target.startswith("TARS/"):
    target = "TARS/" + target

  dest = os.path.join(dest_dir, tarball)
  store_url = "%s/%s" % (base, target)
  debug("HTTP GET %s (download tarball)", store_url)
  _download_with_resume(store_url, dest)
  return dest


def _download_with_resume(url, dest, retries=5):
  """Stream url to dest, resuming from the bytes already on disk (HTTP Range) if
  the connection drops or stalls mid-download -- so a blip on a multi-GB file
  doesn't throw away the whole transfer. (connect, read) timeout of (30, 120):
  a stalled read errors after 120s and we resume rather than restart."""
  total, progress, offset = None, None, 0
  for attempt in range(retries + 1):
    headers = {"Range": "bytes=%d-" % offset} if offset else {}
    try:
      with requests.get(url, stream=True, headers=headers, timeout=(30, 120)) as resp:
        if offset and resp.status_code == 206:
          mode = "ab"                       # server honoured the range: append
        else:
          resp.raise_for_status()           # 200 (fresh, or range ignored): restart
          mode, offset = "wb", 0
        if total is None:
          total = int(resp.headers.get("content-length", 0)) or None
        if progress is None:
          progress = byte_progress("download " + os.path.basename(dest), total)
        with open(dest, mode) as out:
          for chunk in resp.iter_content(1 << 20):
            out.write(chunk)
            offset += len(chunk)
            progress(len(chunk))
      dieOnError(total is not None and offset != total,
                 "incomplete download of %s (%d/%d bytes)" % (dest, offset, total))
      return
    except (ChunkedEncodingError, RequestsConnectionError, Timeout) as exc:
      offset = os.path.getsize(dest) if os.path.exists(dest) else 0
      if attempt >= retries:
        raise
      warning("Download of %s interrupted at %d bytes; resuming (%d/%d): %s",
              os.path.basename(dest), offset, attempt + 1, retries, exc)
      time.sleep(2)


def _list_old_store(read_url, prefix):
  """List keys under prefix in a read-only swift/HTTP old store."""
  url = "%s/?prefix=%s&delimiter=/" % (read_url.rstrip("/"), prefix)
  debug("HTTP GET %s", url)
  resp = requests.get(url, timeout=120)
  resp.raise_for_status()
  return resp.text.split()


def _arch_package_names(read_url, architecture):
  """The package-directory names under TARS/<arch>/ (longest first, so
  _match_package prefers the more specific name), minus the publisher/store
  subtrees. Used to map closure/dep tarball filenames back to package names."""
  pkg_prefix = "TARS/%s/" % architecture
  special = {"dist", "dist-direct", "dist-runtime", "store"}
  return sorted({k[len(pkg_prefix):].rstrip("/")
                 for k in _list_old_store(read_url, pkg_prefix)
                 if k.startswith(pkg_prefix) and k.endswith("/")} - special,
                key=len, reverse=True)


def _dist_folder_specs(read_url, architecture, subtree, top_spec, names):
  """List the PACKAGE/VERSION-REVISION specs recorded in a dist subtree folder for
  top_spec. `subtree` is 'dist' (full closure), 'dist-direct' (direct deps) or
  'dist-runtime' (runtime closure). Returns [] if the folder does not exist."""
  pkg, _, verrev = top_spec.partition("/")
  suffix = ".%s.tar.gz" % architecture
  prefix = "TARS/%s/%s/%s/%s-%s/" % (architecture, subtree, pkg, pkg, verrev)
  filenames = sorted({os.path.basename(k) for k in _list_old_store(read_url, prefix)
                      if k.endswith(suffix)})
  specs = []
  for fname in filenames:
    spec = _match_package(read_url, architecture, names, fname[:-len(suffix)], suffix)
    if spec:
      specs.append(spec)
  return specs


def enumerate_closure(read_url, architecture, top_spec, strict=True):
  """Return the PACKAGE/VERSION-REVISION specs for the full build closure of
  top_spec, read cheaply from the old store's dist tree (no tarball downloads).

  Only packages that were a *build target* have a dist/ tree. A dependency-only or
  prefer_system package (e.g. ninja) has none: with strict=True (an explicit
  `--closure PKG`) that is an error (likely a wrong spec); with strict=False (driven
  by `--match`, where every spec is real and enumerated) it just means the closure is
  the package itself, so we return [top_spec] instead of failing."""
  pkg, _, verrev = top_spec.partition("/")
  dieOnError(not verrev, "expected PACKAGE/VERSION-REVISION, got %r" % top_spec)
  names = _arch_package_names(read_url, architecture)
  specs = _dist_folder_specs(read_url, architecture, "dist", top_spec, names)
  if not specs:
    dieOnError(strict, "no dist closure at TARS/%s/dist/%s/%s-%s/ -- is %s right?" %
               (architecture, pkg, pkg, verrev, top_spec))
    debug("No dist tree for %s (dependency-only/prefer_system); migrating it alone",
          top_spec)
    return [top_spec]
  # The dist tree includes the top package itself, but guard just in case.
  if top_spec not in specs:
    specs.append(top_spec)
  return specs


def enumerate_arch(read_url, architecture, pattern=None):
  """Return every PACKAGE/VERSION-REVISION published for `architecture` in the old
  store, optionally filtered by a regex (`re.search` against the 'PACKAGE/VERSION-
  REVISION' spec). Reads only the per-package link listing -- no tarball downloads.
  Used by `migrate --match` to bulk-migrate a whole arch (or a regex subset) so the
  new store's revisions are the authoritative old-store ones before any fresh build
  claims them."""
  suffix = ".%s.tar.gz" % architecture
  pkg_prefix = "TARS/%s/" % architecture
  names = _arch_package_names(read_url, architecture)
  regex = re.compile(pattern) if pattern else None
  specs = set()
  for name in names:
    for key in _list_old_store(read_url, "%s%s/" % (pkg_prefix, name)):
      base = os.path.basename(key.rstrip("/"))
      if not base.endswith(suffix):
        continue   # skips 'latest*' symlinks, manifests, etc.
      spec = _match_package(read_url, architecture, names, base[:-len(suffix)], suffix)
      if spec and (regex is None or regex.search(spec)):
        specs.add(spec)
  return sorted(specs)


def recover_legacy_deps(read_url, architecture, items, sync):
  """Second pass of a legacy migration: for every migrated item that is a legacy
  (pre-provenance) AC entry, recover its dependency graph from the old store's
  dist-direct/dist-runtime folders and write it into the entry, hash-linked. Each
  dep is resolved to the hash it lives under in the *new* store (a legacy dep's
  content hash, or a full build's action hash) via the per-package link, so the
  graph walks with the existing machinery. Self-contained and idempotent: reads the
  new store to find legacy entries, so it also enriches already-present ones on a
  re-run. Deps that can't be resolved are dropped (partial graph). Returns the number
  of entries enriched."""
  names = _arch_package_names(read_url, architecture)
  hash_cache = {}

  def action_hash(spec):
    if spec not in hash_cache:
      pkg, _, verrev = spec.partition("/")
      version, _, revision = verrev.rpartition("-")
      try:
        hash_cache[spec] = sync.resolve_action_hash(pkg, version, revision)
      except Exception:   # pylint: disable=broad-except
        hash_cache[spec] = None
    return hash_cache[spec]

  def refs(specs):
    return [{"package": dep.partition("/")[0], "actionHash": action_hash(dep)}
            for dep in specs if action_hash(dep)]

  enriched = 0
  for spec in items:
    content_hash = action_hash(spec)
    if not content_hash:
      continue
    entry = sync.read_ac_entry(content_hash)
    if entry is None or entry["action"].get("kind") != "legacy":
      continue
    direct = [d for d in _dist_folder_specs(read_url, architecture, "dist-direct", spec, names)
              if d != spec]
    runtime = [d for d in _dist_folder_specs(read_url, architecture, "dist-runtime", spec, names)
               if d != spec]
    entry["action"]["deps"] = refs(direct)
    entry["action"]["runtimeDeps"] = refs(runtime)
    sync.update_ac_entry(entry)
    enriched += 1
  return enriched


def _match_package(read_url, architecture, names, base, suffix):
  """Map a closure tarball basename '<pkg>-<ver>-<rev>' to PACKAGE/VERSION-REVISION.

  A package name can contain dashes, and one name can be a prefix of another
  (e.g. 'ninja' vs 'ninja-fortran'): the tarball 'ninja-fortran-v1.11.1.g9-25'
  is package 'ninja' with version 'fortran-v1.11.1.g9', not 'ninja-fortran'.
  Longest-prefix alone is wrong, so when several package names match we pick the
  one whose per-package symlink actually exists on the store."""
  candidates = [n for n in names if base.startswith(n + "-")]   # names are longest-first
  if not candidates:
    return None
  if len(candidates) == 1:
    return "%s/%s" % (candidates[0], base[len(candidates[0]) + 1:])
  for name in candidates:
    url = "%s/TARS/%s/%s/%s%s" % (read_url.rstrip("/"), architecture, name, base, suffix)
    try:
      if requests.head(url, timeout=(10, 30)).status_code == 200:
        return "%s/%s" % (name, base[len(name) + 1:])
    except Exception:   # pylint: disable=broad-except
      pass
  warning("Ambiguous package for %s (candidates %s); guessing %s",
          base, candidates, candidates[0])
  return "%s/%s" % (candidates[0], base[len(candidates[0]) + 1:])


def _alidist_remote(alidist_dir):
  """Return the alidist remote URL (origin of the local clone, else canonical)."""
  if alidist_dir:
    err, out = git(("config", "--get", "remote.origin.url"),
                   directory=alidist_dir, check=False)
    if not err and out.strip():
      return out.strip()
  return "https://github.com/alisw/alidist"


def _github_raw_base(remote_url):
  """Map a github.com remote URL to its raw.githubusercontent.com base."""
  match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", remote_url or "")
  return "https://raw.githubusercontent.com/" + (match.group(1) if match else "alisw/alidist")


def recover_recipe(alidist_dir, alidist_commit, package):
  """Recover the full recipe of `package` at the recorded alidist commit.

  Tries the local alidist checkout first (`git show`); if the commit isn't
  present there -- dailies are often built from a CI/branch commit that isn't
  reachable from a plain `master` clone -- falls back to fetching the raw recipe
  from the alidist remote on GitHub by commit."""
  fname = package.lower() + ".sh"
  if alidist_dir:
    err, out = git(("show", "%s:%s" % (alidist_commit, fname)),
                   directory=alidist_dir, check=False)
    if not err:
      return out
    debug("%s not in local alidist; fetching from GitHub", alidist_commit)
  url = "%s/%s/%s" % (_github_raw_base(_alidist_remote(alidist_dir)), alidist_commit, fname)
  debug("HTTP GET %s (recover recipe)", url)
  resp = requests.get(url, timeout=60)
  resp.raise_for_status()
  return resp.text


def container_for_migration(architecture, override=None):
  """Return a container record for a migrated build: an explicit override or the
  architecture's default builder, marked as assumed (not captured) provenance."""
  image = override or default_builder_image(architecture)
  return {"runtime": "docker", "image": image, "digest": None,
          "provenance": "migration-default"}


def ac_entry_from_meta(meta, recipe_text, container, source_artifact=None,
                       refs_artifact=None, commit_hash=None):
  """Synthesise a (reconstruct-complete) Action Cache entry from a tarball's
  embedded .meta.json provenance and the recovered recipe.

  If a source was snapshotted (commit_hash resolved), commit.ref is set to that
  SHA -- which is what spec["commit_hash"] becomes at rebuild -- so the
  source-aware checkout's SOURCES path matches. Otherwise we fall back to the
  tag, all the provenance .meta.json gives us."""
  pkg = meta["package"]
  recipe_digest = hashlib.sha256((recipe_text or "").encode("utf-8", "ignore")).hexdigest()
  commit_ref = commit_hash or pkg.get("tag")

  def dep_refs(deps):
    return [{"package": d["name"], "actionHash": d["hash"]} for d in deps]

  recursive = meta.get("dependencies", {}).get("recursive", {})
  return {
    "schemaVersion": 2,
    "action": {
      "package": pkg["name"],
      "version": pkg["version"],
      "revision": pkg["revision"],
      "architecture": meta["architecture"],
      "actionHash": pkg["hash"],
      "commit": {"ref": commit_ref, "commitHash": commit_ref, "altRefs": {}},
      "source": pkg.get("source"),
      "tag": pkg.get("tag"),
      "defaults": meta.get("defaults"),
      "recipeDigest": "sha256:" + recipe_digest,
      "container": container,
      "sourceArtifact": source_artifact,
      "refsArtifact": refs_artifact,
      "deps": dep_refs(recursive.get("build", [])),
      "runtimeDeps": dep_refs(recursive.get("runtime", [])),
      "depsHash": "",
    },
  }


def _ref_candidates(tag):
  """Candidate refs to resolve a build's recorded tag, tolerating a deleted rc/
  branch. Dailies are built on an ``rc/<tag>`` branch that upstream later deletes,
  while the real ``<tag>`` tag survives -- so try the tag as-is, then with the
  ``rc/`` prefix stripped, then the bare basename."""
  candidates = [tag]
  if tag.startswith("rc/"):
    candidates.append(tag[len("rc/"):])
  base = tag.rsplit("/", 1)[-1]
  if base not in candidates:
    candidates.append(base)
  return candidates


def _resolve_source_commit(repo, source, tag):
  """Resolve `tag` to a commit in the mirror, fetching candidate refs from
  upstream as needed, and falling back to the surviving tag when the recorded
  ref (e.g. an rc/ branch built from, then deleted) is gone. Returns the commit
  SHA. Raises if nothing resolves."""
  def resolve(ref):
    err, out = git(("rev-parse", "--verify", "-q", ref + "^{commit}"),
                   directory=repo, check=False)
    return out.strip() if not err and out.strip() else None

  for cand in _ref_candidates(tag):
    commit = resolve(cand)
    if commit:
      return commit
    # Not present locally: try to fetch the candidate as a tag or a branch.
    for src_ref in ("refs/tags/%s" % cand, "refs/heads/%s" % cand):
      git(("fetch", "--quiet", source, "+%s:refs/_snap/%s" % (src_ref, cand)),
          directory=repo, check=False)
    commit = resolve("refs/_snap/%s" % cand)
    if commit:
      return commit
  raise RuntimeError(
    "could not resolve %r for %s (tried %s): the rc/ branch may be deleted and "
    "no surviving tag was found" % (tag, source, _ref_candidates(tag)))


def snapshot_legacy_source(sync, meta, mirror_dir):
  """Capture a legacy release's git source into the CAS at migrate time (while
  upstream is presumably still alive), so the release becomes offline-
  reconstructible. Clones a full bare mirror, reused per package across releases:
  a snapshot bundle (especially the first, full-history base) must pack objects
  locally, so a *partial* clone would force a slow object-by-object network
  backfill during `git bundle create` -- a full clone moves the same history once,
  in bulk, up front. Resolves the tag to a commit -- tolerating a deleted rc/
  branch by falling back to the surviving tag -- and snapshots source + refs.
  Returns (source_artifact, refs_artifact, commit_hash), all None on any failure
  (source archival is best-effort and must not abort a migration)."""
  source = meta["package"].get("source")
  if not source:
    return None, None, None
  try:
    repo = os.path.join(mirror_dir, meta["package"]["name"].lower())
    tag = meta["package"]["tag"]
    if not os.path.isdir(repo):
      os.makedirs(mirror_dir, exist_ok=True)
      git(("clone", "--quiet", "--bare", source, repo), directory=mirror_dir)
    else:
      # Refresh the reused mirror's tags + branches so a newer daily's refs are
      # present (candidates are also fetched on demand in _resolve_source_commit).
      git(("fetch", "--quiet", "--tags", source, "+refs/heads/*:refs/heads/*"),
          directory=repo, check=False)
    commit = _resolve_source_commit(repo, source, tag)
    source_artifact = GitSourceStore(sync).snapshot(repo, source, commit)
    scm_refs = Git().parseRefs(git(Git().listRefsCmd(repo), directory=repo))
    # Pin the recipe's own tag to the resolved commit so it still resolves offline
    # at reconstruct time even if it was an rc/ branch upstream has since deleted:
    # apply_refs then recreates it and `git checkout <tag>` works with no upstream.
    scm_refs.setdefault("refs/tags/" + tag, commit)
    refs_artifact = store_refs(sync, source, scm_refs)
    return source_artifact, refs_artifact, commit
  except Exception as exc:   # pylint: disable=broad-except
    warning("Could not snapshot source for %s from %s (it will not be offline-"
            "reconstructible): %s", meta["package"]["name"], source, exc)
    return None, None, None


def _enrich_entry(sync, entry, mirror_dir):
  """Add a source snapshot to an already-migrated AC entry, in place, from the
  entry itself -- no tarball download, no CAS write. The entry records the
  upstream git URL and tag, so we clone upstream, snapshot the (chained) source +
  refs bundles into the ledger, and rewrite the entry with sourceArtifact/
  refsArtifact and the resolved commit. Idempotent: a second run is a no-op.

  Returns 'migrated' (newly enriched), 'present' (already has a snapshot, or the
  package has no upstream source), or 'skipped' (could not enrich -- upstream
  gone; snapshot_legacy_source has already warned)."""
  action = entry["action"]
  package = action["package"]
  if action.get("sourceArtifact"):
    return "present"                       # already offline-reconstructible
  source = action.get("source")
  if not source:
    return "present"                       # no upstream source (e.g. defaults-release)

  meta = {"package": {"name": package, "source": source, "tag": action.get("tag")}}
  source_artifact, refs_artifact, commit = snapshot_legacy_source(sync, meta, mirror_dir)
  if not source_artifact:
    return "skipped"                       # snapshot_legacy_source already warned

  action["sourceArtifact"] = source_artifact
  action["refsArtifact"] = refs_artifact
  if commit:
    action["commit"] = {"ref": commit, "commitHash": commit,
                        "altRefs": action.get("commit", {}).get("altRefs", {})}
  sync.update_ac_entry(entry)
  info("Enriched %s %s-%s with source snapshot (commit %s)",
       package, action.get("version"), action.get("revision"), (commit or "?")[:12])
  return "migrated"


def enrich_source_snapshot(sync, package, version, revision, mirror_dir):
  """Enrich a single already-migrated release, resolved by (package, version,
  revision) via the per-package link. Used from the tarball/old-store migration
  path; the ledger-wide recovery uses `doEnrichSources`."""
  action_hash = sync.resolve_action_hash(package, version, revision)
  if not action_hash:
    warning("Could not resolve action hash for %s %s-%s; cannot enrich source",
            package, version, revision)
    return "skipped"
  entry = sync.read_ac_entry(action_hash)
  if entry is None:
    warning("No Action Cache entry for %s (%s); cannot enrich source",
            package, action_hash)
    return "skipped"
  return _enrich_entry(sync, entry, mirror_dir)


def doEnrichSources(args):
  """Recover source snapshots for an already-migrated set by walking the Action
  Cache ledger directly -- no old store, no closure, no tarballs. For every AC
  entry of the architecture that has an upstream source but no snapshot, clone
  upstream and archive the (chained) source into the ledger. This is how a daily
  is made offline-reconstructible after the fact, even once the old store has
  pruned it. Reached via `migrate --snapshot-sources` with no TARBALL."""
  dieOnError(not args.remoteStore or not args.remoteStore.startswith("reapi://"),
             "recovering sources (migrate --snapshot-sources with no TARBALL) requires "
             "a reapi:// remote store, got %r" % (args.remoteStore or "(none)"))
  ac_store = strip_rw(getattr(args, "acStore", ""))
  sync = remote_from_url(args.remoteStore, args.remoteStore, args.architecture,
                         args.workDir, getattr(args, "insecure", False),
                         ac_url=ac_store, ac_write_url=ac_store,
                         storage=getattr(args, "storage", "permanent"))
  dieOnError(not isinstance(sync, REAPIRemoteSync),
             "recovering sources requires a reapi:// remote store")

  mirror_dir = args.source_mirror or os.path.join(args.workDir, "MIRROR-migrate")
  dry_run = getattr(args, "dryRun", False)
  jobs = max(1, getattr(args, "jobs", 1) or 1)
  hashes = list(sync.iter_ac_entry_hashes(args.architecture))
  total = len(hashes)
  info("Enriching sources for %d Action Cache entr%s in %s", total,
       "y" if total == 1 else "ies", args.architecture)

  def process(idx, action_hash):
    entry = sync.read_ac_entry(action_hash)
    if entry is None:
      return "skipped"
    action = entry["action"]
    if dry_run:
      if action.get("sourceArtifact"):
        state = "already snapshotted"
      elif not action.get("source"):
        state = "no upstream source"
      else:
        state = "would snapshot from %s" % action["source"]
      info("[%d/%d] %s %s-%s: %s", idx, total, action["package"],
           action.get("version"), action.get("revision"), state)
      return "migrated" if state.startswith("would") else "present"
    result = _enrich_entry(sync, entry, mirror_dir)
    info("[%d/%d] %s: %s", idx, total, action["package"], result)
    return result

  if jobs > 1 and not dry_run:
    info("Enriching with %d parallel jobs", jobs)
    with ThreadPoolExecutor(max_workers=jobs) as pool:
      results = list(pool.map(lambda pair: process(*pair), enumerate(hashes, 1)))
  else:
    results = [process(idx, h) for idx, h in enumerate(hashes, 1)]

  info("Source enrichment %sdone: %d enriched, %d already present or source-less, "
       "%d skipped", "(dry-run) " if dry_run else "", results.count("migrated"),
       results.count("present"), results.count("skipped"))
  return results.count("skipped") == 0


def _recipe_requires(recipe_text, architecture):
  """The arch-filtered require names (build + runtime) of a recipe text."""
  err, spec, _ = parseRecipe(_TextReader(recipe_text))
  if err or spec is None:
    return []
  names = []
  for entry in (list(spec.get("requires", []) or []) +
                list(spec.get("build_requires", []) or [])):
    pkg, _, regex = str(entry).partition(":")
    if regex and not re.match(regex, architecture):
      continue   # arch-excluded dependency (e.g. "GCC-Toolchain:(?!osx)")
    names.append(pkg)
  return names


def _system_requirement_spec(recipe_text):
  """Parsed spec if the recipe declares a system_requirement (make, yacc-like, ...),
  else None. These are exactly the deps missing from a migrated entry: they produce
  no tarball, so they were never recorded as a (built) dependency."""
  err, spec, _ = parseRecipe(_TextReader(recipe_text))
  if err or spec is None or "system_requirement" not in spec:
    return None
  return spec


def _recipe_recoverer(alidist_dir, alidist_commit):
  """A cached `recover_recipe` closure (system recipes like make.sh recur across
  packages, so recover each at most once). Returns None on failure."""
  cache = {}
  def recipe_of(pkg):
    if pkg not in cache:
      try:
        cache[pkg] = recover_recipe(alidist_dir, alidist_commit, pkg)
      except Exception as exc:   # pylint: disable=broad-except
        debug("Could not recover recipe for %s@%s: %s", pkg, alidist_commit, exc)
        cache[pkg] = None
    return cache[pkg]
  return recipe_of


def _populate_entry_system_deps(sync, architecture, entry, recipe_of, dry_run):
  """Give one build AC entry its validate-system nodes: read its archived recipe,
  find requires that are system_requirement packages (via recipe_of), write a
  validate-system entry per such dep and reference it in the entry's deps. Idempotent
  (skips deps already present). Returns the number of system deps added."""
  from alibuild_helpers.build import build_validate_system_entry
  action = entry["action"]
  if action.get("kind") in ("validate-system", "legacy"):
    return 0
  recipe_digest = action.get("recipeDigest", "").split(":", 1)[-1]
  if not recipe_digest:
    return 0
  try:
    pkg_recipe = sync.read_blob(recipe_digest).decode("utf-8", "ignore")
  except Exception:   # pylint: disable=broad-except
    return 0
  have = {d["package"] for d in action.get("deps", [])}
  new_deps = []
  for req in _recipe_requires(pkg_recipe, architecture):
    if req in have:
      continue
    req_recipe = recipe_of(req)
    if req_recipe is None or _system_requirement_spec(req_recipe) is None:
      continue
    sysspec = dict(_system_requirement_spec(req_recipe), package=req, fullRecipe=req_recipe)
    sys_entry = build_validate_system_entry(sysspec, {}, architecture)
    new_deps.append({"package": req, "actionHash": sys_entry["action"]["actionHash"]})
    have.add(req)
    if not dry_run:
      sync.put_ac_entry(sys_entry, req_recipe)
  if new_deps:
    action["deps"] = action.get("deps", []) + new_deps
    if not dry_run:
      sync.update_ac_entry(entry)
    debug("%s-%s: +%d system dep(s): %s", action["package"], action.get("revision"),
          len(new_deps), ", ".join(d["package"] for d in new_deps))
  return len(new_deps)


def populate_system_deps(sync, architecture, alidist_dir, alidist_commit,
                         items=None, dry_run=False):
  """Give migrated packages the validate-system nodes a fresh build now writes, so
  reconstruct materialises their system recipes and re-runs the checks on the host
  with no --alidist bridge. With `items` (a list of PACKAGE/VERSION-REVISION specs)
  only those entries are processed -- the automatic pass run for every migration;
  with items=None the whole AC ledger is walked (bulk retroactive, `--populate-system`).
  Idempotent. Returns (entriesEnriched, depsAdded)."""
  recipe_of = _recipe_recoverer(alidist_dir, alidist_commit)

  def entries():
    if items is None:
      for action_hash in sync.iter_ac_entry_hashes(architecture):
        entry = sync.read_ac_entry(action_hash)
        if entry is not None:
          yield entry
    else:
      for spec in items:
        pkg, _, verrev = spec.partition("/")
        version, _, revision = verrev.rpartition("-")
        try:
          action_hash = sync.resolve_action_hash(pkg, version, revision)
        except Exception:   # pylint: disable=broad-except
          action_hash = None
        entry = sync.read_ac_entry(action_hash) if action_hash else None
        if entry is not None:
          yield entry

  enriched = added = 0
  for entry in entries():
    n = _populate_entry_system_deps(sync, architecture, entry, recipe_of, dry_run)
    if n:
      enriched += 1
      added += n
  return enriched, added


def doPopulateSystem(args):
  """migrate --populate-system: the bulk retroactive form -- walk the *whole* AC
  ledger and add validate-system nodes to every build entry (normal migrations do
  this automatically for what they migrate). Needs the reapi ledger + --alidist."""
  dieOnError(not args.remoteStore or not args.remoteStore.startswith("reapi://"),
             "migrate --populate-system requires a reapi:// remote store, got %r" %
             (args.remoteStore or "(none)"))
  dieOnError(not args.alidist, "--alidist is required to recover system recipes")
  ac_store = strip_rw(getattr(args, "acStore", ""))
  sync = remote_from_url(args.remoteStore, args.remoteStore, args.architecture,
                         args.workDir, getattr(args, "insecure", False),
                         ac_url=ac_store, ac_write_url=ac_store,
                         storage=getattr(args, "storage", "permanent"))
  dieOnError(not isinstance(sync, REAPIRemoteSync),
             "migrate --populate-system requires a reapi:// remote store")
  commit = getattr(args, "alidist_commit", None) or "HEAD"
  dry_run = getattr(args, "dryRun", False)
  enriched, added = populate_system_deps(sync, args.architecture, args.alidist,
                                         commit, dry_run=dry_run)
  info("System population %sdone: %d entr%s enriched, %d validate-system dep(s) added",
       "(dry-run) " if dry_run else "", enriched, "y" if enriched == 1 else "ies", added)
  return True


def migrate_tarball(sync, tarball_path, alidist_dir, container_override=None,
                    verify=True, snapshot_sources=False, mirror_dir=None,
                    dry_run=False):
  """Migrate a single legacy tarball into the reapi store. Returns the migrated
  package's action hash, or None if it could not be migrated (no provenance,
  recipe could not be recovered, or the self-check failed)."""
  meta = read_meta_json(tarball_path)
  if meta is None:
    warning("%s has no .meta.json (pre-provenance); skipping (not migratable)",
            tarball_path)
    return None
  container = container_for_migration(meta["architecture"], container_override)
  # Only legacy tarballs carry an alidist commit; current builds record it in the AC
  # entry. Checked before the try below, whose handler would otherwise raise a
  # second KeyError while reporting the first.
  alidist_commit = (meta.get("alidist") or {}).get("commit")
  if not alidist_commit:
    warning("%s records no alidist commit; skipping (not a legacy tarball -- "
            "current builds archive the recipe and are already in the ledger)",
            tarball_path)
    return None
  try:
    recipe = recover_recipe(alidist_dir, alidist_commit, meta["package"]["name"])
  except Exception as exc:   # pylint: disable=broad-except
    warning("Could not recover recipe for %s from alidist@%s: %s",
            meta["package"]["name"], alidist_commit, exc)
    return None
  if verify:
    ok, reason = verify_recovered_recipe(meta, recipe)
    if not ok:
      warning("Self-check failed for %s, skipping: %s",
              meta["package"]["name"], reason)
      return None
  pkg = meta["package"]
  if dry_run:
    recursive = meta.get("dependencies", {}).get("recursive", {})
    info("[dry-run] would migrate %s %s-%s (action %s): %d build deps, %d runtime "
         "deps%s", pkg["name"], pkg["version"], pkg["revision"], pkg["hash"],
         len(recursive.get("build", [])), len(recursive.get("runtime", [])),
         "; would snapshot source" if snapshot_sources else "")
    return pkg["hash"]

  source_artifact = refs_artifact = commit_hash = None
  if snapshot_sources:
    source_artifact, refs_artifact, commit_hash = \
      snapshot_legacy_source(sync, meta, mirror_dir)
  entry = ac_entry_from_meta(meta, recipe, container, source_artifact,
                             refs_artifact, commit_hash)
  sync.migrate_put(entry, tarball_path, recipe)
  return entry["action"]["actionHash"]


def strip_rw(url):
  """Drop the ::rw suffix a store URL may carry.

  finaliseArgs() normalises ::rw only for `build` and `doctor`, so every other
  subcommand sees the suffix verbatim -- and boto3 then rejects
  "alibuild-cas::rw" as a bucket name before a single request goes out. Since a
  working `--remote-store` is exactly what people copy from a build invocation
  into a migrate one, accept the suffix rather than fail on it.

  Dropping it loses nothing here: doMigrate passes its remote store as BOTH the
  read and the write URL, so migrate writes whether or not the marker is present.
  """
  url = (url or "").rstrip()
  return url[:-len("::rw")] if url.endswith("::rw") else url


def doMigrate(args, parser):
  # Both stores, once, before any branch below builds a sync from them.
  args.remoteStore = strip_rw(getattr(args, "remoteStore", ""))
  if hasattr(args, "acStore"):
    args.acStore = strip_rw(args.acStore)

  # `migrate --snapshot-sources` with nothing to migrate = recover sources by
  # walking the Action Cache ledger: every migrated entry with an upstream source
  # but no snapshot is cloned from upstream and archived. Idempotent, and needs no
  # old store/closure, so it works even after the old store pruned the release.
  if getattr(args, "populate_system", False):
    return doPopulateSystem(args)
  match = getattr(args, "match", None)
  if getattr(args, "snapshot_sources", False) and not args.tarballs and not match:
    return doEnrichSources(args)
  dry_run = getattr(args, "dryRun", False)
  read_url = getattr(args, "read_store", None)
  if read_url:
    dieOnError(not read_url.startswith("http"),
               "--read-store must be a read-only http(s) URL, got %r" % read_url)

  # --match enumerates the old store's arch and adds every spec matching REGEX to
  # the work list (so a whole arch, or a regex subset, can be migrated without
  # naming each package). Composes with any explicit TARBALLs and with --closure.
  if match:
    dieOnError(not read_url, "--match needs --read-store to enumerate the old store")
    matched = enumerate_arch(read_url, args.architecture, match)
    info("--match %r selects %d package(s) for %s", match, len(matched), args.architecture)
    args.tarballs = sorted(set(list(args.tarballs) + matched))

  dieOnError(not args.tarballs, "no tarballs given to migrate")
  dieOnError(not args.alidist, "--alidist DIR is required to migrate tarballs")

  # A dry-run only reads the old store and prints; it needs neither credentials
  # nor an S3 client, so don't construct (or require) the reapi write store.
  if dry_run:
    dieOnError(not args.remoteStore.startswith("reapi://"),
               "'aliBuild migrate' requires a reapi:// remote store, but got %r" %
               (args.remoteStore or "(none)"))
    sync = None
  else:
    ac_store = strip_rw(getattr(args, "acStore", ""))
    sync = remote_from_url(args.remoteStore, args.remoteStore, args.architecture,
                           args.workDir, getattr(args, "insecure", False),
                           ac_url=ac_store, ac_write_url=ac_store,
                           storage=getattr(args, "storage", "ephemeral"))
    dieOnError(not isinstance(sync, REAPIRemoteSync),
               "'aliBuild migrate' requires a reapi:// remote store, but got %r" %
               (args.remoteStore or "(none)"))

  verify = not getattr(args, "no_verify", False)
  snapshot_sources = getattr(args, "snapshot_sources", False)
  allow_no_provenance = getattr(args, "allow_no_provenance", False)
  mirror_dir = args.source_mirror or os.path.join(args.workDir, "MIRROR-migrate")

  items = args.tarballs
  if getattr(args, "closure", False):
    dieOnError(not read_url, "--closure needs --read-store to enumerate the closure")
    # When --match drove the list, every spec is a real enumerated tarball, so a
    # missing dist tree (dependency-only/prefer_system package) is not an error --
    # migrate it alone. An explicit --closure PKG stays strict (empty dist = typo).
    strict_closure = not bool(match)
    seen, items = set(), []
    for top in args.tarballs:
      for spec in enumerate_closure(read_url, args.architecture, top, strict=strict_closure):
        if spec not in seen:
          seen.add(spec)
          items.append(spec)
    info("Closure of %s expands to %d package(s)", ", ".join(args.tarballs), len(items))

  download_dir = tempfile.mkdtemp(prefix="alibuild-migrate-") \
    if read_url and not dry_run else None
  total = len(items)
  jobs = max(1, getattr(args, "jobs", 1) or 1)

  def process(idx, item):
    """Migrate one package; returns 'migrated' | 'skipped' | 'present'. Runs
    concurrently under a thread pool (I/O-bound; the boto3 client is thread-safe)."""
    if read_url and dry_run:
      pkg, _, verrev = item.partition("/")
      info("[dry-run] would fetch %s/TARS/%s/%s/%s-%s.%s.tar.gz and migrate",
           read_url.rstrip("/"), args.architecture, pkg, pkg, verrev, args.architecture)
      return "migrated"
    # Skip fully-migrated packages without downloading the (large) tarball: the
    # per-package link is the last object migrate_put writes, so its presence in
    # the artifact store means the entry is complete (idempotent/resumable even
    # if a previous run was interrupted mid-write).
    if read_url and sync is not None:
      pkg, _, verrev = item.partition("/")
      tarball_name = "%s-%s.%s.tar.gz" % (pkg, verrev, args.architecture)
      if sync.is_fully_migrated(args.architecture, pkg, tarball_name, verrev):
        # Already migrated. If sources are being archived, enrich the existing
        # AC entry in place (clone upstream -> snapshot -> rewrite entry) without
        # re-downloading the tarball; otherwise there is nothing left to do.
        if snapshot_sources and not dry_run:
          version, _, revision = verrev.rpartition("-")
          result = enrich_source_snapshot(sync, pkg, version, revision, mirror_dir)
          info("[%d/%d] %s already migrated; source snapshot: %s",
               idx, total, item, result)
          return result
        info("[%d/%d] %s already present, skipping", idx, total, item)
        return "present"
    info("[%d/%d] Migrating %s", idx, total, item)
    tarball = item
    try:
      if read_url:
        tarball = download_from_old_store(read_url, args.architecture, item, download_dir)
      # Pre-provenance tarball (no .meta.json)? With --allow-no-provenance, reserve
      # its version-revision via a legacy store write (no recipe/AC) instead of
      # skipping, so a later fresh build won't shadow it.
      if allow_no_provenance and read_meta_json(tarball) is None:
        pkg, _, verrev = item.partition("/")
        version, _, revision = verrev.rpartition("-")
        if not dry_run:
          sync.put_legacy_artifact(pkg, version, revision, tarball)
        info("[%d/%d] Reserved %s (legacy, no provenance -- not reconstructable)",
             idx, total, item)
        return "migrated"
      ok = migrate_tarball(sync, tarball, args.alidist, args.container, verify=verify,
                           snapshot_sources=snapshot_sources, mirror_dir=mirror_dir,
                           dry_run=dry_run)
      return "migrated" if ok else "skipped"
    except Exception as exc:   # pylint: disable=broad-except
      warning("Could not migrate %s: %s", item, exc)
      return "skipped"
    finally:
      # Delete each downloaded tarball as we go, so the closure doesn't pile up.
      if read_url and not dry_run and tarball != item and os.path.exists(tarball):
        os.unlink(tarball)

  try:
    if jobs > 1 and not dry_run:
      info("Migrating with %d parallel jobs", jobs)
      with ThreadPoolExecutor(max_workers=jobs) as pool:
        results = list(pool.map(lambda pair: process(*pair), enumerate(items, 1)))
    else:
      results = [process(idx, item) for idx, item in enumerate(items, 1)]
  finally:
    if download_dir:
      shutil.rmtree(download_dir, ignore_errors=True)

  # Second pass: recover the dependency graph of legacy (pre-provenance) entries
  # from the old store's dist tree and hash-link it into their AC entries, so they
  # form a connected, walkable graph instead of isolated nodes. Needs the old store
  # (dist tree) and the new store (to resolve dep hashes); skipped on dry runs.
  if allow_no_provenance and read_url and not dry_run:
    enriched = recover_legacy_deps(read_url, args.architecture, items, sync)
    if enriched:
      info("Recovered the dependency graph for %d legacy package(s) from the dist tree",
           enriched)

  # Standard pass: give the just-migrated entries their validate-system nodes (make,
  # yacc-like, ...) recovered from alidist, so reconstruct is self-contained for
  # system deps -- exactly what a fresh build does. Not opt-in; skipped on dry runs
  # (no ledger to read) and when there is no alidist to recover system recipes from.
  if sync is not None and not dry_run and args.alidist:
    commit = getattr(args, "alidist_commit", None) or "HEAD"
    _, added = populate_system_deps(sync, args.architecture, args.alidist, commit,
                                    items=items)
    if added:
      info("Added %d validate-system dependency node(s) recovered from alidist", added)

  migrated = results.count("migrated")
  skipped = results.count("skipped")
  present = results.count("present")
  info("Migration %sdone: %d migrated, %d skipped, %d already present",
       "(dry-run) " if dry_run else "", migrated, skipped, present)
  return skipped == 0
