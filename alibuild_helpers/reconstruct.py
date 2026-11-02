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

import glob
import hashlib
import os
import re
import os.path
import shutil
import subprocess
import sys

from alibuild_helpers.log import (info, debug, warning, error, dieOnError,
                                  banner, success)
from alibuild_helpers.sync import remote_from_url
from alibuild_helpers.sync_reapi import REAPIRemoteSync, add_reapi_store_args, signature_checker
from alibuild_helpers.source import GitSourceStore, load_refs, apply_refs
from alibuild_helpers.utilities import file_digest


def add_parser(subparsers, detected_arch, work_dir_default):
  """Register the `reconstruct` subcommand's parser -- its (many) options live with
  the command, keeping them out of the shared top-level argument parser."""
  p = subparsers.add_parser(
    "reconstruct", help="reconstruct missing CAS tarballs from the Action Cache",
    description="Walk the build closure of a package in a reapi:// Action Cache, "
                "find tarballs missing from the CAS, and materialise the archived "
                "recipes so they can be rebuilt and the CAS repopulated.")
  p.add_argument("package", metavar="PACKAGE", help="Package to reconstruct.")
  p.add_argument("--version", required=True, metavar="VERSION",
                 help="Version of the package to reconstruct.")
  p.add_argument("--revision", default=None, metavar="REVISION",
                 help="Revision to reconstruct. Defaults to the highest available for the version.")
  add_reapi_store_args(
    p, remote_help="reapi:// store to reconstruct from / into.",
    arch_help="Architecture to reconstruct for. Default '%(default)s'.",
    detected_arch=detected_arch, work_dir_default=work_dir_default)
  p.add_argument("--output-config", dest="outputConfig", default=None, metavar="DIR",
                 help="Where to materialise the recipes. Defaults to WORKDIR/reconstruct-PACKAGE.")
  p.add_argument("--verify", dest="verify", action="store_true",
                 help="Read-only: report the reconstruction plan for the package's closure "
                      "(which tarballs would be reused from the CAS vs rebuilt) and check the "
                      "ledger is complete (recipe integrity, dependency DAG, archived sources). "
                      "Rebuilds nothing.")
  p.add_argument("--rebuild", dest="rebuild", action="store_true",
                 help="With --verify: actually rebuild just the target package (reusing all "
                      "dependencies from the CAS, no upload) and compare the produced tarball's "
                      "content hash to the recorded outputDigest. A match proves the blob is "
                      "byte-for-byte regenerable.")
  p.add_argument("--strict", dest="strict", action="store_true",
                 help="With --verify --rebuild: treat a non-identical rebuilt tarball as a failure "
                      "(default: soft, since legacy pre-normalisation tarballs are not "
                      "bit-reproducible).")
  p.add_argument("--alidist", dest="alidist", default=None, metavar="DIR",
                 help="alidist checkout used to supply the defaults config file "
                      "(defaults-<name>.sh) when it is not archived in the ledger (it is a config, "
                      "not a package in the closure). Needed to rebuild releases built with a "
                      "non-'release' defaults, e.g. 'o2'.")
  p.add_argument("--rebaseline", dest="rebaseline", action="store_true",
                 help="Rebuild the target (implies --verify --rebuild) and, if its reproducible "
                      "hash differs from the recorded legacy one, rewrite the AC entry's "
                      "outputDigest (and store redirect) to the rebuilt hash so future verifies "
                      "are byte-identical. A DRY RUN unless --apply is given.")
  p.add_argument("--apply", dest="apply", action="store_true",
                 help="With --rebaseline: actually perform the ledger + CAS writes (default is a "
                      "dry run that only prints the plan).")
  p.add_argument("--delete-old", dest="delete_old", action="store_true",
                 help="With --rebaseline --apply: also delete the CAS blob orphaned by the "
                      "re-baseline (default: leave it in place).")
  p.add_argument("--persist", dest="persist", action="store_true",
                 help="Rebuild the target (implies --verify --rebuild) and, if it reproduces the "
                      "recorded output digest, upload just that CAS blob back -- a content-"
                      "addressed restore. Unlike an 'aliBuild build ::rw', it writes ONLY the "
                      "blob: no revision assignment, no dist/publisher symlinks, no AC rewrite "
                      "(the AC entry, redirect and links already point at it). A DRY RUN unless "
                      "--apply is given.")
  p.add_argument("--storage", dest="storage", default="permanent",
                 choices=("ephemeral", "permanent"),
                 help="Retention tag for a blob restored by --persist. Default '%(default)s' (a "
                      "deliberately reconstructed blob should not be LRU-expired).")
  return p


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
  """Return the subset of entries whose output tarball is missing from the CAS.
  validate-system entries produce no tarball, so they are never 'missing' -- the
  rebuild re-validates them on the host instead."""
  missing = []
  for entry in entries:
    # validate-system produces no tarball; legacy artifacts have no recipe, so a
    # lost one cannot be rebuilt -- neither is a rebuild candidate.
    if entry["action"].get("kind") in ("validate-system", "legacy"):
      continue
    parts = _digest_parts(entry)
    dieOnError(parts is None, "Action Cache entry for %s has no output digest" %
               entry["action"]["package"])
    algo, content_hash = parts
    if not sync.artifact_blob_exists(content_hash, algo):
      missing.append(entry)
  return missing


def recipe_package_name(recipe):
  """The package name a recipe declares in its own header, or "" if none.

  Usually this is the AC entry's package, but not for defaults: alibuild injects
  every defaults flavour under the single node name ``defaults-release`` while the
  recipe itself still declares the flavour actually used (``defaults-o2``, ...).
  That is by design -- it is how defaults are selected without a code change --
  so the ledger is consistent; only a reconstruct that writes the recipe out under
  the *node* name gets it wrong, since alibuild then rejects the file for
  disagreeing with its own package field.
  """
  for line in recipe.decode("utf-8", "replace").splitlines():
    if line.startswith("---"):        # end of the YAML header
      break
    match = re.match(r"package:\s*(\S+)", line)
    if match:
      return match.group(1)
  return ""


def defaults_from_closure(sync, entries):
  """Recover the ``--defaults`` flavour a build actually used, or "".

  ``action.defaults`` is absent from older (migrated) entries, and the node name
  is always ``defaults-release`` whatever the flavour, so the only honest source
  is the recipe archived for that node: ``defaults-o2`` means ``--defaults o2``.
  Guessing "release" instead makes the rebuild read a defaults file that declares
  a different package and fail.
  """
  for entry in entries:
    action = entry["action"]
    if not action.get("package", "").startswith("defaults-"):
      continue
    digest = action.get("recipeDigest", "")
    if ":" not in digest:
      continue
    algo, _, recipe_hash = digest.partition(":")
    declared = recipe_package_name(sync.read_blob(recipe_hash, algo))
    if declared.startswith("defaults-"):
      return declared[len("defaults-"):]
  return ""


def materialize_recipes(sync, entries, config_dir):
  """Write the archived recipe of every entry into config_dir as <pkg>.sh, so
  the closure can be rebuilt as a self-contained alidist. Returns the written
  paths.

  The file is named after the package the recipe *declares*, not the AC entry's
  package name; see :func:`recipe_package_name` for why those differ for defaults.
  """
  os.makedirs(config_dir, exist_ok=True)
  written = []
  for entry in entries:
    action = entry["action"]
    digest = action.get("recipeDigest", "")
    dieOnError(":" not in digest, "Action Cache entry for %s has no recipe digest "
               "(was it written before recipes were archived?)" % action["package"])
    algo, _, recipe_hash = digest.partition(":")
    recipe = sync.read_blob(recipe_hash, algo)
    declared = recipe_package_name(recipe) or action["package"]
    path = os.path.join(config_dir, declared.lower() + ".sh")
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


def _recipe_intact(sync, action):
  """Whether an action's recipe blob is present in the ledger and matches its
  recorded digest (sha256 == recipeDigest)."""
  algo, _, recipe_hash = action.get("recipeDigest", "").partition(":")
  if not recipe_hash:
    return False
  try:
    return hashlib.new(algo, sync.read_blob(recipe_hash, algo)).hexdigest() == recipe_hash
  except Exception:   # pylint: disable=broad-except
    return False


def verify_closure(sync, closure):
  """Read-only reconstruction check for a build closure. For every package it
  determines whether its tarball would be *reused* from the CAS (blob present) or
  *rebuilt* (blob missing), and whether the ledger can actually rebuild it: recipe
  blob present and integrity-verified (sha256 == recipeDigest), dependency DAG
  intact, and source either archived (offline) or upstream-only. Returns
  (rows, ok) where ok means every would-rebuild package is regenerable."""
  by_hash = {e["action"]["actionHash"] for e in closure}
  rows, ok = [], True
  for entry in closure:
    action = entry["action"]
    # System / prefer_system packages produce no tarball: they are re-validated
    # on the host at rebuild, not reused or rebuilt. Report and move on.
    if action.get("kind") == "validate-system":
      recipe_ok = _recipe_intact(sync, action)
      if not recipe_ok:
        ok = False
      rows.append({
        "package": action["package"], "version": action.get("version"),
        "revision": action.get("revision"), "action": "system",
        "recipe_ok": recipe_ok, "deps_ok": True, "source": "n/a",
        "regenerable": recipe_ok, "rebuildable": recipe_ok,
      })
      continue
    # Legacy (pre-provenance) artifact: preserved and installable, but has no
    # recipe, so it can never be rebuilt -- only reused while its blob survives.
    if action.get("kind") == "legacy":
      parts = _digest_parts(entry)
      present = bool(parts) and sync.artifact_blob_exists(parts[1], parts[0])
      if not present:
        ok = False   # a lost legacy blob is gone for good (nothing to rebuild from)
      rows.append({
        "package": action["package"], "version": action.get("version"),
        "revision": action.get("revision"), "action": "legacy",
        "recipe_ok": False, "deps_ok": True, "source": "n/a",
        # `regenerable` means "satisfiable right now" (the blob is there);
        # `rebuildable` means "could be regenerated if the blob were lost", which
        # for a legacy entry is never, since it has no recipe.
        "regenerable": present, "rebuildable": False,
      })
      continue
    # Would this tarball be reused (present) or rebuilt (missing)?
    parts = _digest_parts(entry)
    present = bool(parts) and sync.artifact_blob_exists(parts[1], parts[0])
    # Recipe blob present and matching its recorded digest?
    recipe_ok = _recipe_intact(sync, action)
    deps_ok = all(dep["actionHash"] in by_hash for dep in action.get("deps", []))
    has_snapshot = bool(action.get("sourceArtifact"))
    has_upstream = bool(action.get("source"))
    # A package we would have to rebuild must be regenerable: its recipe must be
    # intact, its deps consistent, and its source obtainable (archived, upstream,
    # or none needed). Reused (present) packages don't need to be rebuildable now.
    regenerable = recipe_ok and deps_ok and (has_snapshot or has_upstream or
                                             not action.get("source"))
    if not present and not regenerable:
      ok = False
    rows.append({
      "package": action["package"],
      "version": action.get("version"), "revision": action.get("revision"),
      "action": "reuse" if present else "rebuild",
      "recipe_ok": recipe_ok, "deps_ok": deps_ok,
      "source": "archived" if has_snapshot else ("upstream" if has_upstream else "none"),
      "regenerable": regenerable, "rebuildable": regenerable,
    })
  return rows, ok


def ensure_defaults_recipe(config_dir, defaults_name, alidist_dir=None):
  """Make sure the defaults *config* file the build needs (defaults-<name>.sh) is
  present in the materialised alidist. `defaults-release` is usually already there
  as a package recipe, but other defaults (e.g. `o2`) are a config file, not a
  package in the AC closure, so they are not materialised -- copy them from a
  provided --alidist checkout. Returns True if the file is present/available.

  (A future step archives the defaults recipe as a reconstruction input so this
  needs no checkout; until then, and for already-migrated releases, --alidist is
  the bridge.)"""
  if not defaults_name:
    return True
  target = os.path.join(config_dir, "defaults-%s.sh" % defaults_name)
  if os.path.exists(target):
    return True
  if alidist_dir:
    src = os.path.join(alidist_dir, "defaults-%s.sh" % defaults_name)
    if os.path.exists(src):
      shutil.copyfile(src, target)
      debug("Materialised defaults-%s.sh from %s", defaults_name, alidist_dir)
      return True
    warning("defaults-%s.sh not found under --alidist %s", defaults_name, alidist_dir)
  else:
    warning("defaults-%s.sh is a config file (not a package in the closure) and is "
            "not archived; pass --alidist <checkout> so reconstruct can supply it.",
            defaults_name)
  return False


def supply_recipes_from_alidist(config_dir, alidist_dir):
  """Copy every recipe (and defaults) from an alidist checkout into the
  materialised config that isn't already there, so the rebuild's dependency
  resolution finds the *full* recipe closure -- including system/prefer_system
  packages, which have recipes (with their system-requirement checks) but no
  tarballs, so they are absent from the Action Cache.

  Archived recipes already materialised for built packages are kept (never
  overwritten), so their content -- and therefore their action hashes -- stays
  faithful; only the missing ones come from the checkout. Returns the count
  copied.

  (Bridge until the full recipe closure is archived as a reconstruction input;
  see the reconstruct notes in REMOTE_STORE_CAS_AC.md.)"""
  copied = 0
  for src in glob.glob(os.path.join(alidist_dir, "*.sh")):
    dest = os.path.join(config_dir, os.path.basename(src))
    if not os.path.exists(dest):
      shutil.copyfile(src, dest)
      copied += 1
  info("Supplied %d additional recipe(s) from %s to complete the closure "
       "(system/prefer_system packages, defaults, transitive requires)",
       copied, alidist_dir)
  return copied


def _prepare_config_recipes(config_dir, defaults_name, alidist_dir):
  """Complete the materialised config so the rebuild's dependency resolution finds
  every recipe -- including system/prefer_system packages and the defaults config,
  which are not in the Action Cache. With --alidist, supply the whole closure from
  it; otherwise fall back to the defaults-only check (and warn)."""
  if alidist_dir:
    supply_recipes_from_alidist(config_dir, alidist_dir)
  else:
    ensure_defaults_recipe(config_dir, defaults_name, None)


def _rebuilt_tarball(work_dir, architecture, package):
  """Return the tarball a rebuild produced for `package` under work_dir's TARS
  tree, or None. A force-rebuilt package lands under a fresh action-hash
  directory, so glob across hashes and match by package name."""
  pattern = os.path.join(work_dir, "TARS", architecture, "store", "*", "*",
                         "%s-*.%s.tar.gz" % (package, architecture))
  matches = sorted(glob.glob(pattern))
  return matches[-1] if matches else None


def _rebuild_verdict(recorded_hash, rebuilt_hash, strict):
  """Interpret a rebuild's content hash vs the recorded one. Returns (ok, kind).
  A differing hash means the rebuild works but isn't byte-identical -- expected
  for pre-normalisation legacy tarballs, so it is soft unless --strict."""
  if rebuilt_hash == recorded_hash:
    return True, "match"
  return (not strict), "differ"


class RebuildResult:
  """Outcome of verify_rebuild. Truthy iff the rebuild passed its verdict, so it
  drops into `and`/assertTrue like the bool it replaced, while also carrying the
  produced tarball and hashes so a re-baseline can consume them."""
  def __init__(self, ok, kind=None, algo=None, recorded=None, rebuilt=None,
               tarball=None):
    self.ok, self.kind, self.algo = ok, kind, algo
    self.recorded, self.rebuilt, self.tarball = recorded, rebuilt, tarball

  def __bool__(self):
    return self.ok


def verify_rebuild(args, sync, closure, build_runner=None):
  """Rebuild just the target package -- reusing every dependency from the CAS --
  and compare the produced tarball's content hash to the recorded outputDigest.
  Proves the ledger regenerates the actual bytes, not merely that the inputs are
  present. Builds into an isolated workdir and never uploads to the real store."""
  entry = closure[-1]
  parts = _digest_parts(entry)
  dieOnError(not parts, "the target has no recorded output digest to compare against")
  algo, recorded_hash = parts

  # Materialise recipes + restore the target's source, exactly as a reconstruct.
  config_dir = os.path.abspath(getattr(args, "outputConfig", None) or
                               os.path.join(args.workDir, "reconstruct-" + args.package))
  materialize_recipes(sync, closure, config_dir)
  _prepare_config_recipes(config_dir, entry["action"].get("defaults"),
                          getattr(args, "alidist", None))
  reference_dir = os.path.join(config_dir, "sources")
  restore_sources(sync, [entry], reference_dir)

  build_dir = os.path.join(args.workDir, "verify-rebuild-" + args.package)
  try:
    # Pre-populate SOURCES so the rebuild checks out locally without upstream.
    GitSourceStore(sync).restore_to_source_dir(entry, build_dir)
  except Exception as exc:   # pylint: disable=broad-except
    debug("Could not pre-populate SOURCES for %s: %s", args.package, exc)

  ac_store = (getattr(args, "acStore", "") or "").rstrip()
  if ac_store.endswith("::rw"):
    ac_store = ac_store[:-4]
  container = entry["action"].get("container") or {}
  image = container.get("digest") or container.get("image")
  # Rebuild with the defaults this build actually used (they feed the action
  # hash), not a hardcoded guess: prefer the recorded field, else recover the
  # flavour from the archived defaults recipe (migrated entries lack the field).
  defaults = (entry["action"].get("defaults")
              or defaults_from_closure(sync, closure) or "release")

  # Read-only remote store (no ::rw) => dependencies are fetched and reused,
  # nothing is uploaded. --force-rebuild only the target, so only it is
  # recompiled; its action hash changes but that does not affect the *content*
  # we compare against the recorded output digest. Propagate -d so the rebuild
  # streams a debug build log when reconstruct is run with --debug (-d is a
  # global flag, so it must precede the "build" subcommand).
  # Re-invoke through the *same interpreter*, not just the same script: executing
  # sys.argv[0] directly would fall back to the shebang's `env python3`, i.e. to
  # whatever is on PATH. Running alibuild from a virtualenv that is not on PATH
  # (the documented dev setup) would then rebuild with a different, possibly
  # dependency-less Python and fail with a bare ImportError.
  cmd = [sys.executable, sys.argv[0]]
  if getattr(args, "debug", False):
    cmd.append("-d")
  cmd += ["build", args.package, "-c", config_dir,
          "-a", args.architecture, "-w", build_dir,
          "--remote-store", args.remoteStore,
          # A reconstruct rebuild must be hermetic: a local checkout of any
          # dependency (e.g. alibuild-recipe-tools under the cwd) would otherwise
          # be picked up as a development package -- rebuilt from local sources and,
          # worse, disabling the remote write store for the whole build.
          "--force-tracked",
          "--force-rebuild", args.package, "--defaults", defaults]
  if ac_store:
    cmd += ["--ac-store", ac_store]
  if getattr(args, "insecure", False):
    cmd += ["--insecure"]
  if os.path.isdir(reference_dir):
    cmd += ["--reference-sources", reference_dir]
  if image:
    cmd += ["--docker", "--docker-image", image]

  # The materialised recipes are a plain directory, not an SCM checkout; pass the
  # alidist provenance explicitly so the build doesn't require a git repo (the
  # recipes are already pinned by content). Use the recorded recipe digest.
  alidist_hash = entry["action"].get("recipeDigest", "").split(":")[-1] or "reconstruct"
  build_env = dict(os.environ, ALIBUILD_ALIDIST_HASH=alidist_hash)

  info("Rebuilding %s in isolation (deps reused from the CAS, no upload):\n  %s",
       args.package, " ".join(cmd))
  runner = build_runner or (lambda command: subprocess.call(command, env=build_env))
  returncode = runner(cmd)
  if returncode != 0:
    error("Rebuild of %s failed (exit %d): reconstruction is NOT verified.",
          args.package, returncode)
    return RebuildResult(False)

  tarball = _rebuilt_tarball(build_dir, args.architecture, args.package)
  dieOnError(not tarball, "the rebuild produced no tarball for %s under %s" %
             (args.package, build_dir))
  rebuilt_hash = file_digest(tarball, algo)
  ok, kind = _rebuild_verdict(recorded_hash, rebuilt_hash,
                              getattr(args, "strict", False))
  if kind == "match":
    success("REPRODUCED: %s rebuilt to a byte-identical tarball (%s:%s). Its CAS "
            "blob is fully regenerable from the ledger.", args.package, algo, rebuilt_hash)
  else:
    warning("Rebuilt %s, but the tarball is NOT byte-identical to the recorded one:\n"
            "    recorded: %s:%s\n    rebuilt : %s:%s\n"
            "  Expected when the build is not bit-reproducible -- a pre-normalisation "
            "legacy tarball, or paths/timestamps baked into the artifact. The rebuild "
            "is valid; pass --strict to treat a mismatch as failure.",
            args.package, algo, recorded_hash, algo, rebuilt_hash)
  return RebuildResult(ok, kind=kind, algo=algo, recorded=recorded_hash,
                       rebuilt=rebuilt_hash, tarball=tarball)


def do_rebaseline(args, sync, closure, result):
  """Re-baseline the target's AC entry onto the just-rebuilt tarball: rewrite its
  outputDigest (and store redirect + link) to the reproducible hash so future
  verifies are byte-identical. Only meaningful when the rebuild *differed* from
  the recorded (legacy) hash. Prints the plan; performs it only with --apply. The
  new blob is written before the AC is repointed, so it is never left dangling."""
  if result is None or result.tarball is None:
    error("Cannot re-baseline %s: its rebuild did not produce a tarball.",
          args.package)
    return False
  if result.kind == "match":
    info("Nothing to re-baseline for %s: the rebuild already matches the recorded "
         "digest (%s:%s).", args.package, result.algo, result.recorded)
    return True

  entry = closure[-1]
  action_hash = entry["action"]["actionHash"]
  old_cas = "cas/%s/%s/%s" % (result.algo, result.recorded[:2], result.recorded)
  new_cas = "cas/%s/%s/%s" % (result.algo, result.rebuilt[:2], result.rebuilt)
  info("Re-baseline plan for %s %s (action %s):", args.package, args.version,
       action_hash)
  info("  store new CAS blob   : %s", new_cas)
  info("  rewrite AC outputDigest: %s:%s -> %s:%s", result.algo, result.recorded,
       result.algo, result.rebuilt)
  info("  orphaned old CAS blob: %s%s", old_cas,
       " (will delete)" if getattr(args, "delete_old", False) else " (left in place)")

  if not getattr(args, "apply", False):
    warning("DRY RUN: nothing written. Re-run with --apply to perform the "
            "re-baseline above (a write to the real ledger + CAS).")
    return True

  # Reuse the recipe already in the ledger (dedup skips re-upload); pass it
  # through so a missing blob would still be restored.
  recipe_text = ""
  recipe_digest = entry["action"].get("recipeDigest", "").split(":", 1)[-1]
  if recipe_digest:
    try:
      recipe_text = sync.read_blob(recipe_digest).decode("utf-8", "ignore")
    except Exception as exc:   # pylint: disable=broad-except
      debug("Could not pre-read recipe blob %s: %s", recipe_digest, exc)
  old_hash, new_hash, old_cas_path = sync.rebaseline_ac_entry(
    entry, result.tarball, recipe_text)
  success("Re-baselined %s: AC entry %s now points at %s:%s.", args.package,
          action_hash, result.algo, new_hash)
  if getattr(args, "delete_old", False) and old_hash and old_hash != new_hash:
    sync.delete_artifact_blob(old_hash, result.algo)
    info("Deleted orphaned CAS blob %s", old_cas_path)
  return True


def do_persist(args, sync, closure, result):
  """Content-addressed restore of a regenerated blob. After an isolated rebuild
  that reproduces the recorded output digest, upload ONLY that CAS blob back --
  no revision assignment, no dist/publisher symlinks, no AC rewrite. The AC entry,
  legacy store redirect and per-package links still point at this exact hash (only
  the blob was deleted), so putting the bytes back at their content-addressed key
  is the whole restore. This is the correct reconstruct semantics; an 'aliBuild
  build ::rw' is not (it re-publishes: assigns a fresh revision and writes a new
  dist graph). A DRY RUN unless --apply."""
  if result is None or result.tarball is None:
    error("Cannot persist %s: its rebuild did not produce a tarball.", args.package)
    return False
  if result.kind != "match":
    error("Refusing to persist %s: the rebuild's hash (%s:%s) does not match the "
          "recorded digest (%s:%s) -- a content-addressed restore must reproduce the "
          "recorded blob exactly. Use --rebaseline to adopt the new hash instead.",
          args.package, result.algo, result.rebuilt, result.algo, result.recorded)
    return False

  cas_path = "cas/%s/%s/%s" % (result.algo, result.recorded[:2], result.recorded)
  if sync.artifact_blob_exists(result.recorded, result.algo):
    info("CAS blob %s for %s is already present; nothing to restore.",
         cas_path, args.package)
    return True

  info("Restore plan for %s: upload the regenerated blob -> %s (retention=%s); "
       "no revision, dist symlinks or AC entry are written.", args.package, cas_path,
       getattr(args, "storage", "permanent"))
  if not getattr(args, "apply", False):
    warning("DRY RUN: nothing written. Re-run with --apply to upload the blob.")
    return True

  stored = sync.put_artifact_blob(result.tarball, result.algo)
  dieOnError(stored != result.recorded,
             "restored blob hashed to %s:%s but the recorded digest is %s:%s" %
             (result.algo, stored, result.algo, result.recorded))
  success("Restored CAS blob %s for %s from the ledger (content-addressed; no "
          "publisher metadata touched).", cas_path, args.package)
  return True


def doVerify(args, sync, closure):
  """Print the reconstruction plan + ledger-completeness report for a closure and
  return True if every would-rebuild package is regenerable. With --rebuild, also
  regenerate the target and compare its content hash to the recorded digest."""
  rows, ok = verify_closure(sync, closure)
  reuse = sum(1 for r in rows if r["action"] == "reuse")
  rebuild = [r for r in rows if r["action"] == "rebuild"]
  system = sum(1 for r in rows if r["action"] == "system")
  legacy = sum(1 for r in rows if r["action"] == "legacy")
  info("Reconstruction plan for %s %s (%d packages): %d reused from CAS, %d to "
       "rebuild, %d system (revalidated on host), %d legacy (preserved, not "
       "reconstructable)",
       args.package, args.version, len(rows), reuse, len(rebuild), system, legacy)
  markers = {"reuse": "reuse  ", "rebuild": "REBUILD", "system": "system ",
             "legacy": "legacy "}
  for r in rows:
    flags = "recipe:%s deps:%s source:%s" % (
      "ok" if r["recipe_ok"] else "MISSING",
      "ok" if r["deps_ok"] else "BROKEN", r["source"])
    note = "" if r["regenerable"] else (
      "  <- LOST (no recipe)" if r["action"] == "legacy" else
      ("  <- NOT regenerable" if r["action"] == "rebuild" else ""))
    info("  %s  %-24s %s-%s  [%s]%s", markers.get(r["action"], r["action"]),
         r["package"], r["version"], r["revision"], flags, note)
  # Two separate claims, and conflating them was actively misleading: "nothing
  # needs rebuilding" is about the blobs that happen to be present today, while
  # "this closure is reconstructible" is about whether the ledger could regenerate
  # them if they were lost. A closure of purely legacy entries satisfies the first
  # and fails the second, and used to report SUCCESS -- exactly backwards, since
  # the premise of the ledger is that the artifact store is disposable.
  fragile = [r for r in rows if not r["rebuildable"]]
  fragile_note = "%d of %d package(s) could NOT be regenerated if their blob were " \
                 "lost (%s%s)" % (
                   len(fragile), len(rows),
                   ", ".join(r["package"] for r in fragile[:3]),
                   ", ..." if len(fragile) > 3 else "")
  # validate-system nodes produce no tarball, so they must not be counted as one.
  artifacts = len(rows) - system
  if not rebuild:
    if fragile:
      warning("All %d tarball(s) are present in the CAS, so nothing would be rebuilt "
              "now -- but %s. The artifact store is NOT disposable for this closure.",
              artifacts, fragile_note)
    else:
      success("All %d tarball(s) present in the CAS and the whole closure is "
              "regenerable from the ledger (deps, incl. toolchains, reused as-is).",
              artifacts)
  elif ok:
    if fragile:
      warning("The %d missing tarball(s) would rebuild, but %s.", len(rebuild),
              fragile_note)
    else:
      success("Reconstruction is possible: %d package(s) would rebuild, all regenerable "
              "from the ledger; the other %d are reused from the CAS.", len(rebuild), reuse)
  else:
    warning("Reconstruction INCOMPLETE: some missing tarballs are not regenerable "
            "(see 'NOT regenerable' above).")

  if getattr(args, "rebuild", False):
    result = verify_rebuild(args, sync, closure)
    if getattr(args, "rebaseline", False):
      ok = do_rebaseline(args, sync, closure, result) and ok
    if getattr(args, "persist", False):
      ok = do_persist(args, sync, closure, result) and ok
    ok = bool(result) and ok
  return ok


def doReconstruct(args, parser):
  ac_store = (getattr(args, "acStore", "") or "").rstrip()
  if ac_store.endswith("::rw"):
    ac_store = ac_store[:-4]
  sync = remote_from_url(args.remoteStore, args.remoteStore, args.architecture,
                         args.workDir, getattr(args, "insecure", False),
                         ac_url=ac_store, ac_write_url=ac_store,
                         storage=getattr(args, "storage", "permanent"))
  dieOnError(not isinstance(sync, REAPIRemoteSync),
             "'aliBuild reconstruct' requires a reapi:// remote store, but got %r" %
             (args.remoteStore or "(none)"))

  top_hash = sync.resolve_action_hash(args.package, args.version, args.revision)
  dieOnError(not top_hash, "Could not find %s %s%s in %s" % (
    args.package, args.version,
    "-" + args.revision if args.revision else "", args.remoteStore))

  closure = walk_build_closure(sync, top_hash)

  # Before acting on the closure (reusing or rebuilding from it), verify the
  # Action Cache entries are trusted, so reconstruct never propagates an
  # untrusted recipe/provenance into a fresh CAS blob.
  checker = signature_checker(args)
  if checker:
    checker.check_closure(closure)

  # Re-baselining and persisting both need a rebuild to compare/restore, so they
  # imply --verify --rebuild.
  if getattr(args, "rebaseline", False) or getattr(args, "persist", False):
    args.verify = args.rebuild = True

  if getattr(args, "verify", False):
    return doVerify(args, sync, closure)
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
  _prepare_config_recipes(config_dir, closure[-1]["action"].get("defaults"),
                          getattr(args, "alidist", None))

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

  # Use the defaults recorded for this build (they feed the action hash), and pass
  # the alidist provenance via the environment so the plain materialised recipe
  # directory is accepted without being a git checkout.
  defaults = (closure[-1]["action"].get("defaults")
              or defaults_from_closure(sync, closure) or "release")
  alidist_hash = closure[-1]["action"].get("recipeDigest", "").split(":")[-1] or "reconstruct"
  # Propagate the connection flags this reconstruct was invoked with, so the
  # suggested build actually talks to the same store the same way: --insecure
  # (http, e.g. a local proxy) and a separate writable ledger (--ac-store ::rw),
  # or the regenerated AC entry would be written into the CAS bucket. Point at the
  # binary that was actually invoked, not a bare "aliBuild" that may be a different
  # install lacking the reconstruct-side fixes.
  program = sys.argv[0] or "aliBuild"
  insecure_hint = " --insecure" if getattr(args, "insecure", False) else ""
  ac_hint = " --ac-store %s::rw" % ac_store if ac_store else ""
  banner("To rebuild the missing tarballs and repopulate the CAS, run:\n"
         "  ALIBUILD_ALIDIST_HASH=%s %s build %s --defaults %s -c %s -a %s "
         "-w %s --force-tracked%s%s%s --remote-store %s::rw%s",
         alidist_hash, program, args.package, defaults, config_dir,
         args.architecture, args.workDir, docker_hint, reference_hint,
         insecure_hint, args.remoteStore, ac_hint)
  return True
