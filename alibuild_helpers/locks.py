"""Locks which let several aliBuild processes share one work directory.

They are flock()s on files in WORKDIR/LOCKS, so they go away with the process
holding them, however it ends: a crashed build cannot leave one behind.

* A package lock, on its hash, is held while a process decides whether to
  build that package and builds it. Another process which needs the same
  package waits, and then finds it built.
* Build slots, when ALIBUILD_BUILD_SLOTS=N is set, let at most N processes run
  a package's build at the same time, so concurrent builds do not overload the
  machine.
"""

import fcntl
import os
import time
from os.path import join

from alibuild_helpers.log import info

SLOT_POLL_SEC = 2


def _open(path):
  os.makedirs(os.path.dirname(path), exist_ok=True)
  return os.open(path, os.O_RDWR | os.O_CREAT, 0o644)


def _try_lock(fd):
  try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return True
  except BlockingIOError:
    return False


def unlock(fd):
  os.close(fd)


def lock_package(work_dir, pkg_hash, package):
  """Take the lock on pkg_hash, waiting for whoever holds it. unlock() the result."""
  fd = _open(join(work_dir, "LOCKS", pkg_hash))
  if not _try_lock(fd):
    info("Waiting for another aliBuild, which is building %s", package)
    fcntl.flock(fd, fcntl.LOCK_EX)
  return fd


def build_slots(environ=os.environ):
  """How many builds may run at the same time in a work directory, or None for no limit."""
  value = environ.get("ALIBUILD_BUILD_SLOTS", "")
  return int(value) if value.isdigit() and int(value) > 0 else None


def take_build_slot(work_dir, slots, package, poll=SLOT_POLL_SEC):
  """Wait for one of slots build slots. unlock() the result."""
  fds = [_open(join(work_dir, "LOCKS", f"slot-{i}")) for i in range(slots)]
  waiting = False
  while True:
    for i, fd in enumerate(fds):
      if _try_lock(fd):
        for other in fds[:i] + fds[i + 1:]:
          os.close(other)
        return fd
    if not waiting:
      info("Waiting for a build slot for %s: %d build(s) already running "
           "(ALIBUILD_BUILD_SLOTS=%d)", package, slots, slots)
      waiting = True
    time.sleep(poll)
