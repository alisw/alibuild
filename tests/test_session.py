import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from os.path import isdir, islink, join
from unittest.mock import Mock, patch

from alibuild_helpers import cow
from alibuild_helpers.session import (REEXEC_ENV, add_parser, doSession, describe, list_sessions,
                                      merged_refs, reexec_session_alibuild, seed_from, worktrees)


class CopyBackend(cow.CloneBackend):
  """Stands in for a copy-on-write backend: copies, keeping mtimes."""
  name = "test-copy"

  def unavailable_reason(self, src, dst):
    return None

  def clone_tree(self, src, dst):
    if isdir(src) and not islink(src):
      shutil.copytree(src, dst, symlinks=True)
    else:
      shutil.copy2(src, dst, follow_symlinks=False)


def event(action, package, ref):
  return {"time": "t", "action": action, "package": package, "ref": ref, "commit": "c"}


class MergedRefsTestCase(unittest.TestCase):
  def test_merged_refs(self) -> None:
    events = [{"time": "t", "action": "create", "package": "O2", "commit": "c"},
              event("add", "O2", "alisw/O2#1"),
              event("add", "O2", "alisw/O2#2"),
              event("add", "O2Physics", "alisw/O2#1"),
              event("remove", "O2", "alisw/O2#1")]
    self.assertEqual([(e["package"], e["ref"]) for e in merged_refs(events)],
                     [("O2", "alisw/O2#2"), ("O2Physics", "alisw/O2#1")])
    # Adding it back counts, as the latest addition.
    events.append(event("add", "O2", "alisw/O2#1"))
    self.assertEqual([(e["package"], e["ref"]) for e in merged_refs(events)],
                     [("O2", "alisw/O2#2"), ("O2Physics", "alisw/O2#1"), ("O2", "alisw/O2#1")])


class SessionTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self.cwd = os.getcwd()
    self.tmp = tempfile.TemporaryDirectory()
    os.chdir(self.tmp.name)
    self.parser = argparse.ArgumentParser()
    add_parser(self.parser.add_subparsers(dest="action"), "sw", ".")
    # Sessions get a copy of this aliBuild, an installed one unless a test makes it a checkout.
    os.makedirs("src/alibuild/alibuild_helpers")
    for name in ("src/alibuild/aliBuild", "src/alibuild/alibuild_helpers/__init__.py"):
      open(name, "w").close()
    running = patch("alibuild_helpers.session.running_alibuild", return_value=os.path.abspath("src/alibuild"))
    running.start()
    self.addCleanup(running.stop)

  def tearDown(self) -> None:
    os.chdir(self.cwd)
    self.tmp.cleanup()

  def run_session(self, *argv):
    out = io.StringIO()
    with redirect_stdout(out):
      ok = doSession(self.parser.parse_args(["session", *argv]), self.parser)
    return ok, out.getvalue()

  def git(self, *args, cwd="O2"):
    subprocess.check_call(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

  def test_worktrees_and_list(self) -> None:
    for d in ("O2", "O2@s1", "ROOT@s1", "O2@s2", "sw/SESSIONS"):
      os.makedirs(d)
    open("O2@file", "w").close()
    with open("sw/SESSIONS/s3.json", "w") as f:
      f.write("{}")
    self.assertEqual(worktrees("s1"), {"O2": "./O2@s1", "ROOT": "./ROOT@s1"})
    self.assertEqual(worktrees("s3"), {})
    self.assertEqual(list_sessions("sw"), ["s1", "s2", "s3"])

  def test_session(self) -> None:
    os.mkdir("O2")
    self.git("init", "-q")
    self.git("commit", "-q", "--allow-empty", "-m", "init")
    self.assertTrue(self.run_session("create", "s1", "O2")[0])
    self.assertTrue(os.path.isdir("O2@s1"))
    # Creating it again only adds worktrees, and it only records worktrees it has.
    self.assertFalse(self.run_session("create", "s1")[0])
    self.assertFalse(self.run_session("create", "s1", "O2")[0])
    os.mkdir("alidist")
    self.git("init", "-q", cwd="alidist")
    self.git("commit", "-q", "--allow-empty", "-m", "init", cwd="alidist")
    self.assertTrue(self.run_session("create", "s1", "O2", "alidist")[0])
    self.assertEqual(sorted(worktrees("s1")), ["O2", "alidist"])
    self.assertFalse(self.run_session("add", "s1", "ROOT", "alisw/root#1")[0])
    self.assertFalse(self.run_session("add", "s2", "O2", "alisw/O2#1")[0])

    self.git("commit", "-q", "--allow-empty", "-m", "PR 1", cwd="O2@s1")
    self.assertTrue(self.run_session("add", "s1", "O2", "alisw/O2#1")[0])
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd="O2@s1", text=True).strip()
    os.makedirs("sw/BUILD")
    os.symlink("0123abcd", "sw/BUILD/O2-latest-s1")

    session = describe("sw", "s1")
    self.assertEqual([(t["package"], t["commit"], t["build"]) for t in session["worktrees"]][0],
                     ("O2", commit, "0123abcd"))
    self.assertEqual([(e["ref"], e["commit"]) for e in session["merged"]],
                     [("alisw/O2#1", commit)])
    self.assertEqual([(e["action"], e["package"]) for e in session["events"]],
                     [("create", "O2"), ("create", "alidist"), ("add", "O2")])

    ok, out = self.run_session("show", "s1", "--json")
    self.assertTrue(ok)
    self.assertEqual(json.loads(out)["merged"], session["merged"])
    ok, out = self.run_session("show", "s1")
    self.assertIn("O2@s1 at %s, last built as 0123abcd" % commit[:12], out)
    self.assertIn("O2: alisw/O2#1 (at %s" % commit[:12], out)

    self.assertTrue(self.run_session("remove", "s1", "O2", "alisw/O2#1")[0])
    self.assertEqual(describe("sw", "s1")["merged"], [])
    self.assertFalse(self.run_session("show", "nothing")[0])

  def test_seed_from(self) -> None:
    os.mkdir("O2")
    self.git("init", "-q")
    self.git("commit", "-q", "--allow-empty", "-m", "init")
    # Only from another session which exists.
    self.assertFalse(self.run_session("create", "s1", "O2", "--seed-from", "s0")[0])
    self.assertTrue(self.run_session("create", "s0", "O2")[0])
    self.assertFalse(self.run_session("create", "s1", "O2", "--seed-from", "s1")[0])
    self.assertFalse(os.path.exists("sw/SESSIONS/s1.json"))
    self.assertTrue(self.run_session("create", "s1", "O2", "--seed-from", "s0")[0])
    self.assertEqual(seed_from("sw", "s1"), "s0")
    self.assertIsNone(seed_from("sw", "s0"))
    self.assertIsNone(seed_from("sw", None))
    self.assertIn("seeded from s0", self.run_session("show", "s1")[1])
    # Creating it again with --seed-from changes it.
    self.assertTrue(self.run_session("create", "s2")[0])
    self.assertTrue(self.run_session("create", "s1", "--seed-from", "s2")[0])
    self.assertEqual(seed_from("sw", "s1"), "s2")

  def test_drop(self) -> None:
    os.mkdir("O2")
    self.git("init", "-q")
    self.git("commit", "-q", "--allow-empty", "-m", "init")
    self.assertTrue(self.run_session("create", "s1", "O2")[0])
    os.makedirs("sw/BUILD")
    os.makedirs("sw/osx_arm64/O2")
    links = {"sw/BUILD/O2-latest-s1": "0123",
             "sw/osx_arm64/O2/latest-s1-o2": "s1-local1",
             # These belong to other sessions, or to none.
             "sw/BUILD/O2-latest-s1-x": "4567",
             "sw/BUILD/O2-latest": "89ab",
             "sw/osx_arm64/O2/latest-s1-x-o2": "s1-x-local1",
             "sw/osx_arm64/O2/latest": "s1-local1"}
    for link, target in links.items():
      os.symlink(target, link)
    dropped = ["sw/BUILD/O2-latest-s1", "sw/osx_arm64/O2/latest-s1-o2"]

    # Uncommitted changes keep the worktrees, and everything else, in place.
    with open("O2@s1/file", "w") as f:
      f.write("work")
    self.assertFalse(self.run_session("drop", "s1", "--worktrees")[0])
    self.assertTrue(all(os.path.islink(l) for l in links))
    os.unlink("O2@s1/file")

    # Without --worktrees, only the links and the record go.
    self.assertTrue(self.run_session("drop", "s1")[0])
    self.assertEqual([l for l in links if not os.path.islink(l)], dropped)
    self.assertFalse(os.path.exists("sw/SESSIONS/s1.json"))
    self.assertTrue(os.path.isdir("O2@s1"))
    self.assertTrue(self.run_session("drop", "s1", "--worktrees")[0])
    self.assertFalse(os.path.exists("O2@s1"))
    self.assertFalse(self.run_session("drop", "s1")[0])

  def test_git_repository_used_by_sapling(self) -> None:
    # A git repository Sapling has been used on (.git/sl) is still shared with
    # a git worktree: sl share cannot share a git-format repository.
    os.mkdir("O2")
    self.git("init", "-q")
    self.git("commit", "-q", "--allow-empty", "-m", "init")
    os.mkdir("O2/.git/sl")
    with patch("alibuild_helpers.session.scm_for") as scm:
      scm.return_value.checkedOutCommitName.side_effect = lambda directory: subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=directory, text=True).strip()
      self.assertTrue(self.run_session("create", "s1", "O2")[0])
    self.assertTrue(os.path.isfile("O2@s1/.git"))  # a git worktree's .git is a file

  def make_checkout(self, init, commit):
    """O2, committed, with a file changed since, one untracked and one ignored."""
    os.makedirs("O2/src")
    for name, data in (("src/same", "same"), ("src/changed", "committed"), (".gitignore", "*.log\n")):
      with open(join("O2", name), "w") as f:
        f.write(data)
    os.symlink("src/same", "O2/link")
    init()
    commit()
    with open("O2/src/changed", "w") as f:
      f.write("changed")
    for name in ("untracked", "ignored.log"):
      open(join("O2", name), "w").close()
    for name in ("src/same", "src/changed"):
      os.utime(join("O2", name), ns=(1, 1000000000))

  def check_worktree(self, cloned):
    self.assertEqual(sorted(set(os.listdir("O2@s1")) - {".git", ".sl"}), [".gitignore", "link", "src"])
    self.assertEqual(os.readlink("O2@s1/link"), "src/same")
    with open("O2@s1/src/changed") as f:
      self.assertEqual(f.read(), "committed")
    self.assertEqual(os.stat("O2@s1/src/same").st_mtime_ns == 1000000000, cloned)
    self.assertNotEqual(os.stat("O2@s1/src/changed").st_mtime_ns, 1000000000)

  def git_checkout(self):
    self.make_checkout(lambda: self.git("init", "-q"),
                       lambda: (self.git("add", "-A"), self.git("commit", "-q", "-m", "init")))

  def test_cloned_git_worktree(self) -> None:
    self.git_checkout()
    with patch.object(cow, "BACKENDS", [CopyBackend()]):
      self.assertTrue(self.run_session("create", "s1", "O2")[0])
    self.check_worktree(cloned=True)
    self.assertEqual(subprocess.check_output(["git", "status", "--porcelain"], cwd="O2@s1"), b"")
    self.assertIn(b"O2@s1", subprocess.check_output(["git", "worktree", "list"], cwd="O2"))

  def test_git_worktree_not_cloned(self) -> None:
    self.git_checkout()
    with patch.object(cow, "BACKENDS", [cow.NoClone()]):
      self.assertTrue(self.run_session("create", "s1", "O2")[0])
    self.check_worktree(cloned=False)
    self.assertEqual(subprocess.check_output(["git", "status", "--porcelain"], cwd="O2@s1"), b"")
    # Nor is a checkout in the middle of an operation.
    open("O2/.git/MERGE_HEAD", "w").close()
    with patch.object(cow, "BACKENDS", [CopyBackend()]):
      self.assertTrue(self.run_session("create", "s2", "O2")[0])
    self.assertNotEqual(os.stat("O2@s2/src/same").st_mtime_ns, 1000000000)

  @unittest.skipUnless(shutil.which("sl"), "needs Sapling")
  def test_cloned_sapling_share(self) -> None:
    def sl(*args, cwd="O2"):
      return subprocess.check_output(["sl", "--config", "ui.username=t <t@t>", *args], cwd=cwd)
    self.make_checkout(lambda: sl("init", "-q", "O2", cwd="."),
                       lambda: (sl("add", "-q"), sl("commit", "-q", "-m", "init")))
    with patch.object(cow, "BACKENDS", [CopyBackend()]):
      self.assertTrue(self.run_session("create", "s1", "O2")[0])
    self.check_worktree(cloned=True)
    self.assertEqual(sl("status", cwd="O2@s1"), b"")
    self.assertEqual(sl("log", "-r", ".", "-T", "{node}", cwd="O2@s1"), sl("log", "-r", ".", "-T", "{node}"))
    # It is a share: what is committed in it is in O2.
    sl("commit", "-q", "-m", "in s1", "--config", "ui.allowemptycommit=true", cwd="O2@s1")
    self.assertIn(b"in s1", sl("log", "-r", "all()", "-T", "{desc}\\n"))

  def test_invalid_name(self) -> None:
    with patch.object(self.parser, "error", side_effect=SystemExit) as error, \
         self.assertRaises(SystemExit):
      self.run_session("create", "a/b")
    self.assertIn("invalid session name", error.call_args[0][0])

  def alibuild(self, session="s1"):
    with open(f"sw/SESSIONS/{session}.json") as f:
      return json.load(f).get("alibuild")

  def test_alibuild_git_worktree(self) -> None:
    self.git("init", "-q", cwd="src/alibuild")
    self.git("add", "-A", cwd="src/alibuild")
    self.git("commit", "-q", "-m", "v1", cwd="src/alibuild")
    first = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd="src/alibuild", text=True).strip()
    with open("src/alibuild/aliBuild", "w") as f:
      f.write("v2")
    self.git("commit", "-q", "-am", "v2", cwd="src/alibuild")
    with open("src/alibuild/aliBuild", "w") as f:
      f.write("uncommitted")
    # By default, at the commit checked out, without what is not committed.
    self.assertTrue(self.run_session("create", "s1")[0])
    copy = self.alibuild()
    self.assertEqual((copy["kind"], copy["path"]), ("git", os.path.abspath("sw/SESSIONS/s1/alibuild")))
    with open("sw/SESSIONS/s1/alibuild/aliBuild") as f:
      self.assertEqual(f.read(), "v2")
    self.assertIn("aliBuild: %s, git of" % copy["path"], self.run_session("show", "s1")[1])
    self.assertEqual(json.loads(self.run_session("show", "s1", "--json")[1])["alibuild"], copy)
    # Or at the commit asked for, which an existing copy cannot change to.
    self.assertTrue(self.run_session("create", "s2", "--alibuild-rev", first)[0])
    self.assertEqual(self.alibuild("s2")["commit"], first)
    self.assertFalse(self.run_session("create", "s2", "--alibuild-rev", first)[0])
    self.assertFalse(self.run_session("create", "s3", "--alibuild-rev", "nothing")[0])
    # Dropping the session removes the worktree from the repository too.
    self.assertTrue(self.run_session("drop", "s1")[0])
    self.assertFalse(os.path.exists("sw/SESSIONS/s1"))
    self.assertNotIn(b"SESSIONS/s1", subprocess.check_output(["git", "worktree", "list"], cwd="src/alibuild"))

  @unittest.skipUnless(shutil.which("sl"), "needs Sapling")
  def test_alibuild_sapling_share(self) -> None:
    def sl(*args, cwd="src/alibuild"):
      return subprocess.check_output(["sl", "--config", "ui.username=t <t@t>", *args], cwd=cwd)
    shutil.rmtree("src/alibuild")
    sl("init", "-q", "src/alibuild", cwd=".")
    with open("src/alibuild/aliBuild", "w") as f:
      f.write("v1")
    sl("commit", "-q", "-A", "-m", "v1")
    self.assertTrue(self.run_session("create", "s1")[0])
    copy = self.alibuild()
    self.assertEqual((copy["kind"], copy["commit"]), ("sl", sl("log", "-r", ".", "-T", "{node}").decode()))
    self.assertEqual(sl("log", "-r", ".", "-T", "{node}", cwd=copy["path"]).decode(), copy["commit"])
    self.assertTrue(self.run_session("drop", "s1")[0])
    self.assertFalse(os.path.exists("sw/SESSIONS/s1"))

  def test_alibuild_installed(self) -> None:
    with patch.object(cow, "BACKENDS", [CopyBackend()]):
      self.assertTrue(self.run_session("create", "s1")[0])
      # Without a checkout, there is no other commit to take.
      self.assertFalse(self.run_session("create", "s2", "--alibuild-rev", "abc")[0])
    self.assertEqual(self.alibuild()["kind"], "copy")
    self.assertTrue(os.path.isfile("sw/SESSIONS/s1/alibuild/alibuild_helpers/__init__.py"))
    self.assertTrue(os.path.isfile("sw/SESSIONS/s1/alibuild/aliBuild"))
    # A session which cannot have its own still works, with the aliBuild run.
    with patch.object(cow, "BACKENDS", [cow.NoClone()]):
      self.assertTrue(self.run_session("create", "s3")[0])
    self.assertIsNone(self.alibuild("s3"))
    self.assertFalse(os.path.exists("sw/SESSIONS/s3/alibuild"))
    self.assertTrue(self.run_session("drop", "s1")[0])
    self.assertFalse(os.path.exists("sw/SESSIONS/s1"))

  def test_no_alibuild_copy(self) -> None:
    self.assertTrue(self.run_session("create", "s1", "--no-alibuild-copy")[0])
    self.assertIsNone(self.alibuild())
    self.assertFalse(os.path.exists("sw/SESSIONS/s1"))
    self.assertIn("aliBuild: whichever one builds it", self.run_session("show", "s1")[1])

  def test_session_without_alibuild(self) -> None:
    # A session from before sessions had their own aliBuild builds with the one run...
    os.makedirs("sw/SESSIONS")
    with open("sw/SESSIONS/s1.json", "w") as f:
      json.dump({"name": "s1", "created": "t", "events": []}, f)
    execve = Mock()
    reexec_session_alibuild(argparse.Namespace(action="build", develPrefix="s1", workDir="sw"), [], {}, execve)
    execve.assert_not_called()
    # ...until creating it again gives it one.
    with patch.object(cow, "BACKENDS", [CopyBackend()]):
      self.assertTrue(self.run_session("create", "s1")[0])
    self.assertEqual(self.alibuild()["kind"], "copy")
    self.assertTrue(self.run_session("drop", "s1")[0])

  def test_reexec(self) -> None:
    os.makedirs("sw/SESSIONS/s1/alibuild")
    open("sw/SESSIONS/s1/alibuild/aliBuild", "w").close()
    copy = os.path.abspath("sw/SESSIONS/s1/alibuild")
    with open("sw/SESSIONS/s1.json", "w") as f:
      json.dump({"name": "s1", "events": [], "alibuild": {"path": copy, "kind": "copy", "commit": "c",
                                                          "source": "src/alibuild"}}, f)

    def reexec(environ=None, **args):
      execve = Mock()
      args = dict({"action": "build", "develPrefix": "s1", "workDir": "sw", "chdir": "."}, **args)
      reexec_session_alibuild(argparse.Namespace(**args), ["build", "O2", "-z", "s1"],
                              environ or {"PATH": "/bin"}, execve)
      return execve

    reexec().assert_called_once_with(sys.executable, [sys.executable, join(copy, "aliBuild"),
                                                      "build", "O2", "-z", "s1"],
                                     {"PATH": "/bin", REEXEC_ENV: copy})
    # WORKDIR is where -C goes.
    os.chdir("src")
    reexec(chdir="..").assert_called_once()
    os.chdir("..")
    # Not when it runs from there already, or did not, though started again from there.
    with patch("alibuild_helpers.session.running_alibuild", return_value=copy):
      reexec().assert_not_called()
    reexec(environ={REEXEC_ENV: copy}).assert_not_called()
    # Nor for other sessions, other commands, or a copy which is gone.
    reexec(develPrefix="s2").assert_not_called()
    reexec(action="session").assert_not_called()
    os.unlink("sw/SESSIONS/s1/alibuild/aliBuild")
    reexec().assert_not_called()


if __name__ == '__main__':
  unittest.main()
