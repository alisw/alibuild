"""Copy-on-write clones of directory trees, for seeding build directories.

A backend clones a tree so that source and clone share their blocks until one
of them is written, and keeps the files' modification times. Backends never
fall back to a plain deep copy: when none of them can clone, CloneError says
why, and the caller does without the clone.

To add a backend, e.g. for another filesystem, subclass CloneBackend, give it
a unique name, and add an instance to BACKENDS, in the order it should be
tried. ALIBUILD_COW_BACKEND=NAME[,NAME...] selects backends by name, and
ALIBUILD_COW_BACKEND=none disables cloning.
"""

import ctypes
import ctypes.util
import os
import shutil
import subprocess
import sys
from os.path import dirname


class CloneError(Exception):
  """A tree could not be cloned, and nothing was copied."""


class CloneBackend:
  name = ""

  def unavailable_reason(self, src, dst):
    """Why src cannot be cloned to dst with this backend, or None if it can."""
    raise NotImplementedError

  def available(self, src, dst):
    return self.unavailable_reason(src, dst) is None

  def clone_tree(self, src, dst):
    """Clone src, a directory tree or a file, to dst, which must not exist.

    Symbolic links are cloned as links. Raise CloneError if it fails."""
    raise NotImplementedError


def same_device(src, dst):
  return os.stat(src).st_dev == os.stat(dirname(dst)).st_dev


class _StatFs(ctypes.Structure):
  """struct statfs of macOS, with 64-bit inodes."""
  _fields_ = [("f_bsize", ctypes.c_uint32), ("f_iosize", ctypes.c_int32),
              ("f_blocks", ctypes.c_uint64), ("f_bfree", ctypes.c_uint64),
              ("f_bavail", ctypes.c_uint64), ("f_files", ctypes.c_uint64),
              ("f_ffree", ctypes.c_uint64), ("f_fsid", ctypes.c_int32 * 2),
              ("f_owner", ctypes.c_uint32), ("f_type", ctypes.c_uint32),
              ("f_flags", ctypes.c_uint32), ("f_fssubtype", ctypes.c_uint32),
              ("f_fstypename", ctypes.c_char * 16), ("f_mntonname", ctypes.c_char * 1024),
              ("f_mntfromname", ctypes.c_char * 1024), ("f_flags_ext", ctypes.c_uint32),
              ("f_reserved", ctypes.c_uint32 * 7)]


def _libsystem():
  return ctypes.CDLL(ctypes.util.find_library("System"), use_errno=True)


def macos_fstype(path):
  """The filesystem type of path on macOS, e.g. "apfs", or None if unknown."""
  try:
    statfs = _libsystem().statfs
  except (OSError, AttributeError):
    return None
  buf = _StatFs()
  if statfs(os.fsencode(path), ctypes.byref(buf)) != 0:
    return None
  return buf.f_fstypename.decode()


CLONE_NOFOLLOW = 0x0001


class ApfsClonefile(CloneBackend):
  """clonefile(2) of macOS, which clones a whole tree at once on APFS."""
  name = "apfs-clonefile"

  def unavailable_reason(self, src, dst):
    if sys.platform != "darwin":
      return "clonefile(2) is only on macOS"
    try:
      _libsystem().clonefile
    except (OSError, AttributeError):
      return "no clonefile(2) in libSystem"
    if not same_device(src, dst):
      return f"{src} and {dirname(dst)} are on different filesystems"
    return None

  def clone_tree(self, src, dst):
    clonefile = _libsystem().clonefile
    if clonefile(os.fsencode(src), os.fsencode(dst), CLONE_NOFOLLOW) != 0:
      err = ctypes.get_errno()
      raise CloneError(f"clonefile({src}, {dst}): {os.strerror(err)}")


class CpClone(CloneBackend):
  """cp, cloning each file: cp -c on APFS, cp --reflink=always on Linux (Btrfs, XFS...).

  macOS cp -c silently copies when it cannot clone, so it is only used on APFS.
  """
  name = "cp-clone"

  def command(self, src, dst):
    if sys.platform == "darwin":
      return ["cp", "-c", "-R", "-p", src, dst]
    return ["cp", "-a", "--reflink=always", src, dst]

  def unavailable_reason(self, src, dst):
    if not shutil.which("cp"):
      return "no cp"
    if not same_device(src, dst):
      return f"{src} and {dirname(dst)} are on different filesystems"
    if sys.platform == "darwin" and macos_fstype(src) != "apfs":
      return f"{src} is not on APFS, and cp -c would copy it"
    return None

  def clone_tree(self, src, dst):
    proc = subprocess.run(self.command(src, dst), stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True)
    if proc.returncode:
      raise CloneError(f"{' '.join(self.command(src, dst))}: {proc.stdout.strip()}")


class ZfsClone(CloneBackend):
  """Not implemented: an extension point.

  ZFS clones datasets, not directories: `zfs snapshot POOL/A@seed` and
  `zfs clone POOL/A@seed POOL/B`. It only fits if every build directory is
  the root of its own dataset, which aliBuild does not set up, and the
  snapshot then outlives the source until the clone is promoted or destroyed.
  A backend would check in unavailable_reason that src is a dataset's
  mountpoint (`zfs list -H -o name,mountpoint`), and mount the clone at dst.
  """
  name = "zfs"

  def unavailable_reason(self, src, dst):
    return "ZFS clones datasets, not directories, which is not implemented"


class NoClone(CloneBackend):
  """Never clones: ALIBUILD_COW_BACKEND=none disables copy-on-write seeding."""
  name = "none"

  def unavailable_reason(self, src, dst):
    return "copy-on-write cloning is disabled"


#: Tried in this order, unless ALIBUILD_COW_BACKEND says otherwise.
BACKENDS = [ApfsClonefile(), CpClone(), ZfsClone(), NoClone()]


def select_backends(environ=os.environ, backends=None):
  """The backends to try, in order: those named by ALIBUILD_COW_BACKEND, or all."""
  backends = BACKENDS if backends is None else backends
  wanted = [n.strip() for n in environ.get("ALIBUILD_COW_BACKEND", "").split(",") if n.strip()]
  if not wanted:
    return list(backends)
  by_name = {b.name: b for b in backends}
  unknown = [n for n in wanted if n not in by_name]
  if unknown:
    raise CloneError("unknown ALIBUILD_COW_BACKEND %s, known ones are %s" %
                     (", ".join(unknown), ", ".join(by_name)))
  return [by_name[n] for n in wanted]


def clone_tree(src, dst, backends=None, environ=os.environ):
  """Clone src, a tree or a file, to dst with the first backend which can; return its name.

  Raise CloneError, saying why for each backend, if none can. dst is left
  absent then.
  """
  reasons = []
  for backend in select_backends(environ, backends):
    reason = backend.unavailable_reason(src, dst)
    if reason is None:
      try:
        backend.clone_tree(src, dst)
        return backend.name
      except CloneError as e:
        reason = str(e)
        shutil.rmtree(dst, ignore_errors=True)
    reasons.append(f"{backend.name}: {reason}")
  raise CloneError("; ".join(reasons))
