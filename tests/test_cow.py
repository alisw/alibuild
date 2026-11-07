import os
import sys
import tempfile
import unittest
from os.path import exists, join
from unittest.mock import patch

from alibuild_helpers import cow


class Fake(cow.CloneBackend):
  def __init__(self, name, reason=None, fails=False):
    self.name, self.reason, self.fails, self.calls = name, reason, fails, []

  def unavailable_reason(self, src, dst):
    return self.reason

  def clone_tree(self, src, dst):
    self.calls.append((src, dst))
    os.makedirs(join(dst, "partial"))
    if self.fails:
      raise cow.CloneError(f"{self.name} failed")


class CowTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self.tmp = tempfile.TemporaryDirectory()
    self.src, self.dst = join(self.tmp.name, "src"), join(self.tmp.name, "dst")
    os.makedirs(join(self.src, "sub"))
    with open(join(self.src, "sub", "f"), "w") as f:
      f.write("x")
    os.utime(join(self.src, "sub", "f"), ns=(1, 1234567890123456789))

  def tearDown(self) -> None:
    self.tmp.cleanup()

  def test_select(self) -> None:
    a, b, none = Fake("a"), Fake("b"), cow.NoClone()
    self.assertEqual(cow.select_backends({}, [a, b, none]), [a, b, none])
    self.assertEqual(cow.select_backends({"ALIBUILD_COW_BACKEND": "b, a"}, [a, b, none]), [b, a])
    self.assertRaises(cow.CloneError, cow.select_backends, {"ALIBUILD_COW_BACKEND": "zz"}, [a])
    self.assertEqual([b.name for b in cow.BACKENDS], ["apfs-clonefile", "cp-clone", "zfs", "none"])

  def test_fallback(self) -> None:
    unavailable, failing, working = Fake("u", reason="not here"), Fake("f", fails=True), Fake("w")
    self.assertEqual(cow.clone_tree(self.src, self.dst, [unavailable, failing, working], {}), "w")
    self.assertEqual((unavailable.calls, len(failing.calls), len(working.calls)), ([], 1, 1))
    # What the failed backend left is gone before the next one starts.
    self.assertEqual(os.listdir(self.dst), ["partial"])

  def test_none_left(self) -> None:
    with self.assertRaises(cow.CloneError) as e:
      cow.clone_tree(self.src, self.dst, [Fake("f", fails=True), cow.ZfsClone(), cow.NoClone()], {})
    self.assertIn("f: f failed", str(e.exception))
    self.assertIn("none: copy-on-write cloning is disabled", str(e.exception))
    self.assertFalse(exists(self.dst))
    # ALIBUILD_COW_BACKEND=none disables it, whatever else is there.
    working = Fake("w")
    self.assertRaises(cow.CloneError, cow.clone_tree, self.src, self.dst,
                      [working, cow.NoClone()], {"ALIBUILD_COW_BACKEND": "none"})
    self.assertEqual(working.calls, [])

  def test_clonefile_failure(self) -> None:
    class LibSystem:
      @staticmethod
      def clonefile(src, dst, flags):
        return -1
    with patch.object(cow, "_libsystem", return_value=LibSystem), \
         patch.object(sys, "platform", "darwin"), \
         patch.object(cow.CpClone, "unavailable_reason", return_value="no cp here"):
      self.assertIsNone(cow.ApfsClonefile().unavailable_reason(self.src, self.dst))
      with self.assertRaises(cow.CloneError) as e:
        cow.clone_tree(self.src, self.dst, environ={})
    self.assertIn("apfs-clonefile: clonefile(", str(e.exception))
    self.assertIn("cp-clone: no cp here", str(e.exception))
    self.assertFalse(exists(self.dst))

  def test_not_on_macos(self) -> None:
    with patch.object(sys, "platform", "linux"):
      self.assertIn("only on macOS", cow.ApfsClonefile().unavailable_reason(self.src, self.dst))
      self.assertEqual(cow.CpClone().command("a", "b"), ["cp", "-a", "--reflink=always", "a", "b"])

  @unittest.skipUnless(sys.platform == "darwin" and cow.macos_fstype(tempfile.gettempdir()) == "apfs",
                       "needs APFS")
  def test_real_clone(self) -> None:
    for backend in (cow.ApfsClonefile(), cow.CpClone()):
      dst = self.dst + backend.name
      self.assertEqual(cow.clone_tree(self.src, dst, [backend], {}), backend.name)
      self.assertEqual(os.stat(join(dst, "sub", "f")).st_mtime_ns,
                       os.stat(join(self.src, "sub", "f")).st_mtime_ns)


if __name__ == "__main__":
  unittest.main()
