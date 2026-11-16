import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from os.path import join

from unittest import mock

from alibuild_helpers import mcp_server
from alibuild_helpers.mcp_server import Server, TOOLS

# Stands in for aliBuild: answers like `aliBuild build ... --json` would.
FAKE_ALIBUILD = r'''
import json, os, sys, time
argv = sys.argv[1:]
if argv[0] == "session":
    print(json.dumps(["s1"]) if "list" in argv else "")
    sys.exit(0)
packages = []
for a in argv[1:]:
    if a.startswith("-"):
        break
    packages.append(a)
if "--plan" in argv:
    if "broken" in packages:
        print(json.dumps({"status": "error", "message": "Package broken not found"}))
        sys.exit(1)
    print(json.dumps({"packages": [{"package": p, "action": "build"} for p in packages],
                      "summary": {"packages": len(packages), "reuse": 0, "build": len(packages)}}))
    sys.exit(0)
status = os.environ["ALIBUILD_STATUS_FILE"]
with open(status, "w") as f:
    json.dump({"state": "building", "package": packages[0], "log": status + ".pkglog"}, f)
with open(status + ".pkglog", "w") as f:
    f.write("compiling\n" * 5)
print("some logging", file=sys.stderr)
time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))
if "fail" in packages:
    print(json.dumps({"status": "failure", "failed": {"package": "fail", "log": status + ".pkglog"}}))
    sys.exit(1)
print(json.dumps({"status": "success", "packages": [{"package": p, "version": "v1", "revision": "1",
                                                     "action": "built"} for p in packages]}))
'''


class McpServerTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self.tmp = tempfile.TemporaryDirectory()
    fake = join(self.tmp.name, "fake_alibuild.py")
    with open(fake, "w") as f:
      f.write(FAKE_ALIBUILD)
    self.server = Server(join(self.tmp.name, "sw"), root=self.tmp.name,
                         alibuild=[sys.executable, fake], environ=dict(os.environ, FAKE_SLEEP="0"))

  def tearDown(self) -> None:
    self.tmp.cleanup()

  def rpc(self, method, params=None, msg_id=1):
    return self.server.handle({"jsonrpc": "2.0", "id": msg_id, "method": method,
                               "params": params or {}})

  def tool(self, tool_name, **arguments):
    reply = self.rpc("tools/call", {"name": tool_name, "arguments": arguments})["result"]
    text = reply["content"][0]["text"]
    return (text if reply.get("isError") else json.loads(text)), reply.get("isError", False)

  def test_protocol(self) -> None:
    init = self.rpc("initialize", {"protocolVersion": "2025-06-18"})["result"]
    self.assertEqual(init["protocolVersion"], "2025-06-18")
    self.assertIn("tools", init["capabilities"])
    self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
    names = [t["name"] for t in self.rpc("tools/list")["result"]["tools"]]
    self.assertEqual(names, [t["name"] for t in TOOLS])
    self.assertIn("build", names)
    self.assertEqual(self.rpc("nonsense")["error"]["code"], -32601)

    # Over stdio: one message per line, and nothing for notifications.
    out = io.StringIO()
    self.server.serve(io.StringIO('{"jsonrpc":"2.0","id":7,"method":"ping"}\n\n'
                                  '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
                                  'not json\n'), out)
    replies = [json.loads(l) for l in out.getvalue().splitlines()]
    self.assertEqual(replies[0], {"jsonrpc": "2.0", "id": 7, "result": {}})
    self.assertEqual(replies[1]["error"]["code"], -32700)
    self.assertEqual(len(replies), 2)

  def test_plan(self) -> None:
    plan, err = self.tool("plan", packages=["O2"], defaults="o2", session="metal")
    self.assertFalse(err)
    self.assertEqual(plan["summary"]["build"], 1)
    # An error stopping the plan is still a JSON result, passed on as such.
    plan, err = self.tool("plan", packages=["broken"])
    self.assertEqual(plan["status"], "error")
    message, err = self.tool("plan", packages=[])
    self.assertTrue(err)
    self.assertIn("packages", message)

  def test_build(self) -> None:
    started, err = self.tool("build", packages=["O2"], defaults="o2", session="metal", build_slots=1)
    self.assertFalse(err)
    self.assertEqual(started["argv"][:2], ["build", "O2"])
    self.assertIn("-z", started["argv"])
    state, _ = self.tool("build_status", id=started["id"], wait_seconds=30)
    self.assertEqual(state["state"], "finished")
    self.assertEqual(state["exit_code"], 0)
    self.assertEqual(state["result"]["status"], "success")
    self.assertEqual(state["progress"]["package"], "O2")
    self.assertEqual(state["build_slots"], "1")
    log, _ = self.tool("build_log", id=started["id"])
    self.assertIn("some logging", log["text"])
    log, _ = self.tool("build_log", id=started["id"], package="O2", lines=2)
    self.assertEqual(log["text"], "compiling\ncompiling\n")

    failed, _ = self.tool("build", packages=["fail"])
    state, _ = self.tool("build_status", id=failed["id"], wait_seconds=30)
    self.assertEqual((state["exit_code"], state["result"]["status"]), (1, "failure"))
    log, _ = self.tool("build_log", id=failed["id"], package="fail")
    self.assertIn("compiling", log["text"])

    builds, _ = self.tool("builds")
    self.assertEqual([b["id"] for b in builds], [failed["id"], started["id"]])
    self.assertEqual(builds[0]["result_status"], "failure")
    self.assertNotIn("result", builds[0])

    message, err = self.tool("build_status", id="../etc")
    self.assertTrue(err)
    message, err = self.tool("build_status", id="nonexistent")
    self.assertTrue(err)

  def test_running_and_cancel(self) -> None:
    self.server.environ["FAKE_SLEEP"] = "60"
    started, _ = self.tool("build", packages=["O2"])
    state, _ = self.tool("build_status", id=started["id"])
    self.assertEqual(state["state"], "running")
    # The build is detached: another server, e.g. of another client, sees it too.
    other = Server(self.server.work_dir, root=self.tmp.name, alibuild=self.server.alibuild)
    self.assertEqual(other.list_builds({})[0]["state"], "running")
    cancelled, err = self.tool("build_cancel", id=started["id"])
    self.assertFalse(err)
    state, _ = self.tool("build_status", id=started["id"], wait_seconds=10)
    self.assertEqual(state["state"], "cancelled")
    self.assertNotEqual(state["exit_code"], 0)
    time.sleep(0.5)
    self.assertFalse(self.server._alive(join(self.server.builds_dir, started["id"])))
    message, err = self.tool("build_cancel", id=started["id"])
    self.assertTrue(err)

  def test_stdio_closes_with_builds_running(self) -> None:
    # Through ssh and srun, the client only sees the server end once nothing
    # holds its stdout and stderr: a detached build must not.
    script = ("import sys; from alibuild_helpers.mcp_server import Server; "
              "Server(sys.argv[1], root=sys.argv[2], alibuild=sys.argv[3:]).serve()")
    proc = subprocess.Popen([sys.executable, "-c", script, self.server.work_dir, self.tmp.name,
                             *self.server.alibuild], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env=dict(self.server.environ, FAKE_SLEEP="60"),
                            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    started = time.time()
    out, _ = proc.communicate(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                          "params": {"name": "build",
                                                     "arguments": {"packages": ["O2"]}}}) + "\n",
                              timeout=30)
    self.assertLess(time.time() - started, 30)
    build_id = json.loads(json.loads(out)["result"]["content"][0]["text"])["id"]
    self.assertEqual(self.server.build_state(build_id)["state"], "running")
    self.server.cancel_build({"id": build_id})

  def test_sessions(self) -> None:
    sessions, err = self.tool("session_list")
    self.assertEqual((sessions, err), (["s1"], False))
    done, err = self.tool("session_record", name="s1", package="O2", ref="alisw/O2#1", action="add")
    self.assertFalse(err)


# Stands in for alienv setenv MODULES -c COMMAND...
FAKE_ALIENV = r'''
echo "alienv $*"
while [ "$1" != -c ]; do shift; done
shift
exec "$@"
'''


def sh(*argv, cwd=None, input=None):
  return subprocess.run(argv, cwd=cwd, input=input, check=True, stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, text=True).stdout


class GatedMcpServerTestCase(McpServerTestCase):
  """With --gated, and a throwaway key as the owner's."""

  def setUp(self) -> None:
    super().setUp()
    t = self.tmp.name
    for repo in ("O2", "alidist"):
      os.makedirs(join(t, repo))
      sh("git", "init", "-q", cwd=join(t, repo))
      with open(join(t, repo, "README"), "w") as f:
        f.write("%s\n" % repo)
      sh("git", "add", "README", cwd=join(t, repo))
      sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "first",
         cwd=join(t, repo))
    sh("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "owner", "-f", join(t, "k"))
    sh("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "other", "-f", join(t, "other"))
    with open(join(t, "alienv"), "w") as f:
      f.write(FAKE_ALIENV)
    self.server = Server(join(t, "sw"), root=t, alibuild=self.server.alibuild,
                         environ=dict(self.server.environ, SLURM_JOB_ID="42"),
                         approvals_key=join(t, "k.pub"), alienv=["/bin/sh", join(t, "alienv")])

  def sign(self, request, key="k", namespace="epn-approval"):
    return sh("ssh-keygen", "-Y", "sign", "-f", join(self.tmp.name, key), "-n", namespace,
              input=request)

  def approved(self, tool_name, **arguments):
    """Ask for, sign and approve tool_name(arguments); return the approval's id."""
    asked, err = self.tool(tool_name, **arguments)
    self.assertFalse(err)
    self.assertEqual(asked["status"], "approval_required")
    done, err = self.tool("approve", id=asked["id"], signature=self.sign(asked["request"]))
    self.assertEqual((done, err), ({"status": "approved", "id": asked["id"]}, False))
    return asked["id"]

  def gated_tool(self, tool_name, **arguments):
    return self.tool(tool_name, approval=self.approved(tool_name, **arguments), **arguments)

  def error(self, tool_name, **arguments):
    text, err = self.tool(tool_name, **arguments)
    self.assertTrue(err, text)
    return json.loads(text)["status"]

  def test_protocol(self) -> None:
    names = [t["name"] for t in self.rpc("tools/list")["result"]["tools"]]
    self.assertEqual(names[:len(TOOLS)], [t["name"] for t in TOOLS])
    self.assertTrue({"approve", "build_dir", "run"} <= set(names))
    build = next(t for t in self.rpc("tools/list")["result"]["tools"] if t["name"] == "build")
    self.assertTrue({"approval", "runs"} <= set(build["inputSchema"]["properties"]))

  def test_build(self) -> None:
    # Unapproved, a build only returns the request, and starts nothing.
    asked, err = self.tool("build", packages=["O2"], defaults="o2")
    self.assertFalse(err)
    self.assertEqual(asked["status"], "approval_required")
    self.assertFalse(os.path.exists(self.server.builds_dir))
    request = json.loads(asked["request"])
    self.assertEqual(asked["request"], json.dumps(request, sort_keys=True, separators=(",", ":")))
    self.assertEqual((request["v"], request["action"], request["packages"], request["job"]),
                     (1, "build", ["O2"], "42"))
    self.assertEqual(sorted(request["sources"]), ["O2"])
    commit = sh("git", "rev-parse", "HEAD", cwd=join(self.tmp.name, "O2")).strip()
    self.assertTrue(request["sources"]["O2"].startswith(commit + "+"))
    self.assertTrue(request["alidist"])
    self.assertIn("O2", asked["summary"])
    # Not approved yet; then approved, it runs, once.
    self.assertEqual(self.error("build", packages=["O2"], defaults="o2", approval=asked["id"]),
                     "approval_invalid")
    self.tool("approve", id=asked["id"], signature=self.sign(asked["request"]))
    started, err = self.tool("build", packages=["O2"], defaults="o2", approval=asked["id"])
    self.assertFalse(err, started)
    state, _ = self.tool("build_status", id=started["id"], wait_seconds=30)
    self.assertEqual(state["result"]["status"], "success")
    self.assertEqual(self.error("build", packages=["O2"], defaults="o2", approval=asked["id"]),
                     "used")
    # Another tool, or other arguments, are another request.
    self.assertEqual(self.error("build", packages=["O2Physics"], defaults="o2",
                                approval=asked["id"]), "used")
    self.assertEqual(self.error("build", packages=["O2"], approval="nonsense"), "approval_invalid")
    _, err = self.tool("build", packages=["O2"], nonsense=1)
    self.assertTrue(err)
    _, err = self.tool("build", packages=["../alidist/evil"])
    self.assertTrue(err)

  def test_stale(self) -> None:
    for change in ("O2/README", "O2/new_file", "alidist/README"):
      approval = self.approved("build", packages=["O2"])
      with open(join(self.tmp.name, change), "a") as f:
        f.write("changed\n")
      self.assertEqual(self.error("build", packages=["O2"], approval=approval), "stale", change)
    # As are other arguments.
    approval = self.approved("build", packages=["O2"])
    self.assertEqual(self.error("build", packages=["O2"], defaults="o2", approval=approval),
                     "stale")

  def test_session_sources(self) -> None:
    t = self.tmp.name
    sh("git", "-C", join(t, "O2"), "worktree", "add", "-q", "--detach", join(t, "O2@s"))
    request = json.loads(self.tool("build", packages=["O2"], session="s")[0]["request"])
    self.assertEqual((request["session"], sorted(request["sources"])), ("s", ["O2"]))
    approval = self.approved("build", packages=["O2"], session="s")
    with open(join(t, "O2", "README"), "a") as f:
      f.write("not the session's\n")
    started, err = self.tool("build", packages=["O2"], session="s", approval=approval)
    self.assertFalse(err, started)
    approval = self.approved("build", packages=["O2"], session="s")
    with open(join(t, "O2@s", "README"), "a") as f:
      f.write("the session's\n")
    self.assertEqual(self.error("build", packages=["O2"], session="s", approval=approval), "stale")

  def test_bad_signatures(self) -> None:
    asked, _ = self.tool("build", packages=["O2"])
    for signature in (self.sign(asked["request"], key="other"),
                      self.sign(asked["request"], namespace="git"),
                      self.sign(asked["request"] + " "), "", "nonsense"):
      text, err = self.tool("approve", id=asked["id"], signature=signature)
      self.assertEqual((json.loads(text)["status"], err), ("approval_invalid", True))
      self.assertEqual(self.error("build", packages=["O2"], approval=asked["id"]),
                       "approval_invalid")

  def test_expired(self) -> None:
    approval = self.approved("build", packages=["O2"])
    later = time.time() + mcp_server.APPROVAL_TTL_SEC + 1
    with mock.patch.object(mcp_server.time, "time", return_value=later):
      self.assertEqual(self.error("build", packages=["O2"], approval=approval), "expired")

  def test_other_job(self) -> None:
    approval = self.approved("build", packages=["O2"])
    self.server.environ["SLURM_JOB_ID"] = "43"
    self.assertEqual(self.error("build", packages=["O2"], approval=approval), "approval_invalid")

  def test_runs(self) -> None:
    runs = [{"argv_prefix": ["echo", "bench"], "max": 2}]
    started, err = self.gated_tool("build", packages=["O2"], runs=runs)
    self.assertFalse(err, started)
    self.tool("build_status", id=started["id"], wait_seconds=30)
    for i in range(2):
      ran, err = self.tool("run", argv=["echo", "bench", str(i)], build=started["id"])
      self.assertFalse(err, ran)
      state, _ = self.tool("build_status", id=ran["id"], wait_seconds=30)
      self.assertEqual(state["exit_code"], 0)
      log, _ = self.tool("build_log", id=ran["id"])
      self.assertEqual(log["text"], "alienv -w %s setenv O2/v1-1 -c echo bench %d\nbench %d\n"
                                    % (self.server.work_dir, i, i))
    # Beyond max, or another argv, or another build: approve it alone.
    for argv, build in ((["echo", "bench"], started["id"]), (["echo", "other"], started["id"]),
                        (["echo", "bench"], None)):
      asked, err = self.tool("run", argv=argv, **({"build": build} if build else {}))
      self.assertEqual((asked["status"], err), ("approval_required", False))
    ran, err = self.gated_tool("run", argv=["echo", "other"], build=started["id"])
    self.assertFalse(err, ran)
    # Without a build, in the server's environment, and in the work directory.
    ran, err = self.gated_tool("run", argv=["pwd"])
    self.tool("build_status", id=ran["id"], wait_seconds=30)
    self.assertEqual(self.tool("build_log", id=ran["id"])[0]["text"].strip(),
                     os.path.realpath(self.server.work_dir))
    _, err = self.gated_tool("run", argv=["pwd"], cwd="..")
    self.assertTrue(err)
    _, err = self.tool("build", packages=["O2"], runs=[{"argv_prefix": [], "max": 1}])
    self.assertTrue(err)

  def test_build_dir(self) -> None:
    _, err = self.gated_tool("build_dir", package="O2", session="s")
    self.assertTrue(err)
    d = join(self.server.work_dir, "BUILD", "O2-latest-s", "O2")
    os.makedirs(d)
    with open(join(d, ".envrc"), "w") as f:
      f.write("export FROM_ENVRC=yes\nsource_up\n")
    with open(join(d, "cmake"), "w") as f:
      f.write("#!/bin/sh\necho \"$FROM_ENVRC $*\"\n")
    os.chmod(join(d, "cmake"), 0o755)
    self.server.environ["PATH"] = d + ":" + self.server.environ["PATH"]
    started, err = self.gated_tool("build_dir", package="O2", session="s", target="install")
    self.assertFalse(err, started)
    self.tool("build_status", id=started["id"], wait_seconds=30)
    self.assertEqual(self.tool("build_log", id=started["id"])[0]["text"],
                     "yes --build . --target install\n")
    _, err = self.tool("build_dir", package="../O2")
    self.assertTrue(err)

  def test_plan(self) -> None:
    super().test_plan()
    for args in (["-c", "elsewhere"], ["--config-dir=elsewhere"], ["--conf", "x"], ["-C", "/"],
                 [1]):
      _, err = self.tool("plan", packages=["O2"], args=args)
      self.assertTrue(err, args)
    plan, err = self.tool("plan", packages=["O2"], args=["--disable", "GCC", "-a", "osx_arm64"])
    self.assertFalse(err, plan)

  def test_running_and_cancel(self) -> None:
    self.server.environ["FAKE_SLEEP"] = "60"
    started, _ = self.gated_tool("build", packages=["O2"])
    cancelled, err = self.tool("build_cancel", id=started["id"])
    self.assertFalse(err)

  def test_stdio_closes_with_builds_running(self) -> None:
    pass    # the same server

  def test_sessions(self) -> None:
    super().test_sessions()
    asked, err = self.tool("session_drop", name="s1", worktrees=True)
    self.assertEqual(asked["status"], "approval_required")
    dropped, err = self.tool("session_drop", name="s1")
    self.assertFalse(err)


class NotGatedTestCase(unittest.TestCase):
  def test_tools(self) -> None:
    server = Server("sw")
    self.assertFalse(server.gated)
    self.assertIs(mcp_server.tool_list(False), TOOLS)
    for name in ("approve", "build_dir", "run"):
      reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": name}})
      self.assertIn("unknown tool", reply["result"]["content"][0]["text"])


if __name__ == '__main__':
  unittest.main()
