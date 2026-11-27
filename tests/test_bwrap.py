import io
import json
import os
import shlex
import tarfile
import tempfile
import unittest
from unittest import mock

from alibuild_helpers import bwrap
from alibuild_helpers.bwrap import (ImageError, Image, apply_layer, bwrap_command, bwrap_run_string,
                                    parse_image_reference, parse_volume, resolve_in_root, select_platform)


def make_layer(path, entries):
  """Write a gzipped layer tarball: ENTRIES are (name, kind, data) with kind
  one of dir, file, symlink, hardlink; data is the content or link target."""
  with tarfile.open(path, "w:gz") as tar:
    for name, kind, data in entries:
      info = tarfile.TarInfo(name)
      info.mode = 0o755 if kind == "dir" else 0o644
      payload = None
      if kind == "dir":
        info.type = tarfile.DIRTYPE
      elif kind == "file":
        payload = data.encode()
        info.size = len(payload)
      elif kind == "symlink":
        info.type, info.linkname = tarfile.SYMTYPE, data
      elif kind == "hardlink":
        info.type, info.linkname = tarfile.LNKTYPE, data
      tar.addfile(info, io.BytesIO(payload) if payload is not None else None)
  return path


class LayerTestCase(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.root = os.path.join(self.tmp.name, "rootfs")
    os.mkdir(self.root)

  def tearDown(self):
    self.tmp.cleanup()

  def apply(self, entries):
    apply_layer(self.root, make_layer(os.path.join(self.tmp.name, "layer.tar.gz"), entries))

  def read(self, *parts):
    with open(os.path.join(self.root, *parts)) as f:
      return f.read()

  def test_whiteouts(self):
    self.apply([("a", "dir", None), ("a/f", "file", "f"), ("a/g", "file", "g"),
                ("b", "dir", None), ("b/x", "file", "x"), ("b/sub", "dir", None),
                ("b/sub/z", "file", "z"), ("c", "dir", None), ("c/old", "file", "old")])
    # The opaque marker comes after b/y, which must survive it; c is replaced
    # by a file.
    self.apply([("a/.wh.f", "file", ""), ("b/y", "file", "y"), ("b/.wh..wh..opq", "file", ""),
                ("c", "file", "now a file")])
    self.assertEqual(sorted(os.listdir(os.path.join(self.root, "a"))), ["g"])
    self.assertEqual(sorted(os.listdir(os.path.join(self.root, "b"))), ["y"])
    self.assertEqual(self.read("c"), "now a file")
    self.assertFalse([n for _, _, files in os.walk(self.root) for n in files if n.startswith(".wh.")])

  def test_symlinks_resolve_inside_rootfs(self):
    outside = os.path.join(self.tmp.name, "outside")
    self.apply([("usr", "dir", None), ("usr/lib", "dir", None), ("lib", "symlink", "usr/lib"),
                ("abs", "symlink", "/usr"), ("up", "symlink", "../../../.."),
                ("esc", "symlink", outside)])
    self.apply([("lib/a.so", "file", "a"), ("abs/b", "file", "b"), ("up/c", "file", "c"),
                ("esc/d", "file", "d")])
    self.assertEqual(self.read("usr", "lib", "a.so"), "a")
    self.assertEqual(self.read("usr", "b"), "b")
    self.assertEqual(self.read("c"), "c")    # '..' stops at the root
    self.assertFalse(os.path.exists(outside))
    self.assertEqual(self.read(*outside.strip("/").split("/"), "d"), "d")
    # Symlinks themselves are kept as they are, for the container to resolve.
    self.assertEqual(os.readlink(os.path.join(self.root, "esc")), outside)

  def test_escaping_paths_are_refused(self):
    for name in ("../evil", "a/../../evil", "/etc/evil"):
      with self.assertRaises(ImageError, msg=name):
        self.apply([(name, "file", "x")])
    with self.assertRaises(ImageError):
      self.apply([("f", "file", "x"), ("h", "hardlink", "../f")])
    self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "evil")))

  def test_hardlinks_and_modes(self):
    self.apply([("bin", "dir", None), ("bin/a", "file", "same"), ("bin/b", "hardlink", "bin/a")])
    st_a, st_b = (os.stat(os.path.join(self.root, "bin", n)) for n in "ab")
    self.assertEqual(st_a.st_ino, st_b.st_ino)
    self.assertEqual(st_a.st_mode & 0o777, 0o644)

  def test_resolve_in_root(self):
    os.makedirs(os.path.join(self.root, "x", "y"))
    os.symlink("/x", os.path.join(self.root, "lx"))
    self.assertEqual(resolve_in_root(self.root, ["lx", "y"]), os.path.join(self.root, "x", "y"))
    self.assertIsNone(resolve_in_root(self.root, ["missing"]))
    os.symlink("loop", os.path.join(self.root, "loop"))
    with self.assertRaises(ImageError):
      resolve_in_root(self.root, ["loop"])


class ReferenceTestCase(unittest.TestCase):
  def test_parse_image_reference(self):
    self.assertEqual(parse_image_reference("registry.cern.ch/alisw/slc9-builder"),
                     ("registry.cern.ch", "alisw/slc9-builder", "latest"))
    self.assertEqual(parse_image_reference("localhost:5000/a/b:v1"), ("localhost:5000", "a/b", "v1"))
    self.assertEqual(parse_image_reference("alpine"), ("registry-1.docker.io", "library/alpine", "latest"))
    self.assertEqual(parse_image_reference("alisw/x@sha256:ab"), ("registry-1.docker.io", "alisw/x", "sha256:ab"))

  def test_select_platform(self):
    index = {"manifests": [{"digest": "sha256:x86", "platform": {"os": "linux", "architecture": "amd64"}},
                           {"digest": "sha256:arm", "platform": {"os": "linux", "architecture": "arm64",
                                                                 "variant": "v8"}}]}
    self.assertEqual(select_platform(index, "linux/arm64"), "sha256:arm")
    self.assertEqual(select_platform(index, "linux/amd64"), "sha256:x86")
    with self.assertRaises(ImageError):
      select_platform(index, "linux/ppc64le")

  def test_parse_volume(self):
    self.assertEqual(parse_volume("/a:/b:ro"), ("/a", "/b", True))
    self.assertEqual(parse_volume("/a:/b"), ("/a", "/b", False))
    self.assertEqual(parse_volume("/a"), ("/a", "/a", False))


class FakeRegistry:
  """Serves one single-layer image; counts blob downloads."""

  def __init__(self, layer):
    self.layer, self.downloads = layer, 0
    self.config = json.dumps({"config": {"Env": ["PATH=/opt/bin:/usr/bin", "LANG=C"],
                                         "WorkingDir": "/work"}}).encode()

  def manifest(self, reference):
    return ("application/vnd.docker.distribution.manifest.v2+json", "sha256:" + "1" * 64,
            {"config": {"digest": "sha256:cfg"}, "layers": [{"digest": "sha256:layer", "size": 1}]})

  def blob(self, digest, dest):
    self.downloads += 1
    with open(dest, "wb") as f:
      if digest == "sha256:cfg":
        f.write(self.config)
      else:
        with open(self.layer, "rb") as layer:
          f.write(layer.read())


class ImageCacheTestCase(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.cache = os.path.join(self.tmp.name, "CONTAINERS")
    self.registry = FakeRegistry(make_layer(os.path.join(self.tmp.name, "l.tar.gz"),
                                            [("etc", "dir", None), ("etc/os-release", "file", "x")]))
    patcher = mock.patch("alibuild_helpers.bwrap.Registry", new=lambda *a: self.registry)
    patcher.start()
    self.addCleanup(patcher.stop)

  def tearDown(self):
    self.tmp.cleanup()

  def test_unpack_once_and_reuse(self):
    image = Image("registry.cern.ch/alisw/slc9-builder:latest", self.cache, "linux/arm64")
    # A partial unpack left by an interrupted run is cleaned up.
    os.makedirs(os.path.join(self.cache, "sha256-" + "1" * 64 + ".tmp-dead", "rootfs"))
    self.assertEqual(image.resolve(), "registry.cern.ch/alisw/slc9-builder@sha256:" + "1" * 64)
    with open(os.path.join(image.rootfs, "etc", "os-release")) as f:
      self.assertEqual(f.read(), "x")
    self.assertEqual(image.config["WorkingDir"], "/work")
    self.assertEqual(sorted(os.listdir(self.cache)), ["refs", "sha256-" + "1" * 64, "sha256-" + "1" * 64 + ".lock"])
    downloads = self.registry.downloads
    again = Image("registry.cern.ch/alisw/slc9-builder:latest", self.cache, "linux/arm64")
    self.assertEqual(again.rootfs, image.rootfs)
    self.assertEqual(self.registry.downloads, downloads)

  def test_offline_uses_last_resolved_digest(self):
    Image("alisw/x", self.cache, "linux/arm64").ensure()
    self.registry.manifest = mock.MagicMock(side_effect=OSError("no network"))
    with mock.patch("alibuild_helpers.bwrap.warning"):
      offline = Image("alisw/x", self.cache, "linux/arm64")
      self.assertEqual(offline.resolve(), "alisw/x@sha256:" + "1" * 64)
      self.assertTrue(os.path.isdir(offline.rootfs))
    with self.assertRaises(ImageError):
      Image("alisw/never-pulled", self.cache, "linux/arm64").resolve()


class FakeImage:
  rootfs = "/cache/rootfs"
  config = {"Env": ["PATH=/opt/bin:/usr/bin", "FOO=image"], "WorkingDir": "/work"}


@mock.patch("alibuild_helpers.bwrap.proc_args", new=lambda host_proc=False: ("--proc", "/proc"))
class CommandTestCase(unittest.TestCase):
  def test_bwrap_command(self):
    cmd = bwrap_command(FakeImage(), [("/w", "/sw", False), ("/c", "/alidist", True)], [("FOO", "env")])
    self.assertEqual(cmd[:7], ["bwrap", "--unshare-user", "--unshare-pid", "--unshare-ipc",
                               "--unshare-uts", "--die-with-parent", "--new-session"])
    self.assertNotIn("--unshare-net", cmd)
    joined = " ".join(cmd)
    self.assertIn("--bind /cache/rootfs / --proc /proc --dev /dev --tmpfs /tmp", joined)
    self.assertIn("--bind /w /sw --ro-bind /c /alidist --remount-ro /", joined)
    # The image's environment applies, then ours overrides it.
    self.assertLess(joined.index("--setenv FOO image"), joined.index("--setenv FOO env"))
    self.assertIn("--setenv PATH /opt/bin:/usr/bin", joined)
    self.assertEqual(cmd[-2:], ["--chdir", "/work"])
    self.assertIn("--unshare-net", bwrap_command(FakeImage(), network=False))

  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.work = os.path.join(self.tmp.name, "sw")
    self.spec = {"package": "zlib", "version": "v1.3.1", "revision": "1", "hash": "abcdef1234",
                 "tag": "v1.3.1", "commit_hash": "v1.3.1", "build_family": "fam",
                 "reference": "/mirror/zlib", "is_devel_pkg": False}

  def run_string(self, sandbox=False, **kwargs):
    args = mock.MagicMock(sandbox=sandbox, architecture="slc9_aarch64", develPrefix=None,
                          containerNetwork="host", containerAllowHostProc=False, workDir=self.work,
                          sandboxAllowWrite=[])
    for k, v in kwargs.items():
      setattr(args, k, v)
    run = bwrap_run_string(FakeImage(), args, "img", self.work, "/alidist-host", self.work + "/SPECS/x",
                           [], self.spec, {"zlib": self.spec}, ["/data:/data:ro"],
                           [("PKGNAME", "zlib"), ("WEIRD", "a b'c")])
    args = shlex.split(run)
    self.assertEqual(args[-3:], ["bash", "-ex", "/build.sh"])
    return " ".join(args), args

  def test_run_string(self):
    w = self.work
    with open(os.path.join(self.tmp.name, "stale"), "w"):
      pass
    joined, _ = self.run_string()
    for expected in ("--bind %s /sw --ro-bind %s/CONTAINERS /sw/CONTAINERS" % (w, w),
                     "--ro-bind /alidist-host /alidist",
                     "--ro-bind %s/SPECS/x/build.sh /build.sh --bind /mirror /mirror" % w,
                     # /tmp is on disk, and TMP/<hash> is a mount point build.sh cannot remove
                     "--dev /dev --bind %s/TMP/abcdef1234 /tmp" % w,
                     "--bind %s/TMP/abcdef1234 /sw/TMP/abcdef1234" % w,
                     "--ro-bind /data /data", "--setenv PKGNAME zlib", "--setenv WEIRD a b'c",
                     "--setenv WORK_DIR_OVERRIDE /sw", "--setenv ALIBUILD_CONFIG_DIR_OVERRIDE /alidist",
                     "--setenv TMPDIR /tmp"):
      self.assertIn(expected, joined)
    self.assertNotIn("--tmpfs", joined)
    self.assertEqual(os.listdir(os.path.join(w, "TMP", "abcdef1234")), [])

  def test_sandbox_binds(self):
    w = self.work
    os.makedirs(os.path.join(w, "SOURCES", "zlib", "v1.3.1", "v1.3.1"))   # checked out
    joined, args = self.run_string(sandbox=True)
    self.assertIn("--ro-bind %s /sw --ro-bind %s/CONTAINERS /sw/CONTAINERS" % (w, w), joined)
    self.assertIn("--ro-bind /mirror /mirror", joined)
    writable = [(args[i + 1], args[i + 2]) for i, a in enumerate(args) if a == "--bind"]
    rel = ["BUILD/abcdef1234", "INSTALLROOT/abcdef1234", "TMP/abcdef1234",
           "TARS/slc9_aarch64/store/ab/abcdef1234", "TARS/slc9_aarch64/zlib",
           "slc9_aarch64/zlib/v1.3.1-1", "SOURCES/zlib/v1.3.1/v1.3.1"]
    self.assertEqual(writable, [("/cache/rootfs", "/"), (w + "/TMP/abcdef1234", "/tmp")] +
                     [(os.path.join(w, r), "/sw/" + r) for r in rel])
    # The sources and directories exist, as bwrap needs; the BUILD link is made.
    for r in rel + ["SOURCES", "SPECS"]:
      self.assertTrue(os.path.isdir(os.path.join(w, r)), r)
    self.assertEqual(os.readlink(os.path.join(w, "BUILD", "zlib-latest")), "abcdef1234")
    # The package's other versions stay read-only; the links there are set
    # only once the build has succeeded.
    self.assertNotIn(" /sw/slc9_aarch64/zlib ", " %s " % joined)
    self.assertFalse(os.path.lexists(os.path.join(w, "slc9_aarch64", "zlib", "latest")))
    args = mock.MagicMock(workDir=w, architecture="slc9_aarch64", develPrefix=None)
    bwrap.set_links(self.spec, args, done=True)
    for link in ("latest", "latest-fam"):
      self.assertEqual(os.readlink(os.path.join(w, "slc9_aarch64", "zlib", link)), "v1.3.1-1")
    # Not checked out (e.g. unpacking a tarball): no SOURCEDIR bind.
    os.rmdir(os.path.join(w, "SOURCES", "zlib", "v1.3.1", "v1.3.1"))
    self.assertNotIn("SOURCES", self.run_string(sandbox=True)[0])

  def test_sandbox_allow_write_and_hint(self):
    extra = os.path.join(self.tmp.name, "extra")
    os.mkdir(extra)
    with mock.patch("alibuild_helpers.bwrap.warning") as warn:
      joined, _ = self.run_string(sandbox=True, sandboxAllowWrite=[extra, "/does/not/exist"])
    self.assertIn("--bind %s %s" % (extra, extra), joined)
    warn.assert_called_once()
    args = mock.MagicMock(workDir=self.work, architecture="slc9_aarch64", develPrefix=None)
    hint = bwrap.bwrap_failure_hint(self.spec, args, "BUILD/zlib-latest/log")
    self.assertIn(os.path.join(self.work, "INSTALLROOT", "abcdef1234"), hint)
    self.assertIn("grep 'Read-only file system' BUILD/zlib-latest/log", hint)

  def test_runtime_takes_platform_from_docker_extra_args(self):
    args = mock.MagicMock(workDir="/w", dockerImage="img", docker_extra_args=["--platform", "linux/arm64", "--x"],
                          containerNetwork="none")
    bwrap._images.clear()
    runner, run_string = bwrap.runtime(args)
    self.assertEqual(bwrap.get_image(args).platform, "linux/arm64")
    self.assertEqual(bwrap.get_image(args).cache_dir, "/w/CONTAINERS")
    self.assertEqual(runner("img", [])._run_args, ["--x"])
    bwrap._images.clear()


class ProcTestCase(unittest.TestCase):
  def setUp(self):
    bwrap.proc_args.cache_clear()
    self.addCleanup(bwrap.proc_args.cache_clear)

  def test_fresh_proc_by_default(self):
    with mock.patch("alibuild_helpers.bwrap.fresh_proc", new=lambda: (True, "")):
      self.assertEqual(bwrap.proc_args(), ("--proc", "/proc"))

  def test_host_proc_needs_opt_in(self):
    with mock.patch("alibuild_helpers.bwrap.fresh_proc", new=lambda: (False, "EPERM")), \
         mock.patch("alibuild_helpers.bwrap.shutil.which", new=lambda _: "/usr/bin/bwrap"), \
         mock.patch("alibuild_helpers.bwrap.getstatusoutput", new=lambda _: (0, "")), \
         mock.patch("alibuild_helpers.bwrap.warning") as warn:
      self.assertIn("--container-allow-host-proc", bwrap.bwrap_check())
      self.assertIsNone(bwrap.bwrap_check(host_proc=True))
      with self.assertRaises(SystemExit):
        bwrap.proc_args()
      self.assertEqual(bwrap.proc_args(True), ("--ro-bind", "/proc", "/proc"))
      warn.assert_called_once()


if __name__ == '__main__':
  unittest.main()
