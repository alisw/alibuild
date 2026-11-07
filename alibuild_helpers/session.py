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

from alibuild_helpers import cow
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
  create.add_argument("--seed-from", metavar="OTHER", dest="seedFrom",
                      help="Experimental: start the build directories of the session's "
                           "packages as copy-on-write clones of session OTHER's, so that "
                           "their first build is incremental.")

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


def seed_from(work_dir, name):
  """The session whose builds session name's first builds start from, or None."""
  path = session_file(work_dir, name) if name else None
  return load_session(work_dir, name).get("seed_from") if path and exists(path) else None


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
    "seed_from": session.get("seed_from"),
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


#: What a checkout in the middle of an operation, e.g. a rebase, has in .sl or .git.
SL_OPERATIONS = ("merge/state", "merge/state2", "rebasestate", "histedit-state", "graftstate",
                 "updatestate", "updatemergestate", "shelvedstate")
GIT_OPERATIONS = ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD",
                  "index.lock")


def run(*command, cwd=None):
  # Not through git() and sapling(): checking out a large repository, e.g. O2,
  # can take longer than their timeouts.
  proc = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
  if proc.returncode:
    raise SCMError("Error %d from %s: %s" % (proc.returncode, " ".join(command), proc.stdout.strip()))
  return proc.stdout


def busy(source, sapling_repo):
  """Why checkout source must not be cloned now, or None if it can be."""
  if sapling_repo:
    meta = join(source, ".sl")
    # It exits with the number of locks held, and leaves out one it cannot read.
    proc = subprocess.run(["sl", "-R", abspath(source), "debuglocks"],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.returncode or sorted(re.findall(r"^(w?lock):\s+free$", proc.stdout, re.M)) != ["lock", "wlock"]:
      return f"sl holds a lock in {source}"
  else:
    meta = run("git", "-C", abspath(source), "rev-parse", "--absolute-git-dir").strip()
  pending = [f for f in (SL_OPERATIONS if sapling_repo else GIT_OPERATIONS) if exists(join(meta, f))]
  return f"{source} is in the middle of an operation ({', '.join(pending)})" if pending else None


def clone_files(source, dest, meta):
  """Clone source's files into dest, except its meta(data) directory."""
  for entry in sorted(os.listdir(source)):
    if entry != meta:
      cow.clone_tree(join(source, entry), join(dest, entry))


def create_worktree(package, name):
  """Create PKG@NAME at the commit checked out in PKG.

  Its files are copy-on-write clones of PKG's, where a backend of cow.py can
  clone them, so that they take no space, and the files which are the same
  as at the commit keep their modification times. The SCM then reverts what PKG
  changed since the commit, and removes the files it does not track. Without
  a backend, or when PKG is busy, the SCM checks the files out itself.
  """
  source, dest = package, f"{package}@{name}"
  if not isdir(source):
    raise SCMError(f"no {source} checkout to create {dest} from")
  commit = scm_for(source).checkedOutCommitName(directory=source)
  # sl share only works for Sapling's own repositories: one in git format
  # (.git, with or without .git/sl) needs a git worktree. Neither share nor
  # worktree is made by cloning .sl or .git: a checkout which is not itself a
  # share has the whole store in its .sl.
  sapling_repo = exists(join(source, ".sl"))
  if sapling_repo:
    run("sl", "share", "-U", abspath(source), abspath(dest))
  else:
    run("git", "-C", abspath(source), "worktree", "add", "--no-checkout", "--detach", abspath(dest), commit)
  reason = busy(source, sapling_repo)
  if reason is None:
    try:
      clone_files(source, dest, ".sl" if sapling_repo else ".git")
    except cow.CloneError as e:
      reason = str(e)
      for entry in set(os.listdir(dest)) - {".sl", ".git"}:
        path = join(dest, entry)
        shutil.rmtree(path) if isdir(path) and not islink(path) else os.unlink(path)
  if reason is not None:
    info("Checking out %s, as its files cannot be cloned from %s: %s", dest, source, reason)
    if sapling_repo:
      run("sl", "-R", abspath(dest), "goto", commit)
    else:
      run("git", "reset", "-q", "--hard", cwd=dest)
  elif sapling_repo:
    for command in (("debugrebuilddirstate", "-r", commit), ("revert", "--all", "--no-backup"),
                    ("purge", "--files", "--dirs", "--ignored")):
      run("sl", "-R", abspath(dest), *command)
  else:
    # update-index fails when files differ from the index, as they may: the
    # checkout then rewrites only those.
    run("git", "reset", "-q", cwd=dest)
    subprocess.run(["git", "update-index", "-q", "--refresh"], cwd=dest, stdout=subprocess.DEVNULL)
    run("git", "checkout-index", "-a", "-f", cwd=dest)
    run("git", "clean", "-fdxq", cwd=dest)


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
    seed = args.seedFrom
    if seed is not None and (seed == name or not exists(session_file(args.workDir, seed))):
      error("Cannot seed session %s from %s: there is no other session %s", name, seed, seed)
      return False
    # Creating an existing session adds the worktrees it does not have yet.
    if exists(session_file(args.workDir, name)):
      session = load_session(args.workDir, name)
      new = [p for p in args.packages if not isdir(f"{p}@{name}")]
      if not new and seed is None:
        error("Session %s already exists, with worktrees for %s", name,
              ", ".join(worktrees(name)) or "no packages")
        return False
    else:
      session = {"name": name, "created": now(), "events": []}
      new = args.packages
    if seed is not None:
      session["seed_from"] = seed
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
    print(f"Session {name}" + (f", created {session['created']}" if session["created"] else "") +
          (f", seeded from {session['seed_from']}" if session["seed_from"] else ""))
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
