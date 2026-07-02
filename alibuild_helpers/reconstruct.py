"""Reconstruct missing CAS blobs from the Action Cache.

`aliBuild reconstruct` walks the build closure of a package in the Action Cache,
finds which content-addressed tarballs are missing from the CAS, and
materialises a self-contained alidist directory (the archived recipes, plus the
recorded source commits and build container) so the packages can be rebuilt and
the CAS repopulated -- even if every tarball was deleted. See
REMOTE_STORE_CAS_AC.md.

The actual rebuild reuses the normal build: once the recipes are materialised,
`aliBuild build ... --remote-store reapi://...::rw` recomputes the same action
hashes, fetches whatever blobs still exist, rebuilds the missing ones and
uploads them (writing fresh CAS blobs and updated AC entries). The DAG is held
together by action hashes, so rebuilt blobs that differ byte-for-byte (when a
build is not bit-reproducible) are fine: their AC outputDigest is simply
rewritten.
"""

import os
import os.path

from alibuild_helpers.log import info, debug, warning, dieOnError, banner
from alibuild_helpers.sync import remote_from_url, REAPIRemoteSync
from alibuild_helpers.source import GitSourceStore, load_refs, apply_refs


def _digest_parts(entry):
  """Return (algo, content_hash) from an AC entry's output digest, or None."""
  digest = (entry.get("result") or {}).get("outputDigest", "")
  if ":" not in digest:
    return None
  algo, _, content_hash = digest.partition(":")
  return algo, content_hash


def walk_build_closure(sync, top_hash):
  """Return the AC entries for top_hash and its full build-dependency closure,
  in post-order (dependencies before the packages that need them)."""
  ordered = []
  visited = set()

  def visit(action_hash):
    if action_hash in visited:
      return
    visited.add(action_hash)
    entry = sync.read_ac_entry(action_hash)
    dieOnError(entry is None, "Missing Action Cache entry for %s" % action_hash)
    for dep in entry["action"].get("deps", []):
      visit(dep["actionHash"])
    ordered.append(entry)

  visit(top_hash)
  return ordered


def find_missing_blobs(sync, entries):
  """Return the subset of entries whose output tarball is missing from the CAS."""
  missing = []
  for entry in entries:
    parts = _digest_parts(entry)
    dieOnError(parts is None, "Action Cache entry for %s has no output digest" %
               entry["action"]["package"])
    algo, content_hash = parts
    if not sync.artifact_blob_exists(content_hash, algo):
      missing.append(entry)
  return missing


def materialize_recipes(sync, entries, config_dir):
  """Write the archived recipe of every entry into config_dir as <pkg>.sh, so
  the closure can be rebuilt as a self-contained alidist. Returns the written
  paths."""
  os.makedirs(config_dir, exist_ok=True)
  written = []
  for entry in entries:
    action = entry["action"]
    digest = action.get("recipeDigest", "")
    dieOnError(":" not in digest, "Action Cache entry for %s has no recipe digest "
               "(was it written before recipes were archived?)" % action["package"])
    algo, _, recipe_hash = digest.partition(":")
    recipe = sync.read_blob(recipe_hash, algo)
    path = os.path.join(config_dir, action["package"].lower() + ".sh")
    with open(path, "wb") as recipef:
      recipef.write(recipe)
    written.append(path)
  return written


def restore_sources(sync, entries, reference_dir):
  """Restore the archived git source of each entry that has one into the
  reference-sources layout (<reference_dir>/<pkg.lower()>), so a rebuild can
  reuse it via --reference-sources. Returns (restored, from_upstream) package
  name lists."""
  store = GitSourceStore(sync)
  restored, from_upstream = [], []
  for entry in entries:
    action = entry["action"]
    artifact = action.get("sourceArtifact")
    if not artifact:
      from_upstream.append(action["package"])
      continue
    dest = os.path.join(reference_dir, action["package"].lower())
    try:
      store.restore(artifact, dest)
      # Recreate the original tag refs from the cached mapping so that a rebuild
      # can resolve tags against this local repo without contacting upstream.
      refs_artifact = action.get("refsArtifact")
      if refs_artifact:
        apply_refs(dest, load_refs(sync, refs_artifact))
      restored.append(action["package"])
    except Exception as exc:   # pylint: disable=broad-except
      warning("Could not restore source for %s from the CAS: %s",
              action["package"], exc)
      from_upstream.append(action["package"])
  return restored, from_upstream


def doReconstruct(args, parser):
  ac_store = (getattr(args, "acStore", "") or "").rstrip()
  if ac_store.endswith("::rw"):
    ac_store = ac_store[:-4]
  sync = remote_from_url(args.remoteStore, args.remoteStore, args.architecture,
                         args.workDir, getattr(args, "insecure", False),
                         ac_url=ac_store, ac_write_url=ac_store)
  dieOnError(not isinstance(sync, REAPIRemoteSync),
             "'aliBuild reconstruct' requires a reapi:// remote store, but got %r" %
             (args.remoteStore or "(none)"))

  top_hash = sync.resolve_action_hash(args.package, args.version, args.revision)
  dieOnError(not top_hash, "Could not find %s %s%s in %s" % (
    args.package, args.version,
    "-" + args.revision if args.revision else "", args.remoteStore))

  closure = walk_build_closure(sync, top_hash)
  missing = find_missing_blobs(sync, closure)
  info("Build closure of %s %s: %d package(s), %d tarball(s) missing from the CAS",
       args.package, args.version, len(closure), len(missing))
  if not missing:
    info("Nothing to reconstruct: all CAS blobs are present.")
    return True

  for entry in missing:
    action = entry["action"]
    info("  missing: %s %s-%s (%s)", action["package"], action["version"],
         action["revision"], action["actionHash"])

  config_dir = os.path.abspath(args.outputConfig or
                               os.path.join(args.workDir, "reconstruct-" + args.package))
  written = materialize_recipes(sync, closure, config_dir)
  info("Materialised %d recipe(s) into %s", len(written), config_dir)

  # Restore archived sources from the CAS so the rebuild doesn't depend on
  # upstream git for the bytes (closing the "tarball lost" gap).
  reference_dir = os.path.join(config_dir, "sources")
  restored, from_upstream = restore_sources(sync, missing, reference_dir)
  info("Restored %d source(s) from the CAS into %s; %d will be fetched from "
       "upstream (no archived source)", len(restored), reference_dir,
       len(from_upstream))
  reference_hint = (" --reference-sources %s" % reference_dir) if restored else ""

  # Pre-populate the build's SOURCES so checkout_sources checks out locally (its
  # isdir branch) without cloning the upstream URL -- the "lost upstream" fix.
  store = GitSourceStore(sync)
  prepopulated = 0
  for entry in missing:
    try:
      if store.restore_to_source_dir(entry, args.workDir):
        prepopulated += 1
    except Exception as exc:   # pylint: disable=broad-except
      warning("Could not pre-populate build source for %s: %s",
              entry["action"]["package"], exc)
  if prepopulated:
    info("Pre-populated %d build source(s) under %s/SOURCES for an offline "
         "rebuild", prepopulated, args.workDir)

  # Surface the recorded build container so the user can pin the environment.
  container = closure[-1]["action"].get("container")
  docker_hint = ""
  if container and container.get("image"):
    image = container.get("digest") or container["image"]
    docker_hint = " --docker --docker-image %s" % image
    info("Recorded build container: %s (digest %s)", container["image"],
         container.get("digest") or "unknown")

  banner("To rebuild the missing tarballs and repopulate the CAS, run:\n"
         "  aliBuild build %s --defaults release -c %s -a %s -w %s%s%s "
         "--remote-store %s::rw",
         args.package, config_dir, args.architecture, args.workDir, docker_hint,
         reference_hint, args.remoteStore)
  return True
