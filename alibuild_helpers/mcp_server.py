"""`aliBuild mcp`: a Model Context Protocol server, so that agents can drive aliBuild.

It speaks JSON-RPC over stdin/stdout, one message per line, implementing the
few MCP methods a tools-only server needs. Each client starts its own server,
so nothing is kept in the server: every build has a directory in
WORKDIR/BUILDS/ID with its request, the status the build keeps up to date (see
buildstatus), its --json result, its exit code and its output. Builds are
detached from the server, so they go on if the client goes away, and every
server sees every build: the list of builds is the queue of the work directory.

With --gated, building and running anything needs the owner's approval: a
gated tool first answers with a request, in canonical JSON, which the owner
signs with `ssh-keygen -Y sign -n epn-approval`, and the signature is given
back with the approve tool. Called again with the request's id, the tool
recomputes the request from what is there now, so that any change since, e.g.
to the sources, voids it, checks the signature against --approvals-key, and
only then runs. Gated mode also has tools to read the sources, and to change
those of the package checkouts.
"""

import base64
import calendar
import hashlib
import json
import os
import secrets
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from glob import glob, escape as glob_escape
from os.path import abspath, dirname, exists, isdir, isfile, islink, join, realpath, relpath

from alibuild_helpers import __version__

PROTOCOL_VERSION = "2025-06-18"
MAX_WAIT_SEC = 300
APPROVAL_NAMESPACE = "epn-approval"
APPROVAL_PRINCIPAL = "ktf"
APPROVAL_TTL_SEC = 1800
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


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
  p.add_argument("--gated", action="store_true",
                 help="Run builds, build directories and programs only with an approval "
                      "signed by a key of --approvals-key.")
  # Made absolute here: aliBuild changes to -C before the server opens it.
  p.add_argument("--approvals-key", metavar="FILE", dest="approvalsKey",
                 type=lambda path: os.path.abspath(os.path.expanduser(path)),
                 help="With --gated, the owner's public key (or keys, one per line), "
                      "relative to the directory aliBuild was started in.")
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
                           "packages": {"type": "array", "items": {"type": "string"}},
                           "seed_from": {"type": "string",
                                         "description": "Start the session's build directories "
                                                        "as copy-on-write clones of this session's."}},
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

# With --gated: what needs an approval (session_drop only with worktrees, as
# only then it deletes sources), and the tools only gated mode has.
GATED = ("build", "build_dir", "run", "session_drop")
_APPROVAL = {"type": "string", "description": "The id of an approved request. Call without it "
                                              "first: that returns the request to approve."}
_RUNS = {"type": "array", "description": "Runs to approve with the build: up to max runs of "
                                         "argv starting with argv_prefix, with this build's "
                                         "environment, without another approval.",
         "items": _schema({"argv_prefix": {"type": "array", "items": {"type": "string"},
                                           "minItems": 1},
                           "max": {"type": "integer", "minimum": 1},
                           "cwd": {"type": "string"}}, ["argv_prefix", "max"])}
GATED_TOOLS = [
  {"name": "approve",
   "description": "Give the owner's signature of a request which a gated tool returned. Then "
                  "call that tool again, with the same arguments and approval: ID.",
   "inputSchema": _schema({"id": {"type": "string"}, "signature": {"type": "string"}},
                          ["id", "signature"])},
  {"name": "build_dir",
   "description": "Build in a development package's build directory, "
                  "BUILD/PACKAGE-latest[-SESSION]/PACKAGE, with cmake --build in the "
                  "environment its .envrc sets up. Runs in the background, like build: "
                  "follow it with build_status and build_log.",
   "inputSchema": _schema({"package": {"type": "string"}, "session": {"type": "string"},
                           "target": {"type": "string"}}, ["package"])},
  {"name": "run",
   "description": "Run a program in the background, in the work directory or cwd within it, "
                  "and with build, in the environment of that build's packages (alienv). "
                  "Follow it with build_status and build_log, which has its output. Needs an "
                  "approval, unless the build's approval had runs matching argv.",
   "inputSchema": _schema({"argv": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                           "build": {"type": "string",
                                     "description": "The id of a finished build."},
                           "cwd": {"type": "string"}}, ["argv"])},
  {"name": "read_file",
   "description": "Read a file under the source root (-C), by lines.",
   "inputSchema": _schema({"path": {"type": "string", "description": "From the source root."},
                           "offset": {"type": "integer", "minimum": 1,
                                      "description": "The first line. Default 1."},
                           "limit": {"type": "integer", "minimum": 1,
                                     "description": "How many lines. Default 2000."}}, ["path"])},
  {"name": "list_files",
   "description": "List a directory under the source root, or with pattern, the files there "
                  "matching it, e.g. **/*.cxx. At most 1000.",
   "inputSchema": _schema({"path": {"type": "string", "description": "Default: the source root."},
                           "pattern": {"type": "string"}})},
  {"name": "edit_file",
   "description": "Replace old with new in a file of a package checkout under the source root. "
                  "old must be there once, unless all is true.",
   "inputSchema": _schema({"path": {"type": "string"}, "old": {"type": "string"},
                           "new": {"type": "string"}, "all": {"type": "boolean"}},
                          ["path", "old", "new"])},
  {"name": "apply_patch",
   "description": "Apply a unified diff to files of the package checkouts, with git apply: "
                  "paths are from the source root, with a/ and b/, e.g. a/O2/CMakeLists.txt.",
   "inputSchema": _schema({"patch": {"type": "string"}}, ["patch"])},
  {"name": "fetch_result",
   "description": "A file in the work directory, given from there or absolute, or under the "
                  "source root: its text, or if it is not text, base64.",
   "inputSchema": _schema({"path": {"type": "string"}}, ["path"])},
]
MAX_FETCH_BYTES = 4 << 20


def tool_list(gated):
  if not gated:
    return TOOLS
  tools = []
  for tool in TOOLS + GATED_TOOLS:
    if tool["name"] in GATED:
      schema = tool["inputSchema"]
      extra = dict(approval=_APPROVAL, **({"runs": _RUNS} if tool["name"] == "build" else {}))
      tool = dict(tool, description=tool["description"] + " Needs an approval.",
                  inputSchema=dict(schema, properties=dict(schema["properties"], **extra)))
    tools.append(tool)
  return tools


class ToolError(Exception):
  pass


class ApprovalError(ToolError):
  def __init__(self, status, request_id, message):
    super().__init__(json.dumps({"status": status, "id": request_id, "message": message}))


#: The options of aliBuild build which plan takes in gated mode. A plan runs
#: the recipes' system checks, so it must not be pointed at other recipes.
PLAN_OPTIONS = ("-a", "--architecture", "--always-prefer-system", "-d", "--debug", "--disable",
                "--force-rebuild", "--force-tracked", "--no-local", "--no-remote-store",
                "--no-system", "--only-deps", "--remote-store")
NAME_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._+-")


class Server:
  def __init__(self, work_dir, root=".", alibuild=None, environ=None, approvals_key=None,
               alienv=None):
    self.work_dir = abspath(work_dir)
    self.root = abspath(root)
    self.alibuild = alibuild or [sys.executable, abspath(sys.argv[0])]
    self.alienv = alienv or [join(dirname(abspath(sys.argv[0])), "alienv")]
    self.environ = dict(os.environ if environ is None else environ)
    self.builds_dir = join(self.work_dir, "BUILDS")
    # With approvals_key, gated: requests by id, the nonces used, and per
    # build its approved runs. All in memory: they end with the server.
    self.gated = approvals_key is not None
    self.pending, self.used, self.allowed_runs = {}, set(), {}
    if self.gated:
      with open(os.path.expanduser(approvals_key)) as f:
        keys = [l.strip() for l in f if l.strip() and not l.startswith("#")]
      if not keys:
        raise ToolError("no key in %s" % approvals_key)
      self.allowed_signers = "".join('%s namespaces="%s" %s\n' % (
        APPROVAL_PRINCIPAL, APPROVAL_NAMESPACE, k) for k in keys)

  # -- approvals -----------------------------------------------------------

  def _needs_approval(self, name, a):
    if name == "session_drop":
      return a.get("worktrees") and not a.get("dry_run")
    return name in GATED

  def _check_names(self, a):
    for name in [*(a.get("packages") or []), a.get("package"), a.get("defaults"),
                 a.get("session")]:
      if name is not None and (not isinstance(name, str) or not name or name[0] in ".-"
                               or not NAME_CHARS.issuperset(name)):
        raise ToolError("invalid name %r" % (name,))

  def _gate(self, name, a, approval):
    """Return None if the call may go ahead, or the request to approve first."""
    known = next(t for t in tool_list(True) if t["name"] == name)["inputSchema"]["properties"]
    if set(a) - set(known):
      raise ToolError("unknown arguments: %s" % ", ".join(sorted(set(a) - set(known))))
    if approval is None:
      if name == "run" and self._allowed_run(a):
        return None
      nonce = secrets.token_hex(16)
      expires = time.strftime(TIME_FORMAT, time.gmtime(time.time() + APPROVAL_TTL_SEC))
      text = self._request(name, a, expires, nonce)
      self.pending[nonce[:12]] = {"request": text}
      return {"status": "approval_required", "id": nonce[:12], "request": text,
              "summary": self._summary(json.loads(text))}
    pending = self.pending.get(approval)
    if not pending:
      raise ApprovalError("approval_invalid", approval, "no such request: call without approval")
    request = json.loads(pending["request"])
    if request["nonce"] in self.used:
      raise ApprovalError("used", approval, "this approval was used already")
    if not self._verified(pending["request"], pending.get("signature")):
      raise ApprovalError("approval_invalid", approval, "not approved: no valid signature")
    if calendar.timegm(time.strptime(request["expires"], TIME_FORMAT)) < time.time():
      raise ApprovalError("expired", approval, "the approval expired at " + request["expires"])
    if (request["host"], request["job"]) != (socket.gethostname(),
                                             self.environ.get("SLURM_JOB_ID")):
      raise ApprovalError("approval_invalid", approval, "approved for another host or job")
    if self._request(name, a, request["expires"], request["nonce"]) != pending["request"]:
      raise ApprovalError("stale", approval, "the arguments, sources or recipes changed since: "
                                             "call without approval for a new request")
    self.used.add(request["nonce"])
    return None

  def approve(self, a):
    pending = self.pending.get(a.get("id"))
    if not pending:
      raise ApprovalError("approval_invalid", a.get("id"), "no such request")
    if not self._verified(pending["request"], a.get("signature")):
      raise ApprovalError("approval_invalid", a["id"], "the signature is not the owner's, "
                                                      "for namespace " + APPROVAL_NAMESPACE)
    pending["signature"] = a["signature"]
    return {"status": "approved", "id": a["id"]}

  def _verified(self, text, signature):
    if not signature:
      return False
    with tempfile.TemporaryDirectory(prefix="alibuild-mcp-") as tmp:
      for name, content in (("allowed_signers", self.allowed_signers), ("signature", signature)):
        with open(join(tmp, name), "w") as f:
          f.write(content)
      return subprocess.run(["ssh-keygen", "-Y", "verify", "-f", join(tmp, "allowed_signers"),
                             "-I", APPROVAL_PRINCIPAL, "-n", APPROVAL_NAMESPACE,
                             "-s", join(tmp, "signature")],
                            input=text.encode(), stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL).returncode == 0

  def _request(self, name, a, expires, nonce):
    """The canonical JSON of what the call would do now, to be signed."""
    if name == "build":
      for run in a.get("runs") or []:
        if (not isinstance(run, dict) or not run.get("argv_prefix") or
            not all(isinstance(x, str) for x in run["argv_prefix"]) or
            not isinstance(run.get("max"), int) or run["max"] < 1):
          raise ToolError("runs must be a list of {argv_prefix: [...], max: N}")
    if name == "session_drop":
      session = a["name"]
    elif name == "run":
      session = self.build_state(a["build"]).get("session") if a.get("build") else None
    else:
      session = a.get("session")
    sources = self._sources(session)
    request = dict(a, v=1, host=socket.gethostname(), job=self.environ.get("SLURM_JOB_ID"),
                   session=session, action=name, alidist=sources.pop("alidist", None),
                   sources=sources, expires=expires, nonce=nonce)
    return json.dumps(request, sort_keys=True, separators=(",", ":"))

  def _summary(self, r):
    fixed = ("v", "host", "job", "session", "action", "alidist", "sources", "expires", "nonce")
    return "%s %s, session %s, on %s, job %s, until %s; alidist %s; sources: %s" % (
      r["action"], json.dumps({k: v for k, v in r.items() if k not in fixed}, sort_keys=True),
      r["session"], r["host"], r["job"], r["expires"], r["alidist"],
      ", ".join("%s %s" % s for s in sorted(r["sources"].items())) or "none")

  def _sources(self, session):
    """{package: BASE+SHA256} for each checkout in the source root a build would use.

    That is PKG@SESSION instead of PKG, and the hash is of the uncommitted
    changes, including untracked files, as computed here.
    """
    sources = {}
    for entry in sorted(os.listdir(self.root)):
      package, _, label = entry.partition("@")
      d = join(self.root, entry)
      if label and label != session:
        continue    # another session's
      if not label and session and isdir("%s@%s" % (d, session)):
        continue    # replaced by the session's
      if exists(join(d, ".sl")) or exists(join(d, ".git")):
        sources[package] = self._source_state(d)
    return sources

  def _source_state(self, d):
    if exists(join(d, ".sl")) or exists(join(d, ".git", "sl")):
      sl = ["sl", "--config", "ui.interactive=false", "--pager=never"]
      base, diff, untracked = sl + ["whereami"], sl + ["diff", "--git"], sl + ["status", "-un0"]
    else:
      git = ["git", "-c", "core.fsmonitor=false"]
      base, diff = git + ["rev-parse", "HEAD"], git + ["diff", "--binary", "--no-ext-diff",
                                                       "--no-textconv", "HEAD"]
      untracked = git + ["ls-files", "-z", "--others", "--exclude-standard"]
    def out(argv):
      return subprocess.run(argv, cwd=d, env=dict(self.environ, HGPLAIN="1"), check=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL).stdout
    h = hashlib.sha256(out(diff))
    for name in filter(None, out(untracked).split(b"\0")):
      h.update(b"\0" + name + b"\0")
      path = join(d, os.fsdecode(name))
      if islink(path):
        h.update(os.fsencode(os.readlink(path)))
      elif isfile(path):
        with open(path, "rb") as f:
          h.update(f.read())
    return "%s+%s" % (out(base).decode().strip(), h.hexdigest())

  def _allowed_run(self, a):
    """Take one of the runs a build's approval allowed, if argv matches one."""
    for run in self.allowed_runs.get(a.get("build"), []):
      if (a["argv"][:len(run["argv_prefix"])] == run["argv_prefix"] and
          a.get("cwd") == run.get("cwd") and run["used"] < run["max"]):
        run["used"] += 1
        return True
    return False

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

  def _new_dir(self):
    build_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    d = join(self.builds_dir, build_id)
    os.makedirs(d)
    return build_id, d

  def _detach(self, d, request, env, redirect):
    """Run request["argv"] in the background, with its output as redirect says."""
    with open(join(d, "request.json"), "w") as f:
      json.dump(request, f, indent=2)
    # The shell starts it in the background and exits, so it is nobody's
    # child here and outlives this server. It writes its exit code last: that
    # is how any server knows it has finished. It holds none of the server's
    # stdio either, or ssh would wait for it to close them.
    q = shlex.quote
    script = ("(%s %s < /dev/null; echo $? > %s) & echo $! > %s"
              % (" ".join(map(q, request["command"])), redirect, q(join(d, "exitcode")),
                 q(join(d, "pid"))))
    subprocess.run(["/bin/sh", "-c", script], cwd=request["cwd"], env=env, check=True,
                   start_new_session=True, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"id": request["id"], "argv": request["argv"]}

  def start_build(self, a):
    argv = self._build_argv(a)
    build_id, d = self._new_dir()
    env = dict(self.environ, ALIBUILD_STATUS_FILE=join(d, "status.json"))
    if a.get("build_slots"):
      env["ALIBUILD_BUILD_SLOTS"] = str(int(a["build_slots"]))
    with open(join(d, "status.json"), "w") as f:
      json.dump({"state": "starting"}, f)
    if a.get("runs"):
      self.allowed_runs[build_id] = [dict(run, used=0) for run in a["runs"]]
    q = shlex.quote
    return self._detach(d, {"id": build_id, "argv": argv, "command": self.alibuild + argv,
                            "cwd": self.root, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                            "build_slots": env.get("ALIBUILD_BUILD_SLOTS"),
                            "packages": a["packages"], "session": a.get("session")},
                        env, "> %s 2> %s" % (q(join(d, "result.json")),
                                             q(join(d, "aliBuild.log"))))

  def _start(self, kind, argv, command, cwd, **extra):
    """Start what build_dir and run run; its output is its log."""
    build_id, d = self._new_dir()
    return self._detach(d, dict(extra, id=build_id, kind=kind, argv=argv, command=command,
                                cwd=cwd, started=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                log="output.log"),
                        self.environ, "> %s 2>&1" % shlex.quote(join(d, "output.log")))

  def build_dir(self, a):
    self._check_names(a)
    link = a["package"] + "-latest" + ("-" + a["session"] if a.get("session") else "")
    d = join(self.work_dir, "BUILD", link, a["package"])
    if not exists(join(d, ".envrc")):
      raise ToolError("no development build of %s at %s" % (a["package"], d))
    argv = ["cmake", "--build", "."] + (["--target", a["target"]] if a.get("target") else [])
    # The environment of the build: the .envrc aliBuild writes for direnv,
    # without direnv, whose source_up only adds the user's own .envrc files.
    return self._start("build_dir", argv, ["/bin/bash", "-c", 'source_up() { :; }; '
                                           'source ./.envrc && exec "$@"', "build_dir", *argv], d)

  def run(self, a):
    argv = a.get("argv")
    if not argv or not all(isinstance(x, str) for x in argv):
      raise ToolError("argv must be a non-empty list of strings")
    cwd, work_dir = realpath(join(self.work_dir, a.get("cwd") or ".")), realpath(self.work_dir)
    if cwd != work_dir and not cwd.startswith(work_dir + os.sep):
      raise ToolError("cwd must be in the work directory %s" % self.work_dir)
    command = argv
    if a.get("build"):
      state = self.build_state(a["build"])
      built = {p["package"]: p for p in (state.get("result") or {}).get("packages") or []}
      packages = state.get("packages") or []
      if state["exit_code"] != 0 or not packages or not all(p in built for p in packages):
        raise ToolError("build %s has not built its packages" % a["build"])
      modules = ",".join("%(package)s/%(version)s-%(revision)s" % built[p] for p in packages)
      command = self.alienv + ["-w", self.work_dir, "setenv", modules, "-c", *argv]
    return self._start("run", argv, command, cwd, build=a.get("build"))

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
      path = join(self._dir(a["id"]), state.get("log", "aliBuild.log"))
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

  # -- files ---------------------------------------------------------------

  def _path(self, path, roots, change=False):
    """path, resolved, if it is under one of roots.

    With change, it must also be in a package checkout, outside its .git or
    .sl, which would let one run commands, and not in alidist, whose recipes
    plan runs.
    """
    if not isinstance(path, str) or not path:
      raise ToolError("no path given")
    for root in map(realpath, roots):
      full = realpath(join(root, path))
      if full == root or full.startswith(root + os.sep):
        break
    else:
      raise ToolError("%s is not under %s" % (path, " or ".join(roots)))
    parts = full[len(root) + 1:].split(os.sep)
    if change and (len(parts) < 2 or parts[0].partition("@")[0] == "alidist" or
                   {".git", ".sl", ".hg"} & set(parts) or
                   not any(exists(join(root, parts[0], scm)) for scm in (".git", ".sl"))):
      raise ToolError("%s is not a file of a package checkout which can be changed" % path)
    return full

  def read_file(self, a):
    path = self._path(a.get("path"), [self.root])
    with open(path, encoding="utf-8", errors="replace") as f:
      lines = f.readlines()
    start = int(a.get("offset") or 1) - 1
    return {"path": path, "lines": len(lines),
            "text": "".join(lines[start:start + int(a.get("limit") or 2000)])}

  def list_files(self, a):
    d = self._path(a.get("path") or ".", [self.root])
    if a.get("pattern"):
      found = glob(join(glob_escape(d), a["pattern"]), recursive=True)
      inside = [p for p in found if realpath(p).startswith(realpath(self.root) + os.sep)]
    else:
      inside = [join(d, n) for n in os.listdir(d)]
    files = sorted(relpath(p, d) + ("/" if isdir(p) else "") for p in inside)
    return {"path": d, "files": files[:1000], "truncated": len(files) > 1000}

  def edit_file(self, a):
    path = self._path(a.get("path"), [self.root], change=True)
    with open(path, encoding="utf-8", errors="surrogateescape", newline="") as f:
      text = f.read()
    count = text.count(a["old"]) if a["old"] else 0
    if not count or (count > 1 and not a.get("all")):
      raise ToolError("old is %d times in %s: it must be there once, or give all" % (count, path))
    with open(path, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
      f.write(text.replace(a["old"], a["new"]))
    return {"path": path, "replaced": count}

  def apply_patch(self, a):
    patch, paths = a.get("patch") or "", []
    # Every path git apply could take one from, and some it would not.
    for line in patch.splitlines():
      if line.startswith(("--- ", "+++ ")) and not line[4:].startswith("/dev/null"):
        paths.append(line[4:].split("\t")[0].partition("/")[2])
      elif line.startswith("diff --git "):
        if len(line.split(" ")) != 4:
          raise ToolError("paths with spaces are not supported: %s" % line)
        paths += [p.partition("/")[2] for p in line.split(" ")[2:]]
      elif line.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
        paths.append(line.split(" ", 2)[2])
      elif line.startswith(("new file mode ", "new mode ")) and line.endswith("120000"):
        raise ToolError("patches cannot make symbolic links")
    if not paths:
      raise ToolError("no file to patch")
    for path in paths:
      self._path(path, [self.root], change=True)
    env = {k: v for k, v in self.environ.items() if not k.startswith("GIT_")}
    proc = subprocess.run(["git", "apply", "--verbose", "-"], cwd=self.root, input=patch,
                          env=dict(env, GIT_CEILING_DIRECTORIES=dirname(realpath(self.root))),
                          text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.returncode:
      raise ToolError("git apply failed: " + proc.stdout.strip())
    return {"files": sorted(set(paths)), "output": proc.stdout.strip()}

  def fetch_result(self, a):
    path = self._path(a.get("path"), [self.work_dir, self.root])
    if os.path.getsize(path) > MAX_FETCH_BYTES:
      raise ToolError("%s is larger than %d bytes" % (path, MAX_FETCH_BYTES))
    with open(path, "rb") as f:
      data = f.read()
    try:
      return {"path": path, "size": len(data), "text": data.decode()}
    except UnicodeDecodeError:
      return {"path": path, "size": len(data), "base64": base64.b64encode(data).decode()}

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
    if self.gated:
      a = dict(a)
      approval = a.pop("approval", None)
      if name == "plan":
        self._check_names(a)
        options = [x for x in a.get("args") or [] if not isinstance(x, str) or x.startswith("-")]
        if any(not isinstance(x, str) or x.split("=")[0] not in PLAN_OPTIONS for x in options):
          raise ToolError("plan only takes these options: " + " ".join(PLAN_OPTIONS))
      if self._needs_approval(name, a):
        self._check_names(a)
        request = self._gate(name, a, approval)
        if request:
          return request
      if name in [t["name"] for t in GATED_TOOLS]:
        return getattr(self, name)(a)
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
      return self._session(["create", a["name"], *(a.get("packages") or [])] +
                           (["--seed-from", a["seed_from"]] if a.get("seed_from") else []))
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
      result = {"tools": tool_list(self.gated)}
    elif method == "tools/call":
      params = msg.get("params") or {}
      try:
        value = self.call(params.get("name"), params.get("arguments") or {})
        result = {"content": [{"type": "text", "text": json.dumps(value, indent=2)}]}
      except (ToolError, KeyError, TypeError, ValueError, AttributeError,
              subprocess.SubprocessError, OSError) as exc:
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
  if args.gated != bool(args.approvalsKey):
    print("aliBuild mcp: --gated needs --approvals-key, and the other way round", file=sys.stderr)
    return False
  # The logging of aliBuild goes to stderr, which MCP leaves to the server, so
  # stdout carries nothing but protocol messages.
  Server(args.workDir, approvals_key=args.approvalsKey).serve()
  return True
