# Coordinating agents in sessions

One coordinating agent, the main conversation, works with the user in the
main tree: the directory holding `alidist`, the development checkouts (`O2`,
`O2Physics`, ...) and the work directory `sw`. Each worker agent gets its own
session `NAME`. The coordinator picks up what is ready and merges it. The
user decides what is merged.

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
- **Building**: in the session, with the MCP `build` tool or
  `ALIBUILD_BUILD_SLOTS=1 aliBuild build PKG --defaults D -z NAME --json` in
  the background, since it can take hours. Build heavy downstream packages
  only when needed. Direct compiles only in the session's own build
  directory, holding a slot. Report an unexpected full rebuild instead of
  working around it.
- **Report**: the ready commits (full hashes) and what they sit on, what is in
  progress or needs review, what was run with its results, what was not run,
  and what is blocked. Short final message; details in a file.

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
