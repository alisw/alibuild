"""`aliBuild mcp`: a Model Context Protocol server, so that agents can drive aliBuild.

It speaks JSON-RPC over stdin/stdout, one message per line, implementing the
few MCP methods a tools-only server needs. Each client starts its own server,
so nothing is kept in the server: every build has a directory in
WORKDIR/BUILDS/ID with its request, the status the build keeps up to date (see
buildstatus), its --json result, its exit code and its output. Builds are
detached from the server, so they go on if the client goes away, and every
server sees every build: the list of builds is the queue of the work directory.
"""

import json
import os
import shlex
import signal
import subprocess
import sys
import time
import uuid
from os.path import abspath, exists, join

from alibuild_helpers import __version__

PROTOCOL_VERSION = "2025-06-18"
MAX_WAIT_SEC = 300


def add_parser(subparsers, work_dir_default, chdir_default):
  p = subparsers.add_parser(
    "mcp", help="run a Model Context Protocol server",
    description="Serve aliBuild's builds and sessions to MCP clients, e.g. agents, "
                "over stdin and stdout.")
  p.add_argument("-C", "--chdir", metavar="DIR", dest="chdir", default=chdir_default,
                 help="The directory to build in, where the checkouts and alidist are. "
                      "Default is '%(default)s'.")
  p.add_argument("-w", "--work-dir", dest="workDir", default=work_dir_default,
                 help="The work directory. Default is '%(default)s'.")
  p.add_argument("--stdio", action="store_true",
                 help="Talk over stdin and stdout, which is the only transport, e.g. through "
                      "ssh and srun.")
  return p


def _schema(properties, required=()):
  return {"type": "object", "properties": properties, "required": list(required),
          "additionalProperties": False}


_PACKAGES = {"type": "array", "items": {"type": "string"}, "minItems": 1,
             "description": "Packages to build, e.g. [\"O2\"]."}
_BUILD_ARGS = {
  "packages": _PACKAGES,
  "defaults": {"type": "string", "description": "Defaults to use, e.g. o2. Default: release."},
  "session": {"type": "string", "description": "Session to build, i.e. -z SESSION."},
  "args": {"type": "array", "items": {"type": "string"},
           "description": "More aliBuild build options, e.g. [\"--debug\"]."},
}

TOOLS = [
  {"name": "plan",
   "description": "Resolve a build without building: for each package its version, hash, "
                  "and whether it would be reused or built. Takes up to a few minutes.",
   "inputSchema": _schema(_BUILD_ARGS, ["packages"])},
  {"name": "build",
   "description": "Start a build in the background and return its id at once. Follow it "
                  "with build_status. Builds share the work directory safely; with "
                  "build_slots, at most that many compile at the same time.",
   "inputSchema": _schema(dict(_BUILD_ARGS, build_slots={
     "type": "integer", "minimum": 1,
     "description": "ALIBUILD_BUILD_SLOTS for this build. Default: the server's environment."}),
     ["packages"])},
  {"name": "build_status",
   "description": "The state of a build: queued, waiting or building which package, and "
                  "once finished its result (status, packages, and on failure the failed "
                  "package and its log). Can wait for it to finish.",
   "inputSchema": _schema({"id": {"type": "string"},
                           "wait_seconds": {"type": "integer", "minimum": 0,
                                            "maximum": MAX_WAIT_SEC,
                                            "description": "Wait up to this long for the build "
                                                           "to finish. Default 0."}}, ["id"])},
  {"name": "builds",
   "description": "The builds of this work directory, newest first, from every client: "
                  "what is running, waiting and finished.",
   "inputSchema": _schema({"limit": {"type": "integer", "minimum": 1,
                                     "description": "At most this many. Default 20."}})},
  {"name": "build_log",
   "description": "The end of a build's log: aliBuild's own output, or with package, that "
                  "package's build log.",
   "inputSchema": _schema({"id": {"type": "string"}, "package": {"type": "string"},
                           "lines": {"type": "integer", "minimum": 1,
                                     "description": "How many lines. Default 100."}}, ["id"])},
  {"name": "build_cancel",
   "description": "Stop a running build.",
   "inputSchema": _schema({"id": {"type": "string"}}, ["id"])},
  {"name": "session_list",
   "description": "The sessions: sets of PKG@NAME worktrees built with -z NAME.",
   "inputSchema": _schema({})},
  {"name": "session_show",
   "description": "A session's worktrees, their commits and last builds, and what was "
                  "merged into it.",
   "inputSchema": _schema({"name": {"type": "string"}}, ["name"])},
  {"name": "session_create",
   "description": "Create a session, with a PKG@NAME worktree of each package's checkout; "
                  "for an existing session, add the worktrees it lacks.",
   "inputSchema": _schema({"name": {"type": "string"},
                           "packages": {"type": "array", "items": {"type": "string"}}},
                          ["name"])},
  {"name": "session_record",
   "description": "Record that REF was merged into (add) or removed from (remove) the "
                  "PKG@NAME worktree, at the commit it has now. Only records: do the merge "
                  "first.",
   "inputSchema": _schema({"name": {"type": "string"}, "package": {"type": "string"},
                           "ref": {"type": "string"},
                           "action": {"type": "string", "enum": ["add", "remove"]}},
                          ["name", "package", "ref", "action"])},
  {"name": "session_drop",
   "description": "Drop a session's latest-NAME links and record, so that aliBuild clean "
                  "can delete its builds; with worktrees, also its worktrees, unless they "
                  "have uncommitted changes. With dry_run, only say what it would remove.",
   "inputSchema": _schema({"name": {"type": "string"}, "worktrees": {"type": "boolean"},
                           "dry_run": {"type": "boolean"}}, ["name"])},
]


class ToolError(Exception):
  pass


class Server:
  def __init__(self, work_dir, root=".", alibuild=None, environ=None):
    self.work_dir = abspath(work_dir)
    self.root = abspath(root)
    self.alibuild = alibuild or [sys.executable, abspath(sys.argv[0])]
    self.environ = dict(os.environ if environ is None else environ)
    self.builds_dir = join(self.work_dir, "BUILDS")

  # -- running aliBuild ---------------------------------------------------

  def _build_argv(self, a, plan=False):
    packages = a.get("packages") or []
    if not packages or not all(isinstance(p, str) and p for p in packages):
      raise ToolError("packages must be a non-empty list of package names")
    argv = ["build", *packages, "-w", self.work_dir, "--json"]
    if a.get("defaults"):
      argv += ["--defaults", a["defaults"]]
    if a.get("session"):
      argv += ["-z", a["session"]]
    argv += list(a.get("args") or [])
    if plan:
      argv.append("--plan")
    return argv

  def _run(self, argv, timeout=None):
    proc = subprocess.run(self.alibuild + argv, cwd=self.root, env=self.environ,
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr

  def _json_or_error(self, rc, out, err):
    try:
      return json.loads(out)
    except ValueError:
      raise ToolError("aliBuild exited with %d without a JSON result: %s"
                      % (rc, (err.strip().splitlines() or [""])[-1]))

  # -- builds --------------------------------------------------------------

  def _dir(self, build_id):
    if not build_id or "/" in build_id or build_id.startswith("."):
      raise ToolError("invalid build id %r" % build_id)
    d = join(self.builds_dir, build_id)
    if not exists(join(d, "request.json")):
      raise ToolError("no build %s" % build_id)
    return d

  def start_build(self, a):
    argv = self._build_argv(a)
    build_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    d = join(self.builds_dir, build_id)
    os.makedirs(d)
    env = dict(self.environ, ALIBUILD_STATUS_FILE=join(d, "status.json"))
    if a.get("build_slots"):
      env["ALIBUILD_BUILD_SLOTS"] = str(int(a["build_slots"]))
    request = {"id": build_id, "argv": argv, "cwd": self.root,
               "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "build_slots": env.get("ALIBUILD_BUILD_SLOTS")}
    with open(join(d, "request.json"), "w") as f:
      json.dump(request, f, indent=2)
    with open(join(d, "status.json"), "w") as f:
      json.dump({"state": "starting"}, f)
    # The shell starts aliBuild in the background and exits, so the build is
    # nobody's child here and outlives this server. It writes its exit code
    # last: that is how any server knows it has finished. It holds none of the
    # server's stdio either, or ssh would wait for the build to close them.
    q = shlex.quote
    script = ("(%s > %s 2> %s < /dev/null; echo $? > %s) & echo $! > %s"
              % (" ".join(map(q, self.alibuild + argv)), q(join(d, "result.json")),
                 q(join(d, "aliBuild.log")), q(join(d, "exitcode")), q(join(d, "pid"))))
    subprocess.run(["/bin/sh", "-c", script], cwd=self.root, env=env, check=True,
                   start_new_session=True, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"id": build_id, "argv": argv}

  def build_state(self, build_id):
    d = self._dir(build_id)
    with open(join(d, "request.json")) as f:
      state = json.load(f)
    try:
      with open(join(d, "status.json")) as f:
        state["progress"] = json.load(f)
    except (OSError, ValueError):
      state["progress"] = {}
    try:
      with open(join(d, "exitcode")) as f:
        state["exit_code"] = int(f.read().strip())
    except (OSError, ValueError):
      state["exit_code"] = None
    if state["exit_code"] is None:
      state["state"] = "running" if self._alive(d) else "lost"
    else:
      state["state"] = "cancelled" if exists(join(d, "cancelled")) else "finished"
      try:
        with open(join(d, "result.json")) as f:
          state["result"] = json.load(f)
      except (OSError, ValueError):
        state["result"] = None
    return state

  def _alive(self, d):
    try:
      with open(join(d, "pid")) as f:
        os.kill(int(f.read().strip()), 0)
      return True
    except (OSError, ValueError):
      return False

  def build_status(self, a):
    deadline = time.time() + min(int(a.get("wait_seconds") or 0), MAX_WAIT_SEC)
    while True:
      state = self.build_state(a.get("id"))
      if state["state"] != "running" or time.time() >= deadline:
        return state
      time.sleep(min(2, max(0.1, deadline - time.time())))

  def list_builds(self, a):
    try:
      ids = sorted((i for i in os.listdir(self.builds_dir)
                    if exists(join(self.builds_dir, i, "request.json"))), reverse=True)
    except OSError:
      ids = []
    states = [self.build_state(i) for i in ids[:int(a.get("limit") or 20)]]
    # Keep the list short: the result has its own tool.
    for s in states:
      result = s.pop("result", None)
      if result:
        s["result_status"] = result.get("status")
        s["failed"] = result.get("failed")
    return states

  def build_log(self, a):
    state = self.build_state(a.get("id"))
    if a.get("package"):
      path = self._package_log(state, a["package"])
    else:
      path = join(self._dir(a["id"]), "aliBuild.log")
    lines = int(a.get("lines") or 100)
    try:
      with open(path, errors="replace") as f:
        text = f.readlines()[-lines:]
    except OSError:
      raise ToolError("no log at %s" % path)
    return {"log": path, "text": "".join(text)}

  def _package_log(self, state, package):
    failed = (state.get("result") or {}).get("failed") or {}
    if failed.get("package") == package and failed.get("log"):
      return failed["log"]
    progress = state.get("progress") or {}
    if progress.get("package") == package and progress.get("log"):
      return progress["log"]
    raise ToolError("no log known for %s in build %s: only for the package being built, "
                    "or the one which failed" % (package, state["id"]))

  def cancel_build(self, a):
    d = self._dir(a.get("id"))
    if self.build_state(a["id"])["state"] != "running":
      raise ToolError("build %s is not running" % a["id"])
    with open(join(d, "pid")) as f:
      pid = int(f.read().strip())
    # The build runs in its own process group, with its build scripts.
    try:
      os.killpg(os.getpgid(pid), signal.SIGTERM)
    except OSError as exc:
      raise ToolError("cannot stop build %s: %s" % (a["id"], exc))
    # That stops the shell waiting for aliBuild too, so record the outcome here.
    with open(join(d, "cancelled"), "w") as f:
      f.write(time.strftime("%Y-%m-%dT%H:%M:%S%z\n"))
    if not exists(join(d, "exitcode")):
      with open(join(d, "exitcode"), "w") as f:
        f.write("%d\n" % (128 + signal.SIGTERM))
    return {"id": a["id"], "cancelled": True}

  # -- sessions ------------------------------------------------------------

  def _session(self, argv, want_json=False):
    rc, out, err = self._run(["session", "-w", self.work_dir, *argv])
    if want_json and rc == 0:
      return json.loads(out)
    if rc:
      raise ToolError(err.strip() or out.strip() or "aliBuild session failed with %d" % rc)
    return {"output": (out + err).strip()}

  # -- MCP -----------------------------------------------------------------

  def call(self, name, a):
    if name == "plan":
      return self._json_or_error(*self._run(self._build_argv(a, plan=True)))
    if name == "build":
      return self.start_build(a)
    if name == "build_status":
      return self.build_status(a)
    if name == "builds":
      return self.list_builds(a)
    if name == "build_log":
      return self.build_log(a)
    if name == "build_cancel":
      return self.cancel_build(a)
    if name == "session_list":
      return self._session(["list", "--json"], want_json=True)
    if name == "session_show":
      return self._session(["show", a["name"], "--json"], want_json=True)
    if name == "session_create":
      return self._session(["create", a["name"], *(a.get("packages") or [])])
    if name == "session_record":
      return self._session([a["action"], a["name"], a["package"], a["ref"]])
    if name == "session_drop":
      return self._session((["-n"] if a.get("dry_run") else []) + ["drop", a["name"]] +
                           (["--worktrees"] if a.get("worktrees") else []))
    raise ToolError("unknown tool %s" % name)

  def handle(self, msg):
    """Answer one JSON-RPC message, or return None for a notification."""
    method, msg_id = msg.get("method"), msg.get("id")
    if msg_id is None:
      return None
    if method == "initialize":
      result = {"protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "alibuild", "version": __version__ or "unknown"}}
    elif method == "ping":
      result = {}
    elif method == "tools/list":
      result = {"tools": TOOLS}
    elif method == "tools/call":
      params = msg.get("params") or {}
      try:
        value = self.call(params.get("name"), params.get("arguments") or {})
        result = {"content": [{"type": "text", "text": json.dumps(value, indent=2)}]}
      except (ToolError, KeyError, subprocess.SubprocessError, OSError) as exc:
        result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    else:
      return {"jsonrpc": "2.0", "id": msg_id,
              "error": {"code": -32601, "message": "unknown method %s" % method}}
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}

  def serve(self, stdin=sys.stdin, stdout=sys.stdout):
    for line in stdin:
      if not line.strip():
        continue
      try:
        msg = json.loads(line)
      except ValueError:
        reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
      else:
        reply = self.handle(msg)
      if reply is not None:
        stdout.write(json.dumps(reply) + "\n")
        stdout.flush()


def doMcp(args):
  # The logging of aliBuild goes to stderr, which MCP leaves to the server, so
  # stdout carries nothing but protocol messages.
  Server(args.workDir).serve()
  return True
