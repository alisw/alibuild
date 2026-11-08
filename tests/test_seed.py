import os
import shutil
import struct
import tempfile
import unittest
from os.path import exists, join
from unittest.mock import patch

from alibuild_helpers import cow, seed


class CopyBackend(cow.CloneBackend):
  """Stands in for a copy-on-write backend in tests."""
  name = "test-copy"

  def unavailable_reason(self, src, dst):
    return None

  def clone_tree(self, src, dst):
    shutil.copytree(src, dst, symlinks=True)


class Failing(CopyBackend):
  name = "failing"

  def clone_tree(self, src, dst):
    raise cow.CloneError("cannot")


def deps_log(*records):
  """A .ninja_deps with the given paths (str) and deps records (tuples of ids)."""
  out = [b"# ninjadeps\n", struct.pack("<i", 4)]
  for record in records:
    if isinstance(record, str):
      path = record.encode()
      path += b"\0" * ((4 - len(path) % 4) % 4)
      out.append(struct.pack("<I", len(path) + 4) + path + struct.pack("<I", ~len(out) & 0xFFFFFFFF))
    else:
      body = struct.pack("<iII", record[0], 7, 0) + b"".join(struct.pack("<i", i) for i in record[1:])
      out.append(struct.pack("<I", len(body) | 0x80000000) + body)
  return b"".join(out)


def read_deps_paths(data):
  pos, paths = 16, []
  while pos < len(data):
    (size,) = struct.unpack_from("<I", data, pos)
    if not size >> 31:
      paths.append(data[pos + 4:pos + size].rstrip(b"\0").decode())
    pos += 4 + (size & 0x7FFFFFFF)
  return paths


class HashTestCase(unittest.TestCase):
  def test_ninja_hashes(self) -> None:
    # As written by ninja 1.11 (log v5) and 1.13 (log v7) in .ninja_log.
    long = b"touch c && echo 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef" \
           b"0123456789abcdef0123456789abcdef0123456789abcdef"
    for command, v5, v7 in ((b"touch a", 0x9544b174230a39b3, 0xd91ff1f2760e13e4),
                            (b"touch b && echo 0123456789", 0x6df90d9b2cc5b8c4, 0xa11d1f115207f8f5),
                            (long, 0x832be2d979ff7ac8, 0x95a81f97b28b2ba4)):
      self.assertEqual(seed.ninja_hash(5)(command), v5)
      self.assertEqual(seed.ninja_hash(7)(command), v7)
    self.assertIsNone(seed.ninja_hash(8))


class RewriteTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self.tmp = tempfile.TemporaryDirectory()
    self.dir = self.tmp.name

  def tearDown(self) -> None:
    self.tmp.cleanup()

  def test_path_rewriter(self) -> None:
    rewrite = seed.path_rewriter([("/src/O2@a", "/src/O2@b"), ("/arch/O2/a-local1", "/arch/O2/b-local3"),
                                  ("/same", "/same")])
    self.assertEqual(rewrite(b"-I/src/O2@a/include:/src/O2@ab/x /src/O2@a"),
                     b"-I/src/O2@b/include:/src/O2@ab/x /src/O2@b")
    self.assertEqual(rewrite(b"../../arch/O2/a-local1/lib ../arch/O2/a-local12"),
                     b"../../arch/O2/b-local3/lib ../arch/O2/a-local12")
    self.assertEqual(seed.path_rewriter([("/x", "/x")])(b"/x"), b"/x")

  def test_rewrite_tree(self) -> None:
    os.makedirs(join(self.dir, "CMakeFiles"))
    for name, data in (("CMakeCache.txt", b"DIR=/old/build\n"), ("CMakeFiles/x.o", b"\0/old/build"),
                       ("CMakeFiles/gen.cxx", b"#include \"/old/build/h\"\n"), (".ninja_log", b"/old/build")):
      with open(join(self.dir, name), "wb") as f:
        f.write(data)
      os.utime(join(self.dir, name), ns=(1, 1000000000))
    os.symlink("/old/build/lib", join(self.dir, "link"))
    self.assertEqual(seed.rewrite_tree(self.dir, seed.path_rewriter([("/old/build", "/new/b")])), 3)
    for name, data in (("CMakeCache.txt", b"DIR=/new/b\n"), ("CMakeFiles/x.o", b"\0/old/build"),
                       ("CMakeFiles/gen.cxx", b"#include \"/new/b/h\"\n"), (".ninja_log", b"/old/build")):
      with open(join(self.dir, name), "rb") as f:
        self.assertEqual(f.read(), data)
      self.assertEqual(os.stat(join(self.dir, name)).st_mtime_ns, 1000000000)
    self.assertEqual(os.readlink(join(self.dir, "link")), "/new/b/lib")

  def test_ninja_log(self) -> None:
    rewrite = seed.path_rewriter([("/old", "/new")])
    h = seed.ninja_hash(5)
    old, unchanged, stale = b"cc -I/old/x -c a.c", b"cc -c b.c", b"cc -I/old/y -c c.c"
    log = join(self.dir, ".ninja_log")
    with open(log, "wb") as f:
      f.write(b"# ninja log v5\n" + b"".join(b"1\t2\t3\t%s\t%x\n" % (o, h(c)) for o, c in (
        (b"a.o", old), (b"/old/b.o", unchanged), (b"c.o", stale))))
    # c.o was built by a command which is not the build's any more.
    self.assertEqual(seed.rewrite_ninja_log(log, rewrite, [old, unchanged, b"cc -I/old/y -O2 -c c.c"]), 1)
    with open(log, "rb") as f:
      self.assertEqual(f.read(), b"# ninja log v5\n" + b"".join(b"1\t2\t3\t%s\t%x\n" % (o, h(c)) for o, c in (
        (b"a.o", b"cc -I/new/x -c a.c"), (b"/new/b.o", unchanged), (b"c.o", stale))))
    with open(log, "wb") as f:
      f.write(b"# ninja log v99\n")
    self.assertEqual(seed.rewrite_ninja_log(log, rewrite, [old]), 0)

  def test_ninja_deps(self) -> None:
    path = join(self.dir, ".ninja_deps")
    with open(path, "wb") as f:
      f.write(deps_log("a.o", "/old/include/h.h", (0, 1), "/old/x"))
    seed.rewrite_ninja_deps(path, seed.path_rewriter([("/old", "/newer/path")]))
    with open(path, "rb") as f:
      data = f.read()
    self.assertEqual(data, deps_log("a.o", "/newer/path/include/h.h", (0, 1), "/newer/path/x"))
    self.assertEqual(read_deps_paths(data), ["a.o", "/newer/path/include/h.h", "/newer/path/x"])

  def test_sync_mtimes(self) -> None:
    for tree in ("old", "new"):
      os.makedirs(join(self.dir, tree, ".git"))
      for name, data in (("same", "x"), ("changed", tree), (".git/index", tree)):
        with open(join(self.dir, tree, name), "w") as f:
          f.write(data)
      if tree == "old":
        for name in ("same", "changed", ".git/index"):
          os.utime(join(self.dir, tree, name), ns=(1, 1000000000))
    self.assertEqual(seed.sync_mtimes(join(self.dir, "new"), join(self.dir, "old")), 1)
    self.assertEqual(os.stat(join(self.dir, "new", "same")).st_mtime_ns, 1000000000)
    self.assertNotEqual(os.stat(join(self.dir, "new", "changed")).st_mtime_ns, 1000000000)


class SeedTestCase(unittest.TestCase):
  """A session s1 seeded from s0, which built pkg as BUILD/OLDHASH/pkg."""

  def setUp(self) -> None:
    self.cwd = os.getcwd()
    self.tmp = tempfile.TemporaryDirectory()
    os.chdir(self.tmp.name)
    self.root = os.getcwd()
    self.work = join(self.root, "sw")
    self.src = join(self.work, "BUILD", "OLDHASH", "pkg")
    os.makedirs(self.src)
    os.symlink("OLDHASH", join(self.work, "BUILD", "pkg-latest-s0"))
    os.makedirs(join(self.work, "arch", "pkg"))
    os.symlink("s0-local2", join(self.work, "arch", "pkg", "latest-s0-o2"))
    for tree in ("pkg@s0", "pkg@s1"):
      os.makedirs(tree)
      with open(join(tree, "a.c"), "w") as f:
        f.write("int a;\n")
    self.files = {
      ".envrc": "source ../../../arch/pkg/s0-local2/etc/profile.d/init.sh\n",
      "CMakeCache.txt": f"CMAKE_CACHEFILE_DIR:INTERNAL={self.work}/BUILD/pkg-latest-s0/pkg\n"
                        f"CMAKE_HOME_DIRECTORY:INTERNAL={self.work}/SOURCES/pkg/s0/0\n"
                        f"CMAKE_INSTALL_PREFIX:PATH={self.work}/arch/pkg/s0-local2\n",
      ".build_succeeded": "abc\n",
    }
    for name, data in self.files.items():
      with open(join(self.src, name), "w") as f:
        f.write(data)
    self.spec = {"package": "pkg", "devel_label": "s1", "version": "s1", "revision": "local1",
                 "hash": "NEWHASH", "incremental_recipe": "make", "full_requires": set(),
                 "source": join(self.root, "pkg@s1")}
    self.specs = {"pkg": self.spec}
    self.dst = join(self.work, "BUILD", "NEWHASH", "pkg")

  def tearDown(self) -> None:
    os.chdir(self.cwd)
    self.tmp.cleanup()

  def seed(self, backends=(CopyBackend(),)):
    return seed.seed_build_dir(self.work, "arch", "o2", self.spec, self.specs, "s0", ".", list(backends))

  def test_seed(self) -> None:
    os.utime("pkg@s0/a.c", ns=(1, 1000000000))
    self.assertTrue(self.seed())
    with open(join(self.dst, "CMakeCache.txt")) as f:
      self.assertEqual(f.read(), f"CMAKE_CACHEFILE_DIR:INTERNAL={self.work}/BUILD/pkg-latest-s1/pkg\n"
                                 f"CMAKE_HOME_DIRECTORY:INTERNAL={self.work}/SOURCES/pkg/s1/0\n"
                                 f"CMAKE_INSTALL_PREFIX:PATH={self.work}/arch/pkg/s1-local1\n")
    with open(join(self.dst, ".envrc")) as f:
      self.assertIn("arch/pkg/s1-local1/etc", f.read())
    # The recipe runs, incrementally, in the clone.
    self.assertFalse(exists(join(self.dst, ".build_succeeded")))
    self.assertEqual(os.stat("pkg@s1/a.c").st_mtime_ns, 1000000000)
    # s0's build directory is left as it was.
    for name, data in self.files.items():
      with open(join(self.src, name)) as f:
        self.assertEqual(f.read(), data)
    # Never twice.
    self.assertFalse(self.seed())

  def test_ninja_version(self) -> None:
    ninja = join(self.root, "ninja")
    with open(join(self.src, "CMakeCache.txt"), "a") as f:
      f.write(f"CMAKE_MAKE_PROGRAM:FILEPATH={ninja}\n")
    for version, seeded in (("1.12.1", False), ("1.11.1.git.kitware.jobserver-1", True)):
      with open(ninja, "w") as f:
        f.write(f"#!/bin/sh\necho {version}\n")
      os.chmod(ninja, 0o755)
      self.assertEqual(self.seed(), seeded)

  def test_not_seeded(self) -> None:
    del self.spec["incremental_recipe"]
    self.assertFalse(self.seed())
    self.spec["incremental_recipe"] = "make"
    with patch.object(seed, "try_lock_package", return_value=None):
      self.assertFalse(self.seed())
    self.assertFalse(self.seed([Failing()]))
    self.assertFalse(exists(self.dst))
    self.assertFalse(seed.seed_build_dir(self.work, "otherarch", "o2", self.spec, self.specs, "s0", ".",
                                         [CopyBackend()]))
    os.rename("pkg@s0", "elsewhere")
    self.assertFalse(self.seed())
    os.rename("elsewhere", "pkg@s0")
    self.assertFalse(seed.seed_build_dir(self.work, "arch", "o2", self.spec, self.specs, "missing", ".",
                                         [CopyBackend()]))
    self.assertFalse(exists(self.dst))
    self.assertTrue(self.seed())


if __name__ == "__main__":
  unittest.main()
