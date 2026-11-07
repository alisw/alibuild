"""Build sessions: a stable -z label, with a record of what went into it.

A session NAME is a set of worktrees, PKG@NAME next to the PKG checkouts,
which `aliBuild build -z NAME` builds instead of PKG (see "Worktrees" in the
user docs). The name never changes as the session's content does, so merging
one more pull request into a worktree only rebuilds that package and what
depends on it.

What the name does not say is kept in WORKDIR/SESSIONS/NAME.json: when the
session was created, and which pull requests (or any other refs) were merged
into, or removed from, which package, at which commit.
"""

import json
import os
import re
import shutil
import subprocess
import time
from glob import glob, escape as glob_escape
from os.path import abspath, basename, exists, isdir, islink, join

from alibuild_helpers.git import git, Git
from alibuild_helpers.log import banner, error, info
from alibuild_helpers.scm import SCMError
from alibuild_helpers.sl import sapling, Sapling

#: Session names become versions, directory names and symlinks.
SESSION_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*\Z")


def add_parser(subparsers, work_dir_default, chdir_default):
  """Register the `session` subcommand's parser."""
  p = subparsers.add_parser(
    "session", help="manage development sessions",
    description="A session NAME is a set of PKG@NAME worktrees, built with "
                "`aliBuild build -z NAME`, plus a record of what was merged into them.")
  p.add_argument("-C", "--chdir", metavar="DIR", dest="chdir", default=chdir_default,
                 help="Change to the specified directory first, where the worktrees are. "
                      "Default is '%(default)s'.")
  p.add_argument("-w", "--work-dir", dest="workDir", default=work_dir_default,
                 help="The toplevel directory used by builds, where SESSIONS is. "
                      "Default is '%(default)s'.")
  actions = p.add_subparsers(dest="sessionAction", metavar="ACTION")
  actions.required = True

  create = actions.add_parser("create", help="create a session",
                              description="Create session NAME, and a PKG@NAME worktree "
                                          "of each PKG checkout given.")
  create.add_argument("name", metavar="NAME")
  create.add_argument("packages", metavar="PKG", nargs="*",
                      help="Packages to create worktrees for, from the PKG checkout's "
                           "current commit.")

  lst = actions.add_parser("list", help="list sessions")
  lst.add_argument("--json", action="store_true", help="Print JSON.")

  show = actions.add_parser("show", help="show what is in a session")
  show.add_argument("name", metavar="NAME")
  show.add_argument("--json", action="store_true", help="Print JSON.")

  for action, verb in (("add", "merged into"), ("remove", "removed from")):
    a = actions.add_parser(action, help=f"record that REF was {verb} a worktree",
                           description=f"Record that REF was {verb} the PKG@NAME worktree, "
                                       "at the commit it has now checked out. This only "
                                       "records it: do the merge (or revert) first.")
    a.add_argument("name", metavar="NAME")
    a.add_argument("package", metavar="PKG")
    a.add_argument("ref", metavar="REF", help="What was merged, e.g. alisw/O2#1234.")

  drop = actions.add_parser("drop", help="drop a session",
                            description="Remove session NAME's latest-NAME links and its "
                                        "record, so that `aliBuild clean` can delete its builds.")
  drop.add_argument("name", metavar="NAME")
  drop.add_argument("--worktrees", action="store_true",
                    help="Also remove its PKG@NAME worktrees, unless they have uncommitted changes.")
  return p


def session_file(work_dir, name):
  return join(work_dir, "SESSIONS", name + ".json")


def worktrees(name, root="."):
  """Return {package: directory} for the PKG@NAME worktrees in root."""
  return {basename(d)[:-len(name) - 1]: d
          for d in sorted(glob(join(glob_escape(root), "*@" + glob_escape(name))))
          if isdir(d)}


def scm_for(directory):
  if exists(join(directory, ".sl")) or exists(join(directory, ".git", "sl")):
    return Sapling()
  return Git()


def checked_out(directory):
  """The commit checked out in directory, or None if there is none."""
  try:
    return scm_for(directory).checkedOutCommitName(directory=directory)
  except SCMError:
    return None


def merged_refs(events):
  """Return the refs currently in a session, in the order they were added.

  An add after a remove of the same PKG and REF counts again.
  """
  current = {}
  for event in events:
    key = (event.get("package"), event.get("ref"))
    if event["action"] == "add":
      current.pop(key, None)
      current[key] = event
    elif event["action"] == "remove":
      current.pop(key, None)
  return list(current.values())


def load_session(work_dir, name):
  with open(session_file(work_dir, name)) as f:
    return json.load(f)


def save_session(work_dir, session):
  path = session_file(work_dir, session["name"])
  os.makedirs(join(work_dir, "SESSIONS"), exist_ok=True)
  with open(path + ".tmp", "w") as f:
    json.dump(session, f, indent=2)
    f.write("\n")
  os.replace(path + ".tmp", path)


def now():
  return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def describe(work_dir, name, root="."):
  """Everything known about session name, as a dict."""
  path = session_file(work_dir, name)
  session = load_session(work_dir, name) if exists(path) else {"name": name, "events": []}
  trees = []
  for package, directory in worktrees(name, root).items():
    link = join(work_dir, "BUILD", f"{package}-latest-{name}")
    trees.append({
      "package": package,
      "directory": abspath(directory),
      "commit": checked_out(directory),
      "build": os.readlink(link) if islink(link) else None,
    })
  return {
    "name": name,
    "created": session.get("created"),
    "recorded": exists(path),
    "worktrees": trees,
    "merged": merged_refs(session["events"]),
    "events": session["events"],
  }


def list_sessions(work_dir, root="."):
  """Names of the sessions recorded in work_dir, or with worktrees in root."""
  names = {basename(p)[:-len(".json")] for p in glob(join(glob_escape(work_dir), "SESSIONS", "*.json"))}
  names |= {basename(d).split("@", 1)[1] for d in glob(join(glob_escape(root), "*@*")) if isdir(d)}
  return sorted(n for n in names if SESSION_NAME_RE.match(n))


def session_links(work_dir, name):
  """The links which keep session name's builds from being cleaned up.

  These are BUILD/PKG-latest-NAME, and WORKDIR/ARCH/PKG/latest-NAME-DEFAULTS.
  As defaults and session names may both contain dashes, the latter are told
  apart from another session's by their target, NAME-REVISION.
  """
  target = re.compile(re.escape(name) + r"-[^-/]+\Z")
  links = glob(join(glob_escape(work_dir), "BUILD", "*-latest-" + glob_escape(name)))
  links += [l for l in glob(join(glob_escape(work_dir), "*", "*", "latest-" + glob_escape(name) + "-*"))
            if islink(l) and target.match(os.readlink(l))]
  return sorted(l for l in links if islink(l))


def uncommitted_changes(directory):
  if isinstance(scm_for(directory), Sapling):
    return sapling(("status",), directory=directory)
  return git(("status", "--porcelain"), directory=directory)


def remove_worktree(package, directory):
  if isinstance(scm_for(directory), Sapling):
    shutil.rmtree(directory)
  else:
    git(("worktree", "remove", abspath(directory)), directory=package)


def create_worktree(package, name):
  source, dest = package, f"{package}@{name}"
  if not isdir(source):
    raise SCMError(f"no {source} checkout to create {dest} from")
  scm = scm_for(source)
  commit = scm.checkedOutCommitName(directory=source)
  # Not through git() and sapling(): checking out a large repository, e.g. O2,
  # can take longer than their timeouts.
  if isinstance(scm, Sapling):
    commands = [["sl", "share", "-U", abspath(source), abspath(dest)],
                ["sl", "-R", abspath(dest), "goto", commit]]
  else:
    commands = [["git", "-C", abspath(source), "worktree", "add", "--detach", abspath(dest), commit]]
  for command in commands:
    proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.returncode:
      raise SCMError("Error %d from %s: %s" % (proc.returncode, " ".join(command), proc.stdout.strip()))


def doSession(args, parser):
  name = getattr(args, "name", None)
  if name is not None and not SESSION_NAME_RE.match(name):
    parser.error(f"invalid session name {name!r}: use letters, digits and ._+-")

  if args.sessionAction == "list":
    names = list_sessions(args.workDir)
    if args.json:
      print(json.dumps([describe(args.workDir, n) for n in names], indent=2))
    else:
      for n in names:
        print(n)
    return True

  if args.sessionAction == "create":
    # Creating an existing session adds the worktrees it does not have yet.
    if exists(session_file(args.workDir, name)):
      session = load_session(args.workDir, name)
      new = [p for p in args.packages if not isdir(f"{p}@{name}")]
      if not new:
        error("Session %s already exists, with worktrees for %s", name,
              ", ".join(worktrees(name)) or "no packages")
        return False
    else:
      session = {"name": name, "created": now(), "events": []}
      new = args.packages
    missing = [p for p in new if not isdir(p) and not isdir(f"{p}@{name}")]
    if missing:
      error("No checkout to create a worktree from: %s", ", ".join(missing))
      return False
    # Saved first, and after each worktree, so a failure leaves none unrecorded.
    save_session(args.workDir, session)
    for package in new:
      try:
        if not isdir(f"{package}@{name}"):   # an existing one is adopted
          create_worktree(package, name)
      except SCMError as e:
        error("Cannot create a worktree for %s: %s", package, e)
        return False
      session["events"].append({"time": now(), "action": "create", "package": package,
                                 "commit": checked_out(f"{package}@{name}")})
      save_session(args.workDir, session)
      info("Created %s@%s", package, name)
    info("Build the session with: aliBuild build -z %s ...", name)
    return True

  if args.sessionAction == "show":
    session = describe(args.workDir, name)
    if not session["recorded"] and not session["worktrees"]:
      error("No session %s: no %s, and no worktrees named *@%s", name,
            session_file(args.workDir, name), name)
      return False
    if args.json:
      print(json.dumps(session, indent=2))
      return True
    print(f"Session {name}" + (f", created {session['created']}" if session["created"] else ""))
    print("Worktrees:" if session["worktrees"] else "No worktrees.")
    for tree in session["worktrees"]:
      print(f"  {tree['package']}@{name} at {(tree['commit'] or 'unknown')[:12]}, " +
            ("the recipes for -z " + name if tree["package"] == "alidist" else
             f"last built as {tree['build']}" if tree["build"] else "not built"))
    print("Merged:" if session["merged"] else "Nothing merged.")
    for event in session["merged"]:
      print(f"  {event['package']}: {event['ref']} "
            f"(at {(event['commit'] or 'unknown')[:12]}, {event['time']})")
    return True

  if args.sessionAction == "drop":
    return drop_session(args, name)

  # add / remove: record what was done to the worktree, and where it left it.
  if not exists(session_file(args.workDir, name)):
    error("No session %s: create it first with `aliBuild session create %s`", name, name)
    return False
  directory = f"{args.package}@{name}"
  if not isdir(directory):
    error("No %s worktree", directory)
    return False
  session = load_session(args.workDir, name)
  session["events"].append({"time": now(), "action": args.sessionAction, "package": args.package,
                            "ref": args.ref, "commit": checked_out(directory)})
  save_session(args.workDir, session)
  return True


def drop_session(args, name):
  record = session_file(args.workDir, name)
  links = session_links(args.workDir, name)
  trees = worktrees(name) if args.worktrees else {}
  if not exists(record) and not links and not trees:
    error("No session %s to drop", name)
    return False
  dirty = [d for d in trees.values() if uncommitted_changes(d)]
  if dirty:
    error("Not dropping session %s, as these worktrees have uncommitted changes: %s",
          name, ", ".join(dirty))
    return False

  doomed = links + ([record] if exists(record) else []) + list(trees.values())
  banner("This %s delete:\n%s", "would" if getattr(args, "dryRun", False) else "will", "\n".join(doomed))
  if getattr(args, "dryRun", False):
    return True
  for path in links + ([record] if exists(record) else []):
    os.unlink(path)
  for package, directory in trees.items():
    try:
      remove_worktree(package, directory)
    except SCMError as e:
      error("Cannot remove %s: %s", directory, e)
      return False
  if not args.worktrees and worktrees(name):
    info("Its worktrees are still there: drop it with --worktrees to remove them too.")
  info("Run `aliBuild clean` to delete the builds of session %s.", name)
  return True
