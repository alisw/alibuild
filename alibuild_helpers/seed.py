"""Seed a session's build directory from another session's, to build incrementally.

`aliBuild session create NAME --seed-from OTHER` records OTHER in the session.
The first time a worktree package of NAME is built, its build directory
BUILD/HASH/PKG does not exist yet. It is then made a copy-on-write clone of
OTHER's, BUILD/PKG-latest-OTHER/PKG, which is made valid at its new place:

* The paths of OTHER's build, source and installs are replaced by NAME's in
  the build directory's text files and symlinks, and in ninja's logs. The
  command lines ninja recorded are rehashed, as they now name NAME's paths.
* Files of the PKG@NAME worktree which are the same as in PKG@OTHER get the
  modification time they have there, so that only what differs is rebuilt.
* .build_succeeded is removed, so that the recipe runs, and so configures and
  builds in the clone, incrementally.

Nothing of OTHER's is modified. Object files still name OTHER's sources in
their debug information until they are rebuilt.
"""

import filecmp
import json
import os
import re
import stat
import struct
import subprocess
from os.path import abspath, exists, isdir, islink, join, realpath

from alibuild_helpers import cow
from alibuild_helpers.locks import try_lock_package, unlock
from alibuild_helpers.log import debug, info, warning

#: Files never holding paths worth rewriting.
BINARY_SUFFIXES = (".o", ".a", ".so", ".dylib", ".pcm", ".pch", ".gch", ".root", ".gz", ".png")
#: Characters which continue a name, so that a path followed by one is another path.
NAME_CHAR = rb"[A-Za-z0-9_.+@-]"
SCM_DIRS = {".git", ".sl", ".hg"}


def path_rewriter(pairs):
  """A function replacing each old path in bytes by its new one.

  Each old path starts with a slash, and only whole names match: /O2@a does
  not match in /O2@ab, nor /x-local1 in /x-local12.
  """
  pairs = {os.fsencode(old): os.fsencode(new) for old, new in pairs if old != new}
  if not pairs:
    return lambda data: data
  regex = re.compile(rb"(" +
                     b"|".join(re.escape(old) for old in sorted(pairs, key=len, reverse=True)) +
                     rb")(?!" + NAME_CHAR + rb")")
  return lambda data: regex.sub(lambda m: pairs[m.group(1)], data)


def seed_paths(work_dir, arch, defaults, spec, specs, other, other_hash, root="."):
  """The (old, new) paths to replace in a clone of other's build of spec."""
  package, session = spec["package"], spec["devel_label"]
  pairs = [("/" + other_hash, "/" + spec["hash"]),
           (f"/BUILD/{package}-latest-{other}", f"/BUILD/{package}-latest-{session}"),
           (f"/SOURCES/{package}/{other}", f"/SOURCES/{package}/{spec['version']}")]
  for path in {abspath(root), realpath(root)}:
    pairs.append((join(path, f"{package}@{other}"), join(path, f"{package}@{session}")))
  # The installs other was built against, itself included, are where its
  # latest-OTHER-DEFAULTS links point.
  for dep in [package] + sorted(spec.get("full_requires", ())):
    link = join(work_dir, arch, dep, f"latest-{other}-{defaults}")
    if islink(link) and dep in specs:
      pairs.append((f"/{arch}/{dep}/{os.readlink(link)}",
                    f"/{arch}/{dep}/{specs[dep]['version']}-{specs[dep]['revision']}"))
  return pairs


def rewrite_tree(top, rewrite, skip=(".ninja_log", ".ninja_deps")):
  """Rewrite paths in the text files and symlinks under top, keeping mtimes.

  Return how many were changed."""
  changed = 0
  for dirpath, dirnames, filenames in os.walk(top):
    for name in filenames + [d for d in dirnames if islink(join(dirpath, d))]:
      path = join(dirpath, name)
      if islink(path):
        target = os.fsencode(os.readlink(path))
        if rewrite(target) != target:
          os.unlink(path)
          os.symlink(rewrite(target), path)
          changed += 1
        continue
      if name in skip or name.endswith(BINARY_SUFFIXES):
        continue
      with open(path, "rb") as f:
        data = f.read(65536)
        if b"\0" in data:  # not text, e.g. an executable: do not read it all
          continue
        data += f.read()
      new = rewrite(data)
      if new != data:
        st = os.stat(path)
        with open(path, "wb") as f:
          f.write(new)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
        changed += 1
  return changed


MASK64 = (1 << 64) - 1


def murmur_hash64a(data):
  """ninja's command hash, up to log version 6."""
  m, r = 0xc6a4a7935bd1e995, 47
  h = (0xDECAFBADDECAFBAD ^ (len(data) * m)) & MASK64
  end = len(data) - len(data) % 8
  for (k,) in struct.iter_unpack("<Q", data[:end]):
    k = (k * m) & MASK64
    k ^= k >> r
    k = (k * m) & MASK64
    h = ((h ^ k) * m) & MASK64
  tail = data[end:]
  if tail:
    for i, byte in enumerate(tail):
      h ^= byte << (8 * i)
    h = (h * m) & MASK64
  h ^= h >> r
  h = (h * m) & MASK64
  h ^= h >> r
  return h


RAPID_SECRET = (0x2d358dccaa6c78a5, 0x8bb84b93962eacc9, 0x4b33a62ed433d4a3)


def _rapid_mum(a, b):
  r = a * b
  return r & MASK64, (r >> 64) & MASK64


def _rapid_mix(a, b):
  a, b = _rapid_mum(a, b)
  return a ^ b


def rapidhash(data, seed=0xbdd89aa982704029):
  """ninja's command hash, from log version 7 (rapidhash, as in ninja's copy)."""
  s = RAPID_SECRET
  r64 = lambda p: struct.unpack_from("<Q", data, p)[0]
  r32 = lambda p: struct.unpack_from("<I", data, p)[0]
  n = len(data)
  seed ^= _rapid_mix(seed ^ s[0], s[1]) ^ n
  if n <= 16:
    if n >= 4:
      last = n - 4
      a = (r32(0) << 32) | r32(last)
      delta = (n & 24) >> (n >> 3)
      b = (r32(delta) << 32) | r32(last - delta)
    elif n > 0:
      a, b = (data[0] << 56) | (data[n >> 1] << 32) | data[n - 1], 0
    else:
      a = b = 0
  else:
    p, i = 0, n
    if i > 48:
      see1 = see2 = seed
      while i >= 48:
        seed = _rapid_mix(r64(p) ^ s[0], r64(p + 8) ^ seed)
        see1 = _rapid_mix(r64(p + 16) ^ s[1], r64(p + 24) ^ see1)
        see2 = _rapid_mix(r64(p + 32) ^ s[2], r64(p + 40) ^ see2)
        p, i = p + 48, i - 48
      seed ^= see1 ^ see2
    if i > 16:
      seed = _rapid_mix(r64(p) ^ s[2], r64(p + 8) ^ seed ^ s[1])
      if i > 32:
        seed = _rapid_mix(r64(p + 16) ^ s[2], r64(p + 24) ^ seed)
    a, b = r64(p + i - 16), r64(p + i - 8)
  a, b = _rapid_mum(a ^ s[1], b ^ seed)
  return _rapid_mix(a ^ s[0] ^ n, b ^ s[1])


def ninja_hash(version):
  """The command hash of ninja's log version, or None if it is not known."""
  return murmur_hash64a if 4 <= version <= 6 else rapidhash if version == 7 else None


def rewrite_ninja_log(path, rewrite, commands):
  """Rewrite the outputs in a .ninja_log, and the hashes of commands that changed.

  commands are the command lines of the build, before rewriting. A hash which
  is none of theirs is kept: ninja then runs that command again.
  """
  with open(path, "rb") as f:
    lines = f.read().split(b"\n")
  match = re.match(rb"# ninja log v(\d+)\Z", lines[0])
  hash_command = ninja_hash(int(match.group(1))) if match else None
  if hash_command is None:
    warning("Unknown ninja log format in %s: its commands will be run again", path)
    return 0
  rehash = {}
  for command in commands:
    new = rewrite(command)
    if new != command:
      rehash[hash_command(command)] = hash_command(new)
  rehashed = 0
  for i, line in enumerate(lines[1:], 1):
    fields = line.split(b"\t")
    if len(fields) != 5:
      continue
    fields[3] = rewrite(fields[3])
    new = rehash.get(int(fields[4], 16))
    if new is not None:
      fields[4] = b"%x" % new
      rehashed += 1
    lines[i] = b"\t".join(fields)
  with open(path, "wb") as f:
    f.write(b"\n".join(lines))
  return rehashed


def rewrite_ninja_deps(path, rewrite):
  """Rewrite the paths in a .ninja_deps (version 4) log, keeping their ids."""
  with open(path, "rb") as f:
    data = f.read()
  if data[:12] != b"# ninjadeps\n" or struct.unpack_from("<i", data, 12)[0] != 4:
    warning("Unknown ninja deps log format in %s: leaving it as it is", path)
    return
  out, pos = [data[:16]], 16
  while pos + 4 <= len(data):
    (size,) = struct.unpack_from("<I", data, pos)
    is_deps, size = size >> 31, size & 0x7FFFFFFF
    record = data[pos + 4:pos + 4 + size]
    if len(record) < size:
      break  # truncated by an interrupted ninja, which ignores it too
    pos += 4 + size
    if is_deps:
      out.append(data[pos - 4 - size:pos])
      continue
    name, checksum = rewrite(record[:-4].rstrip(b"\0")), record[-4:]
    padded = name + b"\0" * ((4 - len(name) % 4) % 4)
    out.append(struct.pack("<I", len(padded) + 4) + padded + checksum)
  with open(path, "wb") as f:
    f.write(b"".join(out))


#: The ninja versions whose logs are known to be rewritten right.
NINJA_VERSIONS = ("1.11.", "1.13.")


def ninja_program(build_dir):
  """The ninja which builds build_dir, or None if it is not built with ninja by CMake."""
  try:
    with open(join(build_dir, "CMakeCache.txt"), errors="replace") as f:
      for line in f:
        if line.startswith("CMAKE_MAKE_PROGRAM:"):
          program = line.split("=", 1)[1].strip()
          return program if "ninja" in os.path.basename(program) else None
  except OSError:
    pass
  return None


def unknown_ninja(build_dir):
  """The version of the ninja building build_dir, if seeding does not know it, else None."""
  program = ninja_program(build_dir)
  if program is None:
    return None
  try:
    version = subprocess.run([program, "--version"], stdout=subprocess.PIPE, text=True).stdout.strip()
  except OSError:
    version = f"{program}, which cannot be run"
  return None if version.startswith(NINJA_VERSIONS) else version or "unknown"


def ninja_commands(build_dir):
  """Every command line in build_dir's build.ninja, as ninja evaluates them."""
  program = ninja_program(build_dir)
  if program is None:
    return None
  proc = subprocess.run([program, "-C", build_dir, "-t", "compdb"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
  if proc.returncode:
    return None
  return [os.fsencode(entry["command"]) for entry in json.loads(proc.stdout)]


def sync_mtimes(new_tree, old_tree):
  """Give the files of new_tree the mtime of the same file in old_tree.

  Only files with the same content are touched, so the rest look modified.
  """
  synced = 0
  for dirpath, dirnames, filenames in os.walk(new_tree):
    dirnames[:] = [d for d in dirnames if d not in SCM_DIRS]
    for name in filenames:
      new = join(dirpath, name)
      old = join(old_tree, os.path.relpath(new, new_tree))
      try:
        new_st, old_st = os.lstat(new), os.lstat(old)
      except OSError:
        continue
      if (stat.S_ISREG(new_st.st_mode) and stat.S_ISREG(old_st.st_mode) and
          new_st.st_mtime_ns != old_st.st_mtime_ns and new_st.st_size == old_st.st_size and
          filecmp.cmp(new, old, shallow=False)):
        os.utime(new, ns=(new_st.st_atime_ns, old_st.st_mtime_ns))
        synced += 1
  return synced


def seed_build_dir(work_dir, arch, defaults, spec, specs, other, root=".", backends=None):
  """Make BUILD/HASH/PKG a clone of session other's build of PKG.

  Return True if it was seeded. If it cannot be, say why, and return False:
  the package is then built from scratch, as without seeding.
  """
  package = spec["package"]
  dst = join(work_dir, "BUILD", spec["hash"], package)
  other_link = join(work_dir, "BUILD", f"{package}-latest-{other}")
  if exists(dst):
    return False
  if "incremental_recipe" not in spec:
    info("Not seeding %s from session %s: its recipe has no incremental_recipe, "
         "so its build directory is always started afresh", package, other)
    return False
  if not islink(other_link) or not isdir(join(other_link, package)):
    info("Not seeding %s: session %s has no build of it in %s", package, other, other_link)
    return False
  other_hash = os.readlink(other_link)
  src = join(work_dir, "BUILD", other_hash, package)
  try:
    with open(join(src, ".envrc")) as f:
      same_arch = f"{arch}/{package}/" in f.read()
  except OSError:
    same_arch = False
  if not same_arch:
    info("Not seeding %s: session %s's build in %s is not one for %s", package, other, src, arch)
    return False
  version = unknown_ninja(src)
  if version is not None:
    info("Not seeding %s: it is built with ninja %s, and seeding only knows the logs "
         "of ninja %s", package, version, " and ".join(v + "x" for v in NINJA_VERSIONS))
    return False
  other_tree = join(root, f"{package}@{other}")
  if not isdir(other_tree):
    info("Not seeding %s: no %s worktree, to tell which sources changed", package, other_tree)
    return False

  # Holding other's lock, so that its build does not change what is cloned.
  lock = try_lock_package(work_dir, other_hash)
  if lock is None:
    info("Not seeding %s: session %s is building it right now", package, other)
    return False
  try:
    os.makedirs(join(work_dir, "BUILD", spec["hash"]), exist_ok=True)
    try:
      backend = cow.clone_tree(src, dst, backends)
    except cow.CloneError as e:
      info("Not seeding %s from session %s, as its build directory cannot be cloned "
           "copy-on-write here (%s). Building it from scratch.", package, other, e)
      return False
  finally:
    unlock(lock)

  info("Seeding the build of %s from session %s's (%s, cloned with %s)", package, other, src, backend)
  rewrite = path_rewriter(seed_paths(work_dir, arch, defaults, spec, specs, other, other_hash, root))
  for marker in (".build_succeeded",):
    if exists(join(dst, marker)):
      os.unlink(join(dst, marker))
  commands = ninja_commands(dst) if exists(join(dst, "build.ninja")) else None
  changed = rewrite_tree(dst, rewrite)
  rehashed = 0
  if exists(join(dst, ".ninja_log")):
    if commands is None:
      warning("Cannot read the commands of %s: ninja will run them all again", dst)
    rehashed = rewrite_ninja_log(join(dst, ".ninja_log"), rewrite, commands or [])
  if exists(join(dst, ".ninja_deps")):
    rewrite_ninja_deps(join(dst, ".ninja_deps"), rewrite)
  synced = sync_mtimes(spec["source"], other_tree)
  debug("Seeded %s: %d files rewritten, %d commands rehashed, %d sources dated as in %s",
        dst, changed, rehashed, synced, other_tree)
  with open(join(dst, ".seeded_from"), "w") as f:
    f.write(f"{other} {other_hash}\n")
  return True
