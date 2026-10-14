from unittest import mock
from unittest.mock import patch
import os
import shlex
import subprocess
import sys
import tempfile
import unittest

from alibuild_helpers.args import doParseArgs
from alibuild_helpers.sandbox import (sandbox_check, sandbox_paths, sandbox_profile,
                                      sandboxed_command, sandbox_failure_hint)

SPEC = {
  "package": "zlib",
  "version": "v1.2.3",
  "revision": "1",
  "hash": "abcdef0123456789",
  "commit_hash": "0123456789abcdef0123",
  "tag": "v1.2.3",
  "build_family": "o2",
}


def fake_getconf(argv, stderr=None):
  return {"DARWIN_USER_TEMP_DIR": b"/var/folders/xx/T/\n",
          "DARWIN_USER_CACHE_DIR": b"/var/folders/xx/C/\n"}[argv[1]]


@patch("alibuild_helpers.sandbox.subprocess.check_output", new=fake_getconf)
@patch("alibuild_helpers.sandbox.realpath", new=lambda p: p)
class SandboxPathsTestCase(unittest.TestCase):
  def test_package_areas(self) -> None:
    subpaths, literals, directories = sandbox_paths(SPEC, "/sw", "/sw", "osx_arm64", "", environ={})
    for path in ("/sw/BUILD/abcdef0123456789",
                 "/sw/INSTALLROOT/abcdef0123456789",
                 "/sw/TMP/abcdef0123456789",
                 "/sw/TARS/osx_arm64/store/ab/abcdef0123456789",
                 "/sw/TARS/osx_arm64/zlib",
                 "/sw/osx_arm64/zlib/v1.2.3-1",
                 "/sw/SOURCES/zlib/v1.2.3/0123456789",
                 "/var/folders/xx/T", "/var/folders/xx/C"):
      self.assertIn(path, subpaths)
    self.assertEqual(literals, ["/sw/BUILD/zlib-latest", "/sw/osx_arm64/zlib/latest",
                                "/sw/osx_arm64/zlib/latest-o2"])
    # Neither the work directory nor other packages' areas are writable...
    for path in subpaths:
      self.assertNotIn(path, ("/sw", "/sw/BUILD", "/sw/osx_arm64", "/sw/osx_arm64/zlib", "/sw/SOURCES"))
    # ...but the parents of what the build creates can be created and updated.
    for path in ("/sw", "/sw/BUILD", "/sw/osx_arm64", "/sw/osx_arm64/zlib",
                 "/sw/TARS/osx_arm64/store/ab"):
      self.assertIn(path, directories)
    self.assertNotIn("/", directories)

  def test_devel_and_build_work_dir(self) -> None:
    subpaths, literals, directories = sandbox_paths(
      SPEC, "/sw", "/scratch", "osx_arm64", "main",
      extra_writable=["/opt/cache"], environ={"CCACHE_DIR": "/ccache"})
    self.assertIn("/scratch/BUILD/abcdef0123456789", subpaths)
    self.assertNotIn("/sw/BUILD/abcdef0123456789", subpaths)
    self.assertIn("/opt/cache", subpaths)
    self.assertIn("/ccache", subpaths)
    self.assertIn("/scratch/BUILD/zlib-latest-main", literals)
    self.assertIn("/scratch/BUILD", directories)

  def test_profile(self) -> None:
    profile = sandbox_profile(["/sw/BUILD/x", 'odd "dir"'], ["/sw/BUILD/z-latest"], ["/sw"])
    self.assertIn("(allow default)\n(deny file-write*)\n(allow file-write*\n", profile)
    self.assertIn('  (subpath "/sw/BUILD/x")\n', profile)
    self.assertIn('  (subpath "odd \\"dir\\"")\n', profile)
    self.assertIn('  (literal "/sw/BUILD/z-latest")\n', profile)
    self.assertIn('  (literal "/sw"))\n', profile)
    self.assertEqual(profile.count("("), profile.count(")"))

  def test_command(self) -> None:
    self.assertEqual(sandboxed_command("/a b/sandbox.sb", "/bin/bash -e -x build.sh 2>&1"),
                     "/usr/bin/sandbox-exec -f '/a b/sandbox.sb' /bin/bash -e -x build.sh 2>&1")
    self.assertIn("/sw/SPECS/x/sandbox.sb", sandbox_failure_hint("/sw/SPECS/x", "sw/BUILD/x/log"))


@mock.patch("alibuild_helpers.utilities.getoutput", new=lambda cmd: "arm64")   # for uname -m
@mock.patch("alibuild_helpers.args.commands")
@mock.patch("alibuild_helpers.args.argparse.ArgumentParser.error", side_effect=SystemExit)
class SandboxArgsTestCase(unittest.TestCase):
  def parse(self, cmd, platform="darwin", environ=None, problem=None):
    with patch.object(sys, "argv", ["alibuild"] + shlex.split(cmd)), \
         patch.object(sys, "platform", platform), \
         patch.dict(os.environ, environ or {}), \
         patch("alibuild_helpers.args.sandbox_check", return_value=problem):
      if not environ:
        os.environ.pop("ALIBUILD_SANDBOX", None)
      return doParseArgs()[0]

  def test_flags(self, error, commands) -> None:
    commands.getstatusoutput.return_value = (0, "")
    self.assertFalse(self.parse("build zlib -a osx_arm64").sandbox)
    args = self.parse("build zlib -a osx_arm64 --sandbox --sandbox-allow-write /x")
    self.assertTrue(args.sandbox)
    self.assertEqual(args.sandboxAllowWrite, ["/x"])
    self.assertTrue(self.parse("build zlib -a osx_arm64", environ={"ALIBUILD_SANDBOX": "1"}).sandbox)
    self.assertFalse(self.parse("build zlib -a osx_arm64 --no-sandbox", environ={"ALIBUILD_SANDBOX": "1"}).sandbox)
    self.assertFalse(self.parse("build zlib -a osx_arm64", environ={"ALIBUILD_SANDBOX": "0"}).sandbox)
    # The environment only enables it where it is possible...
    self.assertFalse(self.parse("build zlib -a slc9_x86-64", platform="linux",
                                environ={"ALIBUILD_SANDBOX": "1"}).sandbox)
    self.assertFalse(self.parse("build zlib -a slc9_x86-64 --docker",
                                environ={"ALIBUILD_SANDBOX": "1"}).sandbox)
    error.assert_not_called()

  def test_errors(self, error, commands) -> None:
    commands.getstatusoutput.return_value = (0, "")
    # ...while asking for it explicitly where it is not, is an error.
    with self.assertRaises(SystemExit):
      self.parse("build zlib -a slc9_x86-64 --docker --sandbox")
    self.assertIn("--docker", error.call_args[0][0])
    with self.assertRaises(SystemExit):
      self.parse("build zlib -a osx_arm64 --sandbox", problem="nested")
    self.assertEqual(error.call_args[0][0], "cannot use --sandbox: nested")


@unittest.skipIf(sandbox_check() is not None, "seatbelt not usable here")
class SandboxExecTestCase(unittest.TestCase):
  def test_confinement(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
      tmp = os.path.realpath(tmp)
      allowed, denied = os.path.join(tmp, "allowed"), os.path.join(tmp, "denied")
      os.mkdir(allowed)
      profile = os.path.join(tmp, "sandbox.sb")
      with open(profile, "w") as f:
        f.write(sandbox_profile([allowed], [], []))

      def run(target):
        return subprocess.call(sandboxed_command(profile, "/bin/sh -c 'echo x > %s'" % target),
                               shell=True, stderr=subprocess.DEVNULL)
      self.assertEqual(run(os.path.join(allowed, "file")), 0)
      self.assertNotEqual(run(denied), 0)
      self.assertFalse(os.path.exists(denied))


if __name__ == '__main__':
  unittest.main()
