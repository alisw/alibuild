import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from os.path import join

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
print(json.dumps({"status": "success", "packages": [{"package": p, "action": "built"} for p in packages]}))
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


if __name__ == '__main__':
  unittest.main()
