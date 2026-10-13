# Logbook: S3 remote store (Action Cache + CAS)

Running record of *what was built and decided when* for the store redesign, and
the (now-settled) decisions. The timeless design lives in
[`REMOTE_STORE_CAS_AC.md`](REMOTE_STORE_CAS_AC.md); this file is kept separate so
the design doc stays readable.

## Open decisions

- **Compatibility scope:** keep back-compat with the `TARS`/publisher layout and
  add `ac/`+`cas/` alongside, or go greenfield. Reconstruction is cleaner
  greenfield but is not readable by today's HTTP frontend without a shim.
- **CAS hash algorithm:** `sha256` (REAPI default) vs reuse of the existing
  SHA-1 machinery.
- **Install surface:** standalone `aliBuild install <pkg>@<ver>` with zero
  alidist dependency (preferred), factoring the unpack+relocate step out of
  `build_template.sh` so build and install share one implementation.
- **Label entry points:** which names are installable (latest, version-revision,
  named nightly tags) and how they are recorded in the store.

## Implementation plan

Settled decisions: **additive** layout (keep `TARS/store`+symlink+manifest;
add `cas/`+`ac/`; the legacy `store/` object becomes an S3 redirect to the CAS
blob, so bytes are stored once); **CAS digest = sha256**, AC key = the existing
sha1 action hash; **`reapi://`** URL scheme; install is a new alidist-free
subcommand; labels reuse the existing `version-revision`/`latest` resolution.

- **Phase 0 — Normalized tarballs.** Done (`build.py`, `build_template.sh`,
  regression test).
- **Phase 1 — Path helpers + AC entry assembly (pure, no S3).**
  `utilities.py`: `resolve_cas_path(algo, h)` → `cas/<algo>/<h[:2]>/<h>`,
  `resolve_ac_path(arch, h)` → `ac/<arch>/<h[:2]>/<h>.json`, and a sha256
  `file_digest` helper. `build.py`: assemble `spec["ac_entry"]` from existing
  spec fields before upload, keeping the backend dumb. Tests in
  `test_utilities.py` and `test_build.py`.
- **Phase 2 — `reapi://` backend, write path.** New backend in `sync.py`
  (generic endpoint), registered in `remote_from_url`. On upload: sha256 the
  tarball, put to CAS (skip if present → dedup), put the recipe blob, put the AC
  JSON, write the legacy `store/` object as a redirect. Tests extend
  `test_sync.py`.
- **Phase 3 — Read path.** `fetch_tarball` resolves action hash → AC →
  `outputDigest` → CAS blob into the local store path, with legacy-`store/`
  fallback. `fetch_symlinks` unchanged.
- **Phase 4 — `aliBuild install`.** Done. `alibuild_helpers/install.py` adds an
  alidist-free subcommand that resolves a label to an action hash (via the
  per-package symlink objects), reads the AC runtime closure, fetches each CAS
  blob, extracts it into the prefix and runs the in-tarball `relocate-me.sh`
  (the relocation logic is not reimplemented -- it ships in the tarball). The
  package's own `init.sh` (already inside the tarball) wires the environment.
  REAPIRemoteSync gained `read_ac_entry`, `download_blob` and
  `resolve_action_hash` read helpers.
- **Phase 5 — `aliBuild reconstruct`.** Done. `alibuild_helpers/reconstruct.py`
  walks the AC build closure post-order, finds tarballs missing from the CAS,
  and materialises the archived full recipes into a self-contained alidist
  directory (surfacing the recorded build container so the env can be pinned).
  The actual rebuild reuses the normal build: running the emitted
  `aliBuild build … --remote-store reapi://…::rw` against the materialised
  config recomputes the same action hashes, rebuilds the missing packages and
  re-uploads them (writing fresh CAS blobs + updated `outputDigest`s).
  Prerequisite, also done: the AC now archives the **full** recipe (parseRecipe
  retains `fullRecipe`) plus `source`/`tag`/`container`, so reconstruction needs
  no alidist checkout.

  `reconstruct --verify` (done): a read-only pre-flight that prints the
  reconstruction *plan* for a package's closure — which tarballs would be
  **reused** from the CAS (blob present) vs **rebuilt** (blob missing) — and
  checks the ledger can actually rebuild the missing ones: recipe blob present +
  integrity-verified (sha256 == recipeDigest), dependency DAG intact, and source
  archived/upstream/none. It certifies the key property that reconstruction is
  incremental — present dependencies (toolchains included) are reused, never
  recompiled — and flags any missing tarball that is *not* regenerable. Rebuilds
  nothing.

  `reconstruct --verify --rebuild` (done): the content-hash capstone. It
  materialises the recipes, restores the target's source, then rebuilds **only the
  target** via the normal build against a *read-only* store (`--force-rebuild
  PACKAGE`, no `::rw`) so every dependency is fetched and reused from the CAS and
  nothing is uploaded; it then hashes the produced tarball and compares to the
  recorded `outputDigest`. A **match** proves the blob is byte-for-byte
  regenerable from the ledger; a **differ** is reported soft (the rebuild is
  valid but not bit-identical — expected for pre-normalisation legacy tarballs)
  and only fails under `--strict`. The `--force-rebuild` changes the target's
  action hash but not the content compared, and only the target is forced, so the
  "don't rebuild the toolchain" guarantee holds. Runs in an isolated workdir; the
  real store is never written.

  `reconstruct --rebaseline` (done): adopt a legacy tarball's reproducible hash as
  the new recorded one, so future verifies are byte-identical instead of a
  perpetual soft `differ`. It implies `--verify --rebuild`; when the rebuild
  *differs* from the recorded (pre-normalisation) hash, it rewrites the target's AC
  entry `outputDigest` — plus the store redirect and per-package link — to point at
  the rebuilt hash, keyed by the **unchanged action hash** (an in-place pointer
  swap: `REAPIRemoteSync.rebaseline_ac_entry`, reusing `migrate_put`). The new CAS
  blob is written **before** the AC is repointed, so a failure never leaves the
  entry dangling (unlike a manual delete-then-rebuild, which has a window where the
  ledger points at nothing); the retention of the replaced blob is preserved
  (untagged == permanent). It is a **dry run** that only prints the plan unless
  `--apply` is given, and leaves the now-orphaned old blob in place unless
  `--delete-old` is also passed. This is the supported way to normalise legacy
  entries in bulk; because the rebuild is deterministic (two runs give the same
  hash), the re-baseline target is a fixed point. A `match` rebuild is a no-op.
  Note it discards the historical `outputDigest` provenance by design — the ledger
  then records the normalised rebuild, not what was originally distributed.

  `reconstruct --persist` (done): the correct way to put a **deleted** artifact blob
  back. It implies `--verify --rebuild`, and when the isolated rebuild reproduces the
  recorded output digest exactly, it uploads **only that CAS blob** at its
  content-addressed key (`put_artifact_blob`, `--storage` retention, default
  `permanent`). It does **not** go through `aliBuild build ...::rw`: that path
  *re-publishes* — it assigns a fresh revision (a rebuild in a polluted workdir came
  out as `-1`, whose tarball hashes differently than the recorded `-6`, so it would
  restore the *wrong* blob) and writes a new `dist`/`dist-direct`/`dist-runtime`
  publisher graph. A content-addressed restore needs none of that: the AC entry,
  legacy store redirect and per-package links still point at the recorded hash (only
  the blob was gone), so putting the bytes back at `cas/<algo>/<hh>/<hash>` is the
  whole operation. It **refuses a `differ` rebuild** (that blob is unreferenced --
  re-baseline instead), is a no-op when the blob is already present, and is a **dry
  run** unless `--apply`. The rebuild runs in an isolated workdir against a read-only
  store, so revision resolution is stable (reproduces the recorded revision) and the
  build itself uploads nothing. Validated end to end: delete a CAS blob, `--verify`
  flips it to `REBUILD`, `--persist --apply` restores the byte-identical blob, and a
  final `--verify` shows `0 to rebuild`.

  **validate-system actions (done).** A satisfied `system_requirement` (make,
  yacc-like, ...) or `prefer_system`-from-host package produces no tarball but *is*
  an action: its check must run to validate the build host. `getPackageList`
  collects every such package into `systemPackageSpecs` -- for **both** categories
  and regardless of `--no-system` (a required system tool must be validated even
  when everything else is built from source), which `--remote-store` sets -- and
  stamps each package's `system_requires` (the satisfied system deps it dropped from
  its build requires). A build then:
  - writes a **`validate-system`** AC entry per system action
    (`build_validate_system_entry` + `put_ac_entry`): the archived recipe (with its
    check), **no `result` tarball**, keyed by the **recipe digest**
    (`system_recipe_digest`) -- content-addressed, so the same system tool required
    by many packages deduplicates to one entry;
  - references those system deps in each dependent's AC entry `deps`, **by the same
    recipe digest** (`build_ac_entry` + `system_specs`), so the dependent resolves to
    the validate-system node.

  reconstruct then **walks to** the node via `deps`, `materialize_recipes` writes its
  recipe, and the rebuild re-runs the check on the host -- self-contained, no
  `--alidist` needed. `find_missing_blobs` skips them (no artifact); `--verify`
  reports them as `system`. Deliberate scope: the system dep is recorded for
  walking/materialising/revalidating but **not folded into the dependent's action
  hash** (the check is host-dependent by nature, and the built deps that *are*
  hashed are unchanged, so nothing rebuilds).

  **Migrate-side population (done, automatic).** Migration gives its entries the same
  validate-system nodes (`populate_system_deps`): for each migrated build entry it
  reads the archived recipe, finds requires that are `system_requirement` packages
  (recovered from `--alidist`), writes a validate-system entry per such dep and
  references it in the entry's `deps` -- exactly what a fresh build does. This runs as
  a **standard pass on every migration** (not opt-in); `migrate --populate-system` is
  the bulk-retroactive form that walks the *whole* ledger to backfill entries migrated
  before the feature existed. Idempotent, no rebuild. Net: the whole store (fresh +
  migrated) is self-reconstructable for system deps -- the `--alidist` bridge is no
  longer needed at reconstruct time.

  Known limitations (next hardening): the build invocation is currently emitted
  for the user to run rather than auto-executed; faithful rebuilds assume the
  recorded `tag` still resolves to `commit.commitHash` (true for release tags,
  not for moving branches — explicit commit pinning is a follow-up); and the
  original `--defaults` name is not recorded (the materialised config uses
  `--defaults release`, since `defaults-release` is in the closure).

- **Phase 6 — Fetch action / content-addressed sources.** Core done.
  `alibuild_helpers/source.py` provides `GitSourceStore` over the reapi backend:
  `snapshot(repo, source, commit)` stores the source as an **incremental chain of
  thin git bundles** — a one-off full base bundle (first snapshot of a repo, or
  after a re-baseline at `MAX_CHAIN`), then a tiny delta per commit, each thin
  against the repo's previous snapshot via a rolling per-repo head. So a stream
  of close commits (e.g. **daily builds of O2Physics**) shares one base and stores
  only its per-commit delta instead of duplicating the whole source each day; the
  artifact records the ordered `segments` to restore. `restore(entry, dest)`
  fetches and applies that chain to rematerialise the exact checkout offline, and
  **falls back to cloning upstream on any chain failure** — under normal
  conditions upstream is available, so the snapshot is a backup + fetch speedup,
  not the sole source of truth. Bundle chains can only be built/thinned with the
  full commit graph, so shallow clones are unusable (a shallow `git bundle create`
  produces an invalid bundle); the legacy `snapshot_legacy_source` therefore uses
  a **partial** (`--filter=tree:0`/`blob:none`) mirror — the same filter aliBuild
  already uses for reference/source clones — so it does not ingest a package's
  whole history to snapshot one commit. Backed by `REAPIRemoteSync` helpers
  (`put_file_as_blob`, `read_object_json`, `write_object_json`). Verified by
  real-git round-trip tests: incremental chain (big base + tiny deltas, one shared
  base), idempotency, multi-segment restore with the upstream wiped, and the
  upstream fallback.

  Wiring done: `doBuild` calls `snapshot_source` at upload time (gated on a
  reapi write store, non-devel, git source; best-effort — it never breaks a
  build, snapshotting from the full reference mirror `spec["reference"]`), and
  records the artifact in the AC as `action.sourceArtifact`. `reconstruct`
  restores archived sources from the CAS into a reference-sources layout and
  adds `--reference-sources` to the emitted build command.

  Refs artifact (done): a rebuild has two upstream touchpoints — resolving
  tags->commits (`git ls-remote` at build.py:69) and fetching source objects.
  The second is the source artifact above; the first is now a **refs artifact**:
  `store_refs`/`load_refs` archive the `scm_refs` ref->commit mapping as a small
  CAS blob (`build.py` `snapshot_refs` captures it into `action.refsArtifact`),
  and `reconstruct` calls `apply_refs` to recreate the original tag refs in the
  restored repo so `ls-remote` against it resolves tags offline. Verified with
  real-git tests.

  Source-aware checkout (done, for fresh git builds): `reconstruct` now
  pre-populates the build's `SOURCES/<pkg>/<version>/<short>` from the source
  artifact (`GitSourceStore.restore_to_source_dir`, replicating
  `short_commit_hash`) and applies the cached tags, then emits `-w <workDir>`.
  At rebuild, `checkout_sources` takes its `isdir` branch and checks out the tag
  **locally**, never cloning the upstream URL; combined with the restored
  reference repo (for the `ls-remote` at build.py:69) the rebuild contacts
  upstream for nothing. Crucially this does **not** touch `spec["source"]`,
  which would change the action hash (build.py:216). Proven by an integration
  test that runs the real `checkout_sources` against an unreachable upstream URL
  and still checks out. No edit to the build hot path was needed.

  Migrated legacy releases (done): `aliBuild migrate --snapshot-sources` clones
  each release's source (once per package, cached under `--source-mirror`),
  resolves the tag to a commit, and archives source + refs into the CAS, setting
  `commit.ref` to the resolved SHA so the source-aware checkout path matches at
  rebuild. Best-effort: if upstream is already gone the release still migrates,
  just without offline source. So both fresh builds and migrated legacy releases
  are now offline-reconstructible (delete the tarball *and* lose the upstream).

  Enriching an already-migrated release (done): re-running with
  `--snapshot-sources` does *not* redo the migration. A fully-migrated package is
  enriched in place from the Action Cache: the AC entry already records the
  upstream git URL and tag, so `enrich_source_snapshot` clones upstream,
  snapshots source + refs into the ledger, and rewrites just the AC entry — no
  tarball re-download and no CAS write. Idempotent (a second run is a no-op once
  the snapshot exists) and cheap (only the unavoidable per-package upstream
  clone), so sources can be back-filled long after the initial migration. The
  build container is intentionally *not* pinned by digest: it is provenance only
  (not part of the action hash), so patching/deleting builder images never
  invalidates the AC/CAS, and reconstruct falls back from digest to tag.

  Remaining: Sapling sources are still git-only (skip cleanly).

- **Phase 7 — `migrate` (migrate-store).** Core done.
  `alibuild_helpers/migrate.py` turns legacy tarballs into reconstruct-complete
  reapi entries: `read_meta_json` extracts the embedded provenance,
  `recover_recipe` recovers the full recipe from the recorded alidist commit
  (`git show`), `ac_entry_from_meta` synthesises the schema-v2 AC entry (deps
  from the recorded recursive dependency hashes), and `REAPIRemoteSync.migrate_put`
  writes the CAS blob + recipe blob + AC entry + legacy redirect + link (so the
  migrated release is installable and publisher-compatible). The build container
  is supplied via `--container` or the architecture's default builder (shared
  `default_builder_image` helper), marked `"provenance": "migration-default"`.
  `aliBuild migrate TARBALL... --alidist DIR --remote-store reapi://...`.

  Inputs: tarballs can be local paths, or `PACKAGE/VERSION-REVISION` specs
  fetched from a **read-only** old HTTP store via `--read-store` (the old store
  is only ever read, never written). `--dry-run` prints the planned migration
  actions (and the URLs it would fetch) without downloading or writing anything.

  Self-verification: a **structural** self-check is wired (`verify_recovered_recipe`,
  on by default, `--no-verify` to skip) — it confirms the recovered recipe
  parses, its package field matches the metadata, and every recorded dependency
  carries a hash, skipping (not writing) entries that fail. This catches the
  realistic failure modes (wrong/renamed recipe, corrupt metadata, missing dep
  hash) without the false-mismatch risk of a half-done hash recompute.

  Follow-ups: full self-verification by **recomputing the action hash** and
  matching the store key (needs replaying defaults + scm_refs — alibuild's
  planning phase; best done as a verify mode of `reconstruct`, which already
  materialises the closure); tarballs without `.meta.json` are skipped
  (install-only fallback TBD); enumerating an old S3 store (vs. taking tarball
  paths) is a driver convenience.

Backbone is 1→2→3 (all testable with mocked S3); 4 and 5 are separable and land
last. Phase 5 is riskiest. Phases 6 (source durability) and 7 (migration) are
separable upgrades that together make legacy releases reconstructible without
their original tarballs or upstreams. Docs: update `docs/docs/user.md`.
