"""Recipe-free installation of prebuilt packages from a reapi:// store.

`aliBuild install` materialises a package and its runtime closure straight from
the Action Cache + CAS, without alidist, a git checkout or a toolchain. It is
the consumer dual of a build: where a build produces a tarball, install fetches
the tarball bytes from the CAS and relocates them into a prefix. See
REMOTE_STORE_CAS_AC.md.
"""

import os
import os.path
import tarfile
from shlex import quote

from alibuild_helpers.cmd import execute
from alibuild_helpers.log import info, debug, dieOnError
from alibuild_helpers.sync import remote_from_url, REAPIRemoteSync
from alibuild_helpers.utilities import symlink


def collect_runtime_closure(sync, top_hash):
  """Return the list of Action Cache entries to install: the requested package
  first, followed by its runtime dependency closure.

  The AC entry's runtimeDeps is the already-flattened runtime closure (it is
  built from full_runtime_requires), so a single pass over it suffices; we still
  deduplicate by action hash defensively.
  """
  top = sync.read_ac_entry(top_hash)
  dieOnError(top is None, "No Action Cache entry found for action %s" % top_hash)

  entries = [top]
  seen = {top_hash}
  for dep in top["action"].get("runtimeDeps", []):
    dep_hash = dep["actionHash"]
    if dep_hash in seen:
      continue
    seen.add(dep_hash)
    entry = sync.read_ac_entry(dep_hash)
    dieOnError(entry is None, "Missing Action Cache entry for runtime dependency "
               "%s (%s)" % (dep.get("package", "?"), dep_hash))
    entries.append(entry)
  return entries


def install_entry(sync, entry, prefix, architecture):
  """Materialise a single Action Cache entry into prefix: fetch its CAS blob,
  unpack it (the tarball already contains <arch>/<pkg>/<ver>-<rev>/...) and run
  the in-tarball relocate-me.sh against the target prefix."""
  action = entry["action"]
  result = entry.get("result") or {}
  digest = result.get("outputDigest", "")
  dieOnError(":" not in digest,
             "Action Cache entry for %s has no output digest; cannot install "
             "(was it ever uploaded?)" % action["package"])
  algo, _, content_hash = digest.partition(":")

  pkg, version, revision = action["package"], action["version"], action["revision"]
  pkgpath = os.path.join(architecture, pkg, "%s-%s" % (version, revision))
  dest_dir = os.path.join(prefix, pkgpath)

  if os.path.isdir(dest_dir):
    debug("%s %s-%s already present at %s, skipping",
          pkg, version, revision, dest_dir)
  else:
    info("Installing %s %s-%s", pkg, version, revision)
    os.makedirs(prefix, exist_ok=True)
    tmp_tarball = os.path.join(prefix, ".%s-%s-%s.tar.gz.part" % (pkg, version, revision))
    try:
      sync.download_artifact(content_hash, tmp_tarball, algo)
      with tarfile.open(tmp_tarball) as tar:
        # The tarball is laid out as <arch>/<pkg>/<ver>-<rev>/..., so extracting
        # at the prefix lands it in the right place.
        try:
          tar.extractall(prefix, filter="data")   # python >= 3.12
        except TypeError:
          tar.extractall(prefix)
    finally:
      if os.path.exists(tmp_tarball):
        os.unlink(tmp_tarball)

    # Relocate to the final prefix. relocate-me.sh ships inside the tarball and
    # rewrites the build-time placeholder paths to $WORK_DIR/$PKGPATH, so it
    # must run from the prefix with WORK_DIR pointing at it.
    relocate = os.path.join(dest_dir, "relocate-me.sh")
    if os.path.exists(relocate):
      err = execute("cd %s && WORK_DIR=%s bash -e %s" % (
        quote(prefix), quote(prefix), quote(os.path.join(pkgpath, "relocate-me.sh"))))
      dieOnError(err, "Relocation failed for %s %s-%s" % (pkg, version, revision))
      for root, _, files in os.walk(dest_dir):
        for fname in files:
          if fname.endswith(".unrelocated"):
            os.unlink(os.path.join(root, fname))

  # Point latest at the freshly installed revision, like a build would.
  pkg_dir = os.path.join(prefix, architecture, pkg)
  os.makedirs(pkg_dir, exist_ok=True)
  symlink("%s-%s" % (version, revision), os.path.join(pkg_dir, "latest"))


def doInstall(args, parser):
  sync = remote_from_url(args.remoteStore, "", args.architecture, args.workDir,
                         getattr(args, "insecure", False),
                         ac_url=getattr(args, "acStore", "") or "")
  dieOnError(not isinstance(sync, REAPIRemoteSync),
             "'aliBuild install' requires a reapi:// remote store, but got %r" %
             (args.remoteStore or "(none)"))

  prefix = os.path.abspath(args.prefix or args.workDir)
  top_hash = sync.resolve_action_hash(args.package, args.version, args.revision)
  dieOnError(not top_hash, "Could not find %s %s%s in %s" % (
    args.package, args.version,
    "-" + args.revision if args.revision else "", args.remoteStore))

  closure = collect_runtime_closure(sync, top_hash)
  info("Installing %s and %d runtime dependenc%s into %s", args.package,
       len(closure) - 1, "y" if len(closure) == 2 else "ies", prefix)
  for entry in closure:
    install_entry(sync, entry, prefix, args.architecture)

  top = closure[0]["action"]
  init_sh = os.path.join(prefix, args.architecture, top["package"],
                         "%s-%s" % (top["version"], top["revision"]),
                         "etc", "profile.d", "init.sh")
  info("Done. To use %s, run:\n  WORK_DIR=%s source %s",
       top["package"], quote(prefix), quote(init_sh))
  return True
