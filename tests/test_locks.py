import os
import tempfile
import threading
import unittest
from os.path import join
from unittest.mock import patch

from alibuild_helpers.locks import lock_package, build_slots, take_build_slot, _open, _try_lock


@patch("alibuild_helpers.locks.info")
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
