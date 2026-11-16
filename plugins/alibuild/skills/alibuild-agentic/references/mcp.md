# The aliBuild MCP server

The plugin registers `aliBuild mcp` (needs `aliBuild` on `PATH`). It runs in
the directory Claude Code was started in, so start Claude Code where alidist
and the checkouts are, or set `ALIBUILD_CHDIR` and `ALIBUILD_WORK_DIR`.

## Tools

- `plan`: `--plan --json`, i.e. per package its version, hash and whether it
  is reused or built.
- `build`: starts a build in the background and returns an id at once.
  `packages`, `defaults`, `session` (`-z SESSION`), `args` (more options),
  `build_slots` (`ALIBUILD_BUILD_SLOTS` for this build).
- `build_status`: queued, waiting (e.g. for a slot) or building which
  package; once finished, the `--json` result. `wait_seconds` waits for it.
- `builds`: the builds of the work directory, from every client.
- `build_log`: the end of aliBuild's output, or with `package`, that
  package's build log.
- `build_cancel`.
- `session_list`, `session_show`, `session_create` (`seed_from`),
  `session_record` (`add`/`remove` a merged REF, after merging it),
  `session_drop` (`worktrees`, `dry_run`).

Build state lives in `sw/BUILDS/ID`, and builds are detached from the server,
so every client sees every build, and builds survive the client going away.
Prefer `build` + `build_status` over a long-running Bash command.

## Gated mode

`aliBuild mcp --gated --approvals-key OWNER.pub` is for agents that must not
build or run anything unapproved, e.g. on a machine of their own. It is not
enabled by this plugin; register it yourself with
`claude mcp add alibuild-gated -- aliBuild mcp --gated --approvals-key ~/owner.pub -C DIR`.

- `build`, `build_dir` (`cmake --build` in a development package's build
  directory), `run` (a program, with a build's environment) and
  `session_drop` with `worktrees` first return a request.
- The owner signs it with
  `python3 -m alibuild_helpers.epn_approve approve REQUEST.json`, the agent
  passes the signature to `approve`, then calls the tool again with
  `approval: ID`.
- A request expires after 30 minutes, is used once, and becomes `stale` if a
  source file changed. A `build` can ask for `runs`
  (`[{argv_prefix, max}]`) to run programs afterwards without another
  approval.
- `read_file`, `list_files`, `edit_file`, `apply_patch` and `fetch_result`
  are free, confined to the source root (and the work directory for
  `fetch_result`), and never touch alidist, `.git` or `.sl`.
