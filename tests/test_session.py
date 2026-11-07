import argparse
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from alibuild_helpers.session import (add_parser, doSession, describe, list_sessions,
                                      merged_refs, worktrees)


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
    # A session is only created once, and only records worktrees it has.
    self.assertFalse(self.run_session("create", "s1")[0])
    self.assertFalse(self.run_session("add", "s1", "ROOT", "alisw/root#1")[0])
    self.assertFalse(self.run_session("add", "s2", "O2", "alisw/O2#1")[0])

    self.git("commit", "-q", "--allow-empty", "-m", "PR 1", cwd="O2@s1")
    self.assertTrue(self.run_session("add", "s1", "O2", "alisw/O2#1")[0])
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd="O2@s1", text=True).strip()
    os.makedirs("sw/BUILD")
    os.symlink("0123abcd", "sw/BUILD/O2-latest-s1")

    session = describe("sw", "s1")
    self.assertEqual([(t["package"], t["commit"], t["build"]) for t in session["worktrees"]],
                     [("O2", commit, "0123abcd")])
    self.assertEqual([(e["ref"], e["commit"]) for e in session["merged"]],
                     [("alisw/O2#1", commit)])
    self.assertEqual([e["action"] for e in session["events"]], ["create", "add"])

    ok, out = self.run_session("show", "s1", "--json")
    self.assertTrue(ok)
    self.assertEqual(json.loads(out)["merged"], session["merged"])
    ok, out = self.run_session("show", "s1")
    self.assertIn("O2@s1 at %s, last built as 0123abcd" % commit[:12], out)
    self.assertIn("O2: alisw/O2#1 (at %s" % commit[:12], out)

    self.assertTrue(self.run_session("remove", "s1", "O2", "alisw/O2#1")[0])
    self.assertEqual(describe("sw", "s1")["merged"], [])
    self.assertFalse(self.run_session("show", "nothing")[0])

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

  def test_invalid_name(self) -> None:
    with patch.object(self.parser, "error", side_effect=SystemExit) as error, \
         self.assertRaises(SystemExit):
      self.run_session("create", "a/b")
    self.assertIn("invalid session name", error.call_args[0][0])


if __name__ == '__main__':
  unittest.main()
