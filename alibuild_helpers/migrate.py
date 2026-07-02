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
from concurrent.futures import ThreadPoolExecutor

import requests

from alibuild_helpers.git import git, Git
from alibuild_helpers.log import info, debug, warning, dieOnError
from alibuild_helpers.sync import remote_from_url, REAPIRemoteSync
from alibuild_helpers.source import GitSourceStore, store_refs
from alibuild_helpers.utilities import default_builder_image, parseRecipe


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


def peek_old_store_action_hash(read_url, architecture, spec):
  """Return the action hash of `spec` from its old-store symlink pointer, without
  downloading the tarball -- used to skip already-migrated packages. None if it
  cannot be resolved."""
  pkg, _, verrev = spec.partition("/")
  tarball = "%s-%s.%s.tar.gz" % (pkg, verrev, architecture)
  link_url = "%s/TARS/%s/%s/%s" % (read_url.rstrip("/"), architecture, pkg, tarball)
  debug("HTTP GET %s (peek action hash)", link_url)
  try:
    link = requests.get(link_url, timeout=60)
    link.raise_for_status()
  except Exception:   # pylint: disable=broad-except
    return None
  match = re.search(r"store/[0-9a-f]{2}/([0-9a-f]+)/", link.text)
  return match.group(1) if match else None


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
  # (connect, read) timeout: a stalled read errors after 120s (turning a hang
  # into a skippable failure) while a slow-but-steady large download is fine.
  with requests.get(store_url, stream=True, timeout=(30, 120)) as resp:
    resp.raise_for_status()
    with open(dest, "wb") as out:
      for chunk in resp.iter_content(1 << 20):
        out.write(chunk)
  return dest


def _list_old_store(read_url, prefix):
  """List keys under prefix in a read-only swift/HTTP old store."""
  url = "%s/?prefix=%s&delimiter=/" % (read_url.rstrip("/"), prefix)
  debug("HTTP GET %s", url)
  resp = requests.get(url, timeout=120)
  resp.raise_for_status()
  return resp.text.split()


def enumerate_closure(read_url, architecture, top_spec):
  """Return the PACKAGE/VERSION-REVISION specs for the full build closure of
  top_spec, read cheaply from the old store's dist tree (no tarball downloads).

  The dist tree lists the closure as <pkg>-<ver>-<rev>.<arch>.tar.gz filenames;
  package names (which may contain dashes) are recovered by matching the longest
  package-directory name that prefixes each filename."""
  pkg, _, verrev = top_spec.partition("/")
  dieOnError(not verrev, "expected PACKAGE/VERSION-REVISION, got %r" % top_spec)
  suffix = ".%s.tar.gz" % architecture
  dist_prefix = "TARS/%s/dist/%s/%s-%s/" % (architecture, pkg, pkg, verrev)
  filenames = sorted({os.path.basename(k) for k in _list_old_store(read_url, dist_prefix)
                      if k.endswith(suffix)})
  dieOnError(not filenames,
             "no dist closure at %s -- is %s right?" % (dist_prefix, top_spec))

  pkg_prefix = "TARS/%s/" % architecture
  names = sorted({k[len(pkg_prefix):].rstrip("/") for k in _list_old_store(read_url, pkg_prefix)
                  if k.startswith(pkg_prefix) and k.endswith("/")}, key=len, reverse=True)
  specs = []
  for fname in filenames:
    base = fname[:-len(suffix)]               # <pkg>-<ver>-<rev>
    match = next((n for n in names if base.startswith(n + "-")), None)
    dieOnError(not match, "could not map %s to a package directory" % fname)
    specs.append("%s/%s" % (match, base[len(match) + 1:]))
  # The dist tree includes the top package itself, but guard just in case.
  if top_spec not in specs:
    specs.append(top_spec)
  return specs


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


def snapshot_legacy_source(sync, meta, mirror_dir):
  """Capture a legacy release's git source into the CAS at migrate time (while
  upstream is presumably still alive), so the release becomes offline-
  reconstructible. Clones the source into mirror_dir (reused per package across
  releases), resolves the tag to a commit, and snapshots source + refs. Returns
  (source_artifact, refs_artifact, commit_hash), all None on any failure (source
  archival is best-effort and must not abort a migration)."""
  source = meta["package"].get("source")
  if not source:
    return None, None, None
  try:
    repo = os.path.join(mirror_dir, meta["package"]["name"].lower())
    if not os.path.isdir(repo):
      os.makedirs(mirror_dir, exist_ok=True)
      git(("clone", "--quiet", source, repo), directory=mirror_dir)
    commit = git(("rev-parse", meta["package"]["tag"] + "^{commit}"),
                 directory=repo).strip()
    source_artifact = GitSourceStore(sync).snapshot(repo, source, commit)
    scm_refs = Git().parseRefs(git(Git().listRefsCmd(repo), directory=repo))
    refs_artifact = store_refs(sync, source, scm_refs)
    return source_artifact, refs_artifact, commit
  except Exception as exc:   # pylint: disable=broad-except
    warning("Could not snapshot source for %s from %s (it will not be offline-"
            "reconstructible): %s", meta["package"]["name"], source, exc)
    return None, None, None


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
  try:
    recipe = recover_recipe(alidist_dir, meta["alidist"]["commit"], meta["package"]["name"])
  except Exception as exc:   # pylint: disable=broad-except
    warning("Could not recover recipe for %s from alidist@%s: %s",
            meta["package"]["name"], meta["alidist"]["commit"], exc)
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


def doMigrate(args, parser):
  dieOnError(not args.tarballs, "no tarballs given to migrate")
  dry_run = getattr(args, "dryRun", False)
  read_url = getattr(args, "read_store", None)
  if read_url:
    dieOnError(not read_url.startswith("http"),
               "--read-store must be a read-only http(s) URL, got %r" % read_url)

  # A dry-run only reads the old store and prints; it needs neither credentials
  # nor an S3 client, so don't construct (or require) the reapi write store.
  if dry_run:
    dieOnError(not args.remoteStore.startswith("reapi://"),
               "'aliBuild migrate' requires a reapi:// remote store, but got %r" %
               (args.remoteStore or "(none)"))
    sync = None
  else:
    ac_store = (getattr(args, "acStore", "") or "").rstrip()
    if ac_store.endswith("::rw"):
      ac_store = ac_store[:-4]
    sync = remote_from_url(args.remoteStore, args.remoteStore, args.architecture,
                           args.workDir, getattr(args, "insecure", False),
                           ac_url=ac_store, ac_write_url=ac_store,
                           storage=getattr(args, "storage", "ephemeral"))
    dieOnError(not isinstance(sync, REAPIRemoteSync),
               "'aliBuild migrate' requires a reapi:// remote store, but got %r" %
               (args.remoteStore or "(none)"))

  verify = not getattr(args, "no_verify", False)
  snapshot_sources = getattr(args, "snapshot_sources", False)
  mirror_dir = args.source_mirror or os.path.join(args.workDir, "MIRROR-migrate")

  items = args.tarballs
  if getattr(args, "closure", False):
    dieOnError(not read_url, "--closure needs --read-store to enumerate the closure")
    seen, items = set(), []
    for top in args.tarballs:
      for spec in enumerate_closure(read_url, args.architecture, top):
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
    # Skip packages already migrated, without downloading the (large) tarball:
    # resolve the action hash from the old-store symlink and check the ledger.
    if read_url and sync is not None:
      action_hash = peek_old_store_action_hash(read_url, args.architecture, item)
      if action_hash and sync.read_ac_entry(action_hash) is not None:
        info("[%d/%d] %s already present, skipping", idx, total, item)
        return "present"
    info("[%d/%d] Migrating %s", idx, total, item)
    tarball = item
    try:
      if read_url:
        tarball = download_from_old_store(read_url, args.architecture, item, download_dir)
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

  migrated = results.count("migrated")
  skipped = results.count("skipped")
  present = results.count("present")
  info("Migration %sdone: %d migrated, %d skipped, %d already present",
       "(dry-run) " if dry_run else "", migrated, skipped, present)
  return skipped == 0
