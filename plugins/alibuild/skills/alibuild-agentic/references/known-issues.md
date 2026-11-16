# Known issues

- Cancelling a session build while it compiles a development package
  (`PKG@NAME`) leaves that package without an install: development packages
  install in place in `sw/ARCH/PKG/NAME-localN`, which is cleared when its
  build starts. Restore it by finishing the build, or with `ninja install` in
  its build directory.
- Worktrees are ignored, with a warning, with `--docker`.
- Development packages ignore `track_env` in their hash, and incremental
  recipes do not re-run configure: a changed environment may need a clean
  build directory.
- `--plan --json` prints nothing when aliBuild stops with an error; only real
  builds always print JSON.
- After a session build, run `alienv` once without `--no-refresh` (e.g.
  `alienv q`) before `alienv --no-refresh` sees the new modules.
- Programs that read stdin when it is not a terminal (e.g. O2's DPL
  workflows) hang in agent shells: run them with `< /dev/null`.
- Benchmarks on a shared machine vary a lot while another session compiles:
  compare variants interleaved, holding the build slot, and never rebuild a
  library while a benchmark uses it.
- Background agents can only report at the end. Ask them to keep a small
  status file current if the coordinator needs to follow them.
