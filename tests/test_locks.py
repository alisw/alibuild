import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from os.path import join
from unittest.mock import patch

from alibuild_helpers.locks import lock_package, build_slots, take_build_slot, _open, _try_lock


@patch("alibuild_helpers.locks.info")
@patch("alibuild_helpers.locks.buildstatus.update", new=lambda **kw: None)
class LocksTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self.tmp = tempfile.TemporaryDirectory()
    self.work_dir = self.tmp.name

  def tearDown(self) -> None:
    self.tmp.cleanup()

  def held(self, name):
    """Whether someone holds LOCKS/name. flock()s conflict between open files, even in one process."""
    fd = _open(join(self.work_dir, "LOCKS", name))
    try:
      return not _try_lock(fd)
    finally:
      os.close(fd)

  def test_package_lock(self, info) -> None:
    fd = lock_package(self.work_dir, "abc123", "zlib")
    self.assertTrue(self.held("abc123"))
    self.assertFalse(self.held("def456"))
    # Another process needing the package waits until the lock is released.
    got = []
    waiter = threading.Thread(target=lambda: got.append(lock_package(self.work_dir, "abc123", "zlib")))
    waiter.start()
    waiter.join(0.2)
    self.assertTrue(waiter.is_alive())
    info.assert_called_with("Waiting for another aliBuild, which is building %s", "zlib")
    os.close(fd)
    waiter.join(5)
    self.assertEqual(len(got), 1)
    os.close(got[0])
    self.assertFalse(self.held("abc123"))

  def test_deleted_lock_file(self, info) -> None:
    # macOS lockf(1) without -k deletes its lock file when it exits. A process
    # waiting on that file then gets a lock on a deleted file, which excludes
    # nobody: it must lock the file now at the path instead.
    path = join(self.work_dir, "LOCKS", "slot-0")
    holder = _open(path)
    self.assertTrue(_try_lock(holder))
    got = []
    waiter = threading.Thread(target=lambda: got.append(lock_package(self.work_dir, "slot-0", "x")))
    waiter.start()
    waiter.join(0.2)
    self.assertTrue(waiter.is_alive())
    os.unlink(path)   # what lockf does on exit...
    os.close(holder)  # ...before its lock goes
    waiter.join(5)
    self.assertEqual(len(got), 1)
    # The waiter holds the file now at the path, so a newcomer is excluded.
    self.assertTrue(self.held("slot-0"))
    self.assertEqual(os.stat(path).st_ino, os.fstat(got[0]).st_ino)
    os.close(got[0])

  @unittest.skipUnless(shutil.which("lockf"), "needs lockf(1), from BSD and macOS")
  def test_real_lockf_without_k(self, info) -> None:
    # The same with the real lockf, as agents run it: the slot must not be
    # shared once lockf has deleted its file. Without -k, lockf gives no
    # ordering guarantee, so either it or aliBuild may get the slot first;
    # what must hold either way is that aliBuild ends up holding the file
    # now at the path, so it excludes newcomers.
    path = join(self.work_dir, "LOCKS", "slot-0")
    first = take_build_slot(self.work_dir, 1, "a", poll=0.01)
    proc = subprocess.Popen(["lockf", path, "sleep", "0.3"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.2)  # lockf is waiting for the slot
    got = []
    waiter = threading.Thread(target=lambda: got.append(take_build_slot(self.work_dir, 1, "b", poll=0.01)))
    waiter.start()
    os.close(first)  # lockf or the waiter gets it; lockf deletes the file on exit
    waiter.join(5)
    self.assertEqual(len(got), 1)
    try:
      # If lockf won, it may still be running: let it finish (and delete its
      # file), then aliBuild must have moved on to the file now at the path.
      deadline = time.time() + 5
      while proc.poll() is None and time.time() < deadline:
        if os.path.exists(path) and os.stat(path).st_ino == os.fstat(got[0]).st_ino:
          break  # aliBuild holds the current file: lockf is the one waiting
        time.sleep(0.01)
      self.assertTrue(self.held("slot-0"))
      self.assertEqual(os.stat(path).st_ino, os.fstat(got[0]).st_ino)
    finally:
      os.close(got[0])  # lets a still-waiting lockf run, so it can exit
      proc.wait(5)

  def test_build_slots(self, info) -> None:
    self.assertIsNone(build_slots({}))
    self.assertIsNone(build_slots({"ALIBUILD_BUILD_SLOTS": "0"}))
    self.assertIsNone(build_slots({"ALIBUILD_BUILD_SLOTS": "many"}))
    self.assertEqual(build_slots({"ALIBUILD_BUILD_SLOTS": "2"}), 2)

    first = take_build_slot(self.work_dir, 2, "a", poll=0.01)
    second = take_build_slot(self.work_dir, 2, "b", poll=0.01)
    self.assertTrue(self.held("slot-0") and self.held("slot-1"))
    got = []
    waiter = threading.Thread(target=lambda: got.append(take_build_slot(self.work_dir, 2, "c", poll=0.01)))
    waiter.start()
    waiter.join(0.2)
    self.assertTrue(waiter.is_alive())
    os.close(first)
    waiter.join(5)
    self.assertEqual(len(got), 1)
    for fd in (second, got[0]):
      os.close(fd)
    self.assertFalse(self.held("slot-0") or self.held("slot-1"))


if __name__ == '__main__':
  unittest.main()
