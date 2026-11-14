---
name: alibuild-agentic
description: Run one or several agents on packages built with aliBuild (ALICE software, e.g. O2, O2Physics, alidist), each in its own aliBuild session (PKG@NAME worktrees built with -z NAME), building concurrently in one work directory. Covers creating and dropping sessions, briefing agents, build slots, --json results, the aliBuild MCP server and its --gated mode, keeping agents non-interactive, reviewing and merging their work, and the known issues. Use when asked to start, brief, watch or merge agents working with aliBuild, to run parallel aliBuild builds, or when a session build or an agent misbehaves.
---

# Agents and aliBuild sessions

One coordinating agent, the main conversation, works with the user in the
main tree: the directory holding `alidist`, the development checkouts (`O2`,
`O2Physics`, ...) and the work directory `sw`. Each worker agent gets its own
aliBuild session `NAME`: worktrees `O2@NAME`, `O2Physics@NAME`,
`alidist@NAME`, ..., built with `-z NAME`. The coordinator picks up what is
ready and merges it. The user decides what is merged.

The "Worktrees", "Sessions", "Running several builds at once" and "Driving
aliBuild from agents (MCP)" sections of the aliBuild user docs are the
reference; check `aliBuild session CMD --help` when in doubt.

## How sessions work

- With `-z NAME`, a directory `PKG@NAME` next to `PKG` is PKG's development
  checkout, and `alidist@NAME` replaces `alidist` for the recipes, unless `-c`
  is given.
- `NAME` only applies to packages that have a `PKG@NAME` worktree. The other
  development checkouts keep their usual version and hash, so their builds
  are shared with the main tree.
- Session builds only get `-latest-NAME` links (`sw/BUILD/PKG-latest-NAME`,
  `sw/ARCH/PKG/latest-NAME-DEFAULTS`). They never move the main tree's
  `latest` links. Enter one with `alienv enter O2/latest-NAME-o2`.
- The record of a session is `sw/SESSIONS/NAME.json`. A session also gets
  its own aliBuild, `sw/SESSIONS/NAME/alibuild`, which `aliBuild build -z NAME`
  re-executes, so updating aliBuild in the main tree does not change a
  running session's builds (`--no-alibuild-copy` and `--alibuild-rev REV` on
  `session create`). A session created before this feature gets its copy
  when `aliBuild session create NAME` is run again; that adds nothing else
  and leaves its worktrees alone. Only the coordinator moves a session's
  aliBuild to another commit (e.g. `sl -R sw/SESSIONS/NAME/alibuild goto REV`).
- Worktrees are a `git worktree`, or an `sl share` for Sapling checkouts. They
  share the commit store with the main checkout, so whatever an agent commits
  is visible at once from the main checkout. Agents should commit often.

## Commands

```sh
aliBuild session create NAME O2 O2Physics alidist   # again later: adds missing worktrees
aliBuild session list [--json]
aliBuild session show NAME [--json]   # worktrees, their commits, last builds, merges
aliBuild session add NAME PKG REF     # record that REF was merged (merge it first)
aliBuild session remove NAME PKG REF
aliBuild session drop [-n] NAME [--worktrees]   # -n: only say what it would remove
aliBuild build O2 --defaults o2 -z NAME --json
aliBuild build O2 --defaults o2 -z NAME --plan --json
```

`session` and `mcp` take `-C DIR` (where alidist and the checkouts are) and
`-w WORKDIR`; both default to `ALIBUILD_CHDIR`/`ALIBUILD_WORK_DIR` when set.
Anything throwaway, e.g. trying a command out, must use its own `-w`: files
in `sw/SESSIONS` show up as sessions.

`--json` prints one JSON object on stdout however the build ends. Read
`status` (`success`, `failure` or `error`), and on failure `failed.package`,
`failed.log` and `failed.build_dir`; on `error`, `message`. Never parse the
log banner. `--plan --json` gives, per package, the version-revision, hash and
whether it is reused or built, without building.

## MCP server

The plugin registers `aliBuild mcp` (needs `aliBuild` on `PATH`). It runs in
the directory Claude Code was started in, so start Claude Code where alidist
and the checkouts are, or set `ALIBUILD_CHDIR` and `ALIBUILD_WORK_DIR`.
Tools: `plan`, `build` (background, returns an id; `build_slots` sets
`ALIBUILD_BUILD_SLOTS`), `build_status` (with `wait_seconds`), `builds`,
`build_log` (with `package`, that package's log), `build_cancel`,
`session_list`, `session_show`, `session_create` (`seed_from`),
`session_record`, `session_drop` (`worktrees`, `dry_run`).

Build state lives in `sw/BUILDS/ID`, and builds are detached from the server,
so every client sees every build, and builds survive the client going away.
Prefer `build` + `build_status` over a long-running Bash command.

`aliBuild mcp --gated --approvals-key OWNER.pub` is for agents that must not
build or run anything unapproved, e.g. on a machine of their own. It is not
enabled by this plugin; register it yourself with
`claude mcp add alibuild-gated -- aliBuild mcp --gated --approvals-key ~/owner.pub -C DIR`.
Then `build`, `build_dir`, `run` and `session_drop` with `worktrees` first
return a request; the owner signs it with
`python3 -m alibuild_helpers.epn_approve approve REQUEST.json`, the agent
passes the signature to `approve`, then calls the tool again with
`approval: ID`. A request expires after 30 minutes, is used once, and becomes
`stale` if a source file changed. `read_file`, `list_files`, `edit_file`,
`apply_patch` and `fetch_result` are free, confined to the source root (and
the work directory for `fetch_result`), and never touch alidist, `.git` or
`.sl`.

## Setting up

1. Find each agent's starting point: the commits it is to continue, based on
   the upstream branch, without unrelated drafts stacked on top.
2. `aliBuild session create NAME PKG... [alidist]` from the main tree.
3. Before any agent builds, compare `aliBuild build PKG --defaults D -z NAME
   --plan --json` with the same without `-z`. The session's plan should only
   differ in the session's packages and what depends on them. Whatever both
   plans build is stale in the main tree: the first session build builds it
   for everyone.
4. Launch the agents in the background, each with a brief from the checklist.

## Agent brief checklist

- **Scope**: edit only `*@NAME`. Never edit, check out, rebase or commit in
  the main checkouts, another session, or the session's own aliBuild copy
  in `sw/SESSIONS/NAME/alibuild`. No pushes, no PRs, no writes to a
  remote store, unless the user asked.
- **Non-interactive**: a merge tool or editor opening on the user's screen
  hangs the agent, and every other agent waiting on the same repository lock.
  - Sapling: `--config ui.merge=:merge3 --config ui.interactive=false`,
    `--pager=never`, commit with `-m`. Resolve conflicts by hand, then
    `sl resolve --mark`.
  - Git: `GIT_EDITOR=true`, `--no-edit`, `-m`, no `-i`.
  - zsh does not word-split `$FLAGS`: use a wrapper script or a function for
    those flags, not a variable.
  - When a decision is needed, the agent ends its turn with a report.
- **Rebasing**: branches that become PRs sit on the upstream branch, not on
  the user's working copy. Rebase before every full build and report. In a
  shared Sapling store, agents never run `sl pull` (it moves the remote
  bookmarks for everyone) nor `sl restack` (it can rewrite other sessions'
  commits).
- **Conflict resolutions**: report each (file, commit, what each side did,
  how and why it was resolved). Such commits are "needs review" until the
  user has checked them. Never trust a merge left by an interrupted tool:
  redo it.
- **Building**: `ALIBUILD_BUILD_SLOTS=1 aliBuild build PKG --defaults D -z NAME
  --json` (or the MCP `build` tool), in the background, since it can take
  hours. Build heavy downstream packages only when needed.
- **Report**: the ready commits (full hashes) and what they sit on, what is in
  progress or needs review, what was run with its results, what was not run,
  and what is blocked. Short final message; details in a file.

## Building concurrently in one work directory

- aliBuild locks each package hash in `sw/LOCKS` while it decides whether to
  build it and builds it. Another process needing it waits, then reuses it.
- `ALIBUILD_BUILD_SLOTS=N` lets at most N package builds compile at once; the
  slots are `sw/LOCKS/slot-0` .. `slot-N-1`.
- All of these are `flock()`s, released when the process ends however it
  ends: nothing to clean after a crash. `sw/LOCKS` keeps one empty file per
  hash; do not delete them while a build may be waiting on one.
- To compile directly in a build directory
  (`sw/BUILD/PKG-latest-NAME/PKG`) without overloading the machine, hold a
  slot: `flock sw/LOCKS/slot-0 cmake --build .` on Linux,
  `lockf -k sw/LOCKS/slot-0 cmake --build .` on macOS. Without `-k`, macOS
  `lockf` deletes the lock file when it exits.
- `ALIBUILD_LINK_DEPENDS_NO_SHARED=1` makes alidist's `o2.sh` and
  `o2physics.sh` configure with `-DCMAKE_LINK_DEPENDS_NO_SHARED=ON` (and flip
  an existing build directory to it): a change inside a library relinks that
  library only, not every executable linked against it. After removing or
  renaming an exported symbol, do one full relink, or executables fail at
  load time instead of build time.
- `ALIBUILD_BUILD_WORK_DIR` moves the build directories of non-development
  packages elsewhere, e.g. to a faster disk; development packages always
  build in the work directory.

## Seeding a session (experimental)

`aliBuild session create NAME PKG --seed-from OTHER` makes the first build of
each `PKG@NAME` with an `incremental_recipe` start from a copy-on-write clone
of session OTHER's build directory, so it is incremental. It only works for
ninja 1.11 and 1.13, and only where the filesystem clones (APFS, or reflinks
on Btrfs/XFS); otherwise the package builds from scratch and aliBuild says
why. `ALIBUILD_COW_BACKEND=none` turns cloning off. `session create` also
clones the worktree's files copy-on-write where it can.

## Following and merging

- Follow progress with `aliBuild session show NAME`, the session's commits in
  the main checkout's log, and the MCP `builds` tool.
- If the user reshuffles an agent's stack (e.g. moves ready commits into a
  PR), tell the agent which successor to check out before giving it new work.
  Commits already in a PR get fixes on top, never amended.
- Merge only what the user approves, into the main checkout, and only when
  asked.

## Cleaning up

`aliBuild session drop NAME --worktrees` removes the session's `latest-NAME`
links, its record, its aliBuild copy and its worktrees; it refuses if a
worktree has uncommitted changes. Committed work stays in the repository.
Then `aliBuild clean` deletes the session's builds.

## Known issues

- Cancelling a session build while it compiles a development package
  (`PKG@NAME`) leaves that package without an install: development packages
  install in place in `sw/ARCH/PKG/NAME-localN`, which is cleared when its
  build starts. Restore it by finishing the build, or with `ninja install` in
  its build directory.
- Worktrees are ignored, with a warning, with `--docker`.
- Development packages ignore `track_env` in their hash, and incremental
  recipes do not re-run configure: a changed environment may need a clean
  build directory.
- After a session build, run `alienv` once without `--no-refresh` (e.g.
  `alienv q`) before `alienv --no-refresh` sees the new modules.
- Programs that read stdin when it is not a terminal (e.g. O2's DPL
  workflows) hang in agent shells: run them with `< /dev/null`.
- Benchmarks on a shared machine vary a lot while another session compiles:
  compare variants interleaved, holding the build slot, and never rebuild a
  library while a benchmark uses it.
- Background agents can only report at the end. Ask them to keep a small
  status file current if the coordinator needs to follow them.
