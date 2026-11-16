---
name: alibuild-agentic
description: Build and work in an aliBuild session (PKG@NAME worktrees built with -z NAME, e.g. O2@NAME, alidist@NAME) through the aliBuild MCP tools or `aliBuild build -z NAME --json`, and run several agents in parallel sessions sharing one work directory. Use when an agent works in a PKG@NAME worktree or is told to "build in a session"; when building ALICE software (O2, O2Physics, alidist recipes) with aliBuild from an agent; and when a coordinator starts, briefs, watches, merges or cleans up agents in sessions, or a session build misbehaves.
---

# Working in an aliBuild session

A session `NAME` is a set of worktrees `PKG@NAME` (and often `alidist@NAME`)
next to the main checkouts, built with `-z NAME`. Its builds get their own
`latest-NAME` links and never touch the main tree's `latest` ones, so several
agents can build in one work directory at once.

## The worker's loop

1. **Find or create the session.** `session_list` / `session_show NAME`
   (MCP), or `aliBuild session show NAME`. If you were told to make one:
   `session_create` with `name` and `packages`, or
   `aliBuild session create NAME O2 alidist` from the main tree.
2. **Edit only `PKG@NAME`** (and `alidist@NAME` for recipes). Never the main
   checkouts, another session, or `sw/SESSIONS/NAME/alibuild`.
3. **Build with the session.** MCP: `build` with `packages`, `defaults`,
   `session: NAME`; it returns an id at once. CLI equivalent:
   `aliBuild build PKG --defaults D -z NAME --json` (run in the background).
4. **Follow it.** `build_status` (with `wait_seconds`) until it ends; on
   failure, `build_log` with `package` for the failing package's log. From
   the CLI, read `status` and `failed.log` from the JSON, never the banner.
5. **Record merges.** After merging a ref (e.g. a PR) into `PKG@NAME`,
   `session_record` (`action: add`, `package`, `ref`), or
   `aliBuild session add NAME PKG REF`. It only records; merge first.
   Builds are recorded on their own: `session_show` gives the last ones.

## Rules that matter

- **Plan before an expensive build.** `plan` (or `--plan --json`) says what
  will be built. If a session build would rebuild far more than the session's
  packages and their dependents, e.g. a whole build directory because its
  ninja log is unreadable, stop and report it. Do not invent a side build in
  another directory.
- **Direct compiles only for quick checks**, only in the session's own build
  directory `sw/BUILD/PKG-latest-NAME/PKG` (never another session's, nor the
  main tree's `PKG-latest`), holding a build slot. They do not install; the
  session build does. See `references/concurrent-builds.md`.
- **Keep artefacts in the work area or a data directory you were given**,
  never in `/tmp`, which may be wiped.
- **Stay non-interactive.** No merge tools, editors, pagers or prompts: they
  hang you and every agent waiting on the same repository lock. Sapling:
  `--config ui.merge=:merge3 --config ui.interactive=false --pager=never`,
  commit with `-m`. Git: `GIT_EDITOR=true`, `--no-edit`.
- **Commit often** in the worktree: the commit store is shared with the main
  checkout, so the coordinator sees your progress. Never `sl pull` or
  `sl restack` in a shared store.
- **Do not cancel a build of a `PKG@NAME`** unless you must: it leaves the
  package without an install until it is rebuilt.

## References

- `references/commands.md`: how sessions work, the `aliBuild session` and
  `build -z` commands, `-C`/`-w`, the `--json` result.
- `references/mcp.md`: the MCP server's tools, and `--gated` mode.
- `references/concurrent-builds.md`: locks, build slots, direct compiles,
  `ALIBUILD_LINK_DEPENDS_NO_SHARED`, seeding a session.
- `references/coordinating.md`: for the coordinator: setting sessions up,
  the agent brief checklist, following, merging, cleaning up.
- `references/known-issues.md`.

The aliBuild user docs ("Worktrees", "Sessions", "Running several builds at
once", "Driving aliBuild from agents (MCP)") are the full reference.
