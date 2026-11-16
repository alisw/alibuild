# Commands and JSON output

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

## JSON results

`--json` prints one JSON object on stdout however the build ends. Read
`status` (`success`, `failure` or `error`), and on failure `failed.package`,
`failed.log` and `failed.build_dir`; on `error`, `message`. Never parse the
log banner. `--plan --json` gives, per package, the version-revision, hash and
whether it is reused or built, without building.
