# Building concurrently in one work directory

- aliBuild locks each package hash in `sw/LOCKS` while it decides whether to
  build it and builds it. Another process needing it waits, then reuses it.
- `ALIBUILD_BUILD_SLOTS=N` lets at most N package builds compile at once; the
  slots are `sw/LOCKS/slot-0` .. `slot-N-1`.
- All of these are `flock()`s, released when the process ends however it
  ends: nothing to clean after a crash. `sw/LOCKS` keeps one empty file per
  hash; do not delete them while a build may be waiting on one.
- Two `sl` commands in shares of the same repository serialize on the shared
  store lock: an `sl` command that hangs in one session blocks the others.

## Compiling directly in a session's build directory

For a quick incremental check, compile in the session's own build directory,
`sw/BUILD/PKG-latest-NAME/PKG`, never in another session's nor in the main
tree's `PKG-latest`. Hold a slot so as not to overload the machine:
`flock sw/LOCKS/slot-0 cmake --build . --target X` on Linux,
`lockf -k sw/LOCKS/slot-0 cmake --build . --target X` on macOS. Without `-k`,
macOS `lockf` deletes the lock file when it exits, and two builds then hold
"the" slot at once. Load the build environment first (the build directory's
`.envrc`, e.g. through direnv). A direct compile does not install: the
session's install (`sw/ARCH/PKG/latest-NAME-DEFAULTS`) only changes with a
session build.

## Relinking less

`ALIBUILD_LINK_DEPENDS_NO_SHARED=1` makes alidist's `o2.sh` and
`o2physics.sh` configure with `-DCMAKE_LINK_DEPENDS_NO_SHARED=ON` (and flip an
existing build directory to it): a change inside a library relinks that
library only, not every executable linked against it. For direct builds in a
build directory configured without it, run
`cmake -DCMAKE_LINK_DEPENDS_NO_SHARED=ON .` there once, never while a build is
running in it. After removing or renaming an exported symbol, do one full
relink (`OFF`, build, back `ON`), or executables fail at load time instead of
build time.

## Elsewhere

`ALIBUILD_BUILD_WORK_DIR` moves the build directories of non-development
packages elsewhere, e.g. to a faster disk; development packages always build
in the work directory.

## Seeding a session (experimental)

`aliBuild session create NAME PKG --seed-from OTHER` makes the first build of
each `PKG@NAME` with an `incremental_recipe` start from a copy-on-write clone
of session OTHER's build directory, so it is incremental. It only works for
ninja 1.11 and 1.13, and only where the filesystem clones (APFS, or reflinks
on Btrfs/XFS); otherwise the package builds from scratch and aliBuild says
why. `ALIBUILD_COW_BACKEND=none` turns cloning off. `session create` also
clones the worktree's files copy-on-write where it can.
