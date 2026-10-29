# Design: S3 remote store with Action Cache + CAS

Status: **largely implemented.** This document describes aliBuild's remote store,
redesigned along the lines of Google's Remote Execution API (REAPI), splitting it
into a small, authoritative **Action Cache (AC)** and a large, regenerable
**Content Addressable Storage (CAS)**, served from S3. Phase-by-phase
implementation status and the settled decisions live in
[`REMOTE_STORE_CAS_AC_LOGBOOK.md`](REMOTE_STORE_CAS_AC_LOGBOOK.md).

## Motivation

Two goals:

1. **Regenerable cache.** The set of tarballs aliBuild ships is large and
   expensive to store. We want the heavy artifact store to be *derived*: if it
   is deleted, it can be reconstructed from a small ledger plus the recipes and
   sources. The ledger must therefore record enough about *how* each artifact
   was produced to re-run the build.

2. **Install without build.** It should be possible to materialise a working
   installation of a package and its runtime closure directly from the remote
   store, with no alidist, no git checkout, and no toolchain — a thin client
   that only downloads and relocates.

## Background: today's store is action-addressed, not content-addressed

It is tempting to call the current `TARS/<arch>/store/<hash[:2]>/<hash>/` layout
a CAS, but it is not. The key is `spec["remote_revision_hash"]`
(`build.py:245`), which is a hash of the *action* — recipe text, version,
package name, git commit, `env`/`append_path`/`prepend_path`/`track_env`, and
every dependency's `hash` (`build.py:146-242`). It is keyed by **what produces
the artifact**, never by the bytes of the artifact. The tarball just happens to
be parked under that action key, and the per-package symlink + `.manifest` layer
is a secondary name→action-key index.

So, in REAPI terms, aliBuild already has a primitive **Action Cache** and *no*
CAS:

| REAPI concept   | keyed by                | aliBuild today                                  |
|-----------------|-------------------------|-------------------------------------------------|
| Action Cache    | action / recipe digest  | `store/<remote_revision_hash>/` — exists        |
| CAS             | hash of the content bytes | does not exist — tarball stored under action key |

Crucial property: the action hash is a pure function of inputs, so it is stable
across rebuilds. A *content* hash of a tarball is only stable if the build is
bit-for-bit reproducible. Importantly, **the dependency DAG is held together by
action hashes, not content hashes**: a package's action hash folds in each
dependency's `hash` (`build.py:224,228`), i.e. the dependency's *action* hash,
never its bytes. This means reconstruction is robust even when builds are not
reproducible (see below).

## Three actions

The redesign makes explicit three operations that share one AC:

- **build** — recipe + dependency closure → tarball. Keyed by the action hash.
  This is what `doBuild` does today. The expensive *producer*.
- **install** — action hash + target prefix → materialised installation. Needs
  only the CAS blobs of the runtime closure plus each tarball's self-contained
  `relocate-me.sh`. No recipes, no toolchain. The cheap, recipe-free *consumer*.
- **reconstruct** — walk the AC DAG and re-run `build` actions for any missing
  CAS blobs, bottom-up. Regenerates the CAS from the AC + recipes + sources.

`install` and `reconstruct` are duals: one materialises from the CAS, the other
repopulates it.

## Data model

### CAS

Content-addressed by a hash of the bytes (e.g. `sha256`):

```
cas/sha256/<h[:2]>/<h>          # tarball bytes and recipe blobs
```

Because aliBuild already mints several *equivalent* action hashes per build
(tag aliases; `spec["remote_hashes"]`, `build.py:250`), a content-addressed CAS
stores the bytes once and lets all equivalent action-cache entries point at the
same blob. This dedup only pays off if the tarball bytes are stable, which is
why tarball normalisation (below) is a prerequisite.

### Action Cache

One small JSON object per action, keyed by the action hash:

```
ac/<arch>/<actionhash[:2]>/<actionhash>.json
```

```jsonc
{
  "schemaVersion": 2,
  "action": {
    "package": "ROOT",
    "version": "v6-28-04",
    "revision": "1",
    "architecture": "slc7_x86-64",
    "actionHash": "<remote_revision_hash>",
    "commit": { "ref": "v6-28-04", "commitHash": "abc123…", "altRefs": { } },
    "source": "https://github.com/root-project/root",
    "tag": "v6-28-04",
    "recipeDigest": "sha256:…",          // FULL recipe (header + body) as a CAS blob
    "container": {                        // build environment, null for native builds
      "runtime": "docker",
      "image": "registry.cern.ch/alisw/slc8-builder:latest",
      "digest": "registry.cern.ch/alisw/slc8-builder@sha256:…"
    },
    "env": { }, "append_path": { }, "prepend_path": { }, "track_env": { },
    "relocatePaths": [ "…" ],
    "deps":        [ { "package": "GCC-Toolchain", "actionHash": "…" } ],
    "runtimeDeps": [ { "package": "GCC-Toolchain", "actionHash": "…" } ],
    "depsHash": "<deps_hash>"
  },
  "result": {
    "tarball": "ROOT-v6-28-04-1.slc7_x86-64.tar.gz",
    "outputDigest": "sha256:…",          // CAS digest of the tarball bytes
    "size": 123456789
  }
}
```

Notes:

- `recipeDigest` (the **full** recipe — header + body, so no alidist checkout is
  needed), `commit`, `source`, `deps` and `env`/paths are what make the entry
  **reconstructing**: they are the full action definition. `container` records
  the build environment (image reference + immutable digest) so reconstruction
  can pin it. None of this was persisted before; the action hash was computed on
  the fly and discarded.
- `runtimeDeps` is the runtime closure (aliBuild's `full_runtime_requires`,
  `build.py:1235`), recorded as action hashes so `install` needs only the AC.
  It mirrors the existing `dist-runtime` link tree but keyed by action hash.
- `outputDigest` is **not load-bearing for reconstruction** — deps reference
  action hashes, so a rebuilt blob simply gets a new digest and that entry's
  `outputDigest` is rewritten. If builds are reproducible it doubles as an
  integrity check; if not, it is just "what we shipped last time".

### Prefix independence (portability)

Both the AC key (the action hash) and the AC entry's contents are independent of
the build/install prefix, which is what lets the same build in different
directories share one cache entry:

- The action hash already excludes the prefix — it is foundational to the
  shared remote cache, which works across users with different `sw/` locations.
  `append_path`/`prepend_path` hold package-relative tokens (`lib`, `bin`); the
  absolute prefix is only spliced in as `${PKG_ROOT}/...` at init.sh-generation
  time (`build.py:465-468`). `relocate_paths` are package-relative. And
  `pruneWorkdirFromPaths`/`pruneVersionEnvVars` (`build.py:523,597`) strip the
  workdir and `*_VERSION` from the environment before the build.
- `build_ac_entry` copies only those prefix-independent fields and records deps
  by action hash; it never stores `workDir`/`INSTALLROOT`/build-prefix.
- CAS content is relocatable (`relocate-me.sh` + `.unrelocated`), so the prefix
  is bound only at install time, not baked into the bytes.

Caveat: this rests on the recipe convention of not hardcoding an absolute build
path into an `env:` value; doing so would already make today's action hash
prefix-dependent, and the AC merely mirrors whatever the hash sees.

## Two stores by lifetime: ledger vs artifact

The content above splits into two lifetimes, and `REAPIRemoteSync` can put them
in two separate stores (buckets):

- **Ledger store** (small, **keep forever**, back it up): Action Cache entries
  (`ac/`) **plus the reconstruction-input blobs** — recipe, source bundles and
  refs. This is the precious, reproduce-forever set.
- **Artifact store** (large, **deletable / regenerable**, lifecycle-expirable):
  the output tarball blobs (`cas/`) and the legacy `TARS/store` redirects/links.

Crucially the inputs live with the AC, not with the tarballs: they are needed to
*reconstruct*, so they must outlive the tarballs. (Before the split they shared
one `cas/`, so "delete the CAS" would have taken the recipes/sources too and
broken reconstruction — the split fixes that.) Because a tarball blob and its
legacy redirect are both in the artifact store, the redirect stays same-bucket;
no cross-bucket redirect is needed.

Config: the artifact store is `--remote-store` (`--write-store`/`::rw` to
upload); the ledger store is the optional `--ac-store` (same `::rw` semantics on
`build`), defaulting to the artifact store so single-bucket setups are unchanged.
Both must share the S3 endpoint (one client; only the bucket differs).
`REAPIRemoteSync` routes by role: `read_ac_entry`/`read_blob`/`download_blob`/
`put_file_as_blob`/`put_bytes_as_blob`/`read_object_json`/`write_object_json` →
ledger; `put_artifact_blob`/`download_artifact`/`artifact_blob_exists` and the
`TARS` redirect/link → artifact.

### Artifact retention: ephemeral vs permanent

The artifact store has a bucket **lifecycle rule** (see
`ali-marathon/s3/alibuild-cas-lifecycle.xml`): objects tagged
`retention=ephemeral` are deleted **90 days after their last-modified time**;
untagged objects and anything tagged `retention=permanent` match no expiry rule
and are kept forever. This is fail-safe — a missing tag never causes deletion.
The **ledger** store is never tagged (always keep-forever); only the large
artifact **tarball blobs** carry a retention tag.

`--storage {ephemeral,permanent}` (default **ephemeral**) drives it, so the CAS
behaves as an LRU cache by default and production pins what it needs:

- **ephemeral** (CI/dev): uploaded blobs are tagged `retention=ephemeral`.
- **permanent** (production): blobs are tagged `retention=permanent`, and when a
  build *reuses* an existing blob (dedup hit) that is still `ephemeral`, it is
  **promoted** to permanent. So a blob first produced by a CI build survives
  once a production build depends on it.

Because a tag-based lifecycle counts from *last-modified*, not last-access, the
reader turns this into true LRU: `download_artifact` **touches** a blob (a
server-side copy-to-self with `TaggingDirective=COPY`, preserving the tag) when
it is `ephemeral` and within `REFRESH_WITHIN_DAYS` (30) of the 90-day expiry.
So a blob that keeps being used never expires, while one unused for ~3 months is
reclaimed. The touch is best-effort and only attempted when the client can write
the same bucket it reads.

## Reconstruction

```
reconstruct(top action hash):
  for each action in post-order over the deps DAG:
    if CAS has result.outputDigest: continue
    fetch recipeDigest blob, check out commit, assemble dependency inputs
    re-run the build action  →  new tarball
    put tarball in CAS, update result.outputDigest/size in the AC entry
```

Correct regardless of build reproducibility, because the DAG edges are action
hashes. Assumes recipes (in CAS) and source repositories (external, referenced
by commit) are still available.

## Install

`install` is a deterministic *client materialisation*, not a cached action — it
produces a prefix-specific result (relocation depends on the target path) that
is cheap to redo, so there is nothing worth caching. It is essentially the
existing cached-tarball branch of `build_template.sh:159-172` (unpack +
`relocate-me.sh` + drop `*.unrelocated`) promoted to a first-class, recipe-free
operation:

```
install(label, prefix):
  top = resolve label → action hash via the store (latest / version-revision)
  for node in {top} ∪ runtime closure (from AC runtimeDeps):
    blob = CAS[ AC[node].result.outputDigest ]
    unpack blob into prefix
    run prefix/.../relocate-me.sh against prefix
  generate init.sh / modulefiles
```

This makes the remote store *self-describing*: today, to know what to fetch,
aliBuild must recompute action hashes from alidist + git. An AC-driven install
reads the closure and digests straight from the store.

## Signing and trust (implemented)

Content addressing gives **integrity** (bytes match their hash) but not
**authenticity**: anyone who can write to the bucket can push a malicious tarball,
compute its digest, and write an AC entry pointing at it — a consumer resolving
`action → outputDigest → blob` would then install it. Signing binds each artifact
to a **trusted builder identity** so `install`/`reconstruct`/fetch can refuse
anything not produced by a trusted key.

**Threat model.** A writer to the store who is not a trusted builder (leaked
credential, insider, or a push path that bypasses CI). *Not* defended by signing
alone: a trusted builder that is itself compromised — that is what key revocation
and a transparency log are for.

**What is signed — the AC entry, not the blob.** The AC entry already binds the
whole action (`recipeDigest`, `commit`, dependency action hashes, `container`,
`ALIBUILD_ALIDIST_HASH`, …) to `result.outputDigest`. Sign that and the chain is:

```
signature → outputDigest → (consumer re-hashes the downloaded blob) → bytes
```

The tarball is never signed directly — content addressing already ties the digest
to the bytes. Sign the *claim*, verify the *bytes hash to the claim*. Use a
**DSSE** envelope (Dead Simple Signing Envelope, the in-toto/sigstore standard):
sign the exact payload bytes + a `payloadType` via PAE, so there is no JSON
canonicalisation to get wrong. Record signatures in the AC JSON, in the
**ledger** store (keep-forever — the right home):

```jsonc
"signatures": [ { "keyid": "…", "sig": "…", "signer": "alice-ci" } ]
```

The signed payload must bind at least `actionHash` + `outputDigest` +
`architecture` + `package`, so a valid signature cannot be replayed onto a
different action.

**Key custody — via the security-proxy.** Consistent with aliBuild's "real secrets
never touch the build shell" model, the builder's private signing key lives in the
security-proxy: a new `sign` route (Ed25519) that takes a payload and returns a
DSSE signature. The key never appears in the build process, CI logs, or an
operator's shell — the same trust boundary that already re-signs S3 requests.
Alternatives: a KMS/HSM, or **keyless** sigstore via CERN OIDC → Fulcio
short-lived certs + a Rekor transparency log (the SLSA-gold path, a larger lift);
the proxy-held key is the MVP.

**Trust root.** A keyring of trusted public keys, each with an identity and a
validity window, that consumers verify against. MVP: a keyring file (shipped in
alibuild or alidist), itself signed by a root key so it cannot be tampered with,
bootstrapped from a signed alibuild release. Later: a TUF-managed root for
rotation and a transparency log for auditable, revocable signatures. **Revocation
and bootstrap must be designed up front**, not bolted on: on key compromise you
must be able to distrust a key and re-evaluate everything it signed.

**Verification.** `install`, `reconstruct` and build-with-fetch verify before
trusting a fetched artifact: fetch AC entry → verify signature(s) against the
trust store per policy → download the CAS blob → check it hashes to the signed
`outputDigest` → proceed, else refuse. Policy modes: `--require-signature` (fail
closed), warn-only, off (default during rollout). Trust is verified over the
**whole runtime/build closure, recursively** — every AC entry in the closure
signed by a trusted key, not just the top package (the easy thing to under-scope).
Local/devel builds (`revision local…`) are exempt or signed by a dev key.

**Rollout.** Optional → warn → enforced, with unsigned legacy entries still
installable throughout the transition (a mixed store). The default is currently
**`warn`**: every consuming command verifies and reports, but nothing is refused,
so a mixed store keeps working while producers start signing.

### MVP: phased plan — S0–S3 done, S4 partly done

Ed25519 keys, DSSE envelopes, key held by the security-proxy, a shipped keyring —
no Fulcio/Rekor/TUF/OPA. Each phase is independently testable and lands behind a
flag, so nothing changed for existing (unsigned) stores until enforcement is
switched on.

Validated end to end on `osx_arm64` against the production store: a signed build
uploaded (`schemaVersion: 3`, signature verifying against the shipped keyring),
then reinstalled with `--require-signature require` on a machine with no alidist
and no `--trusted-keys`.

- **Phase S0 (done) — Verify primitives + keyring (pure, no infra).** New
  `alibuild_helpers/signing.py`: `dsse_pae(payloadType, payload)` (PAE encoding),
  `signed_payload(ac_entry)` (canonical bytes binding `actionHash` +
  `outputDigest` + `architecture` + `package`), `load_keyring(path)` (keyid →
  {ed25519 pubkey, signer, notBefore/notAfter, revoked}), and
  `verify(ac_entry, keyring, policy)`. Ed25519 via `PyNaCl`/`cryptography`.
  Pure functions, unit-tested against fixed vectors — signing and verification
  fixtures, tamper/expiry/revocation cases. No network.
- **Phase S1 (done) — security-proxy `sign` route.** Add an Ed25519 `sign` route in
  `~/src/ali-bot/security-proxy/` (key provisioned into a slot by the human, like
  the S3 creds; the build never sees it). Thin client `sign_via_proxy(payload) →
  {keyid, sig}` in `signing.py`, plus a way to export the public key so the
  keyring can be built from it. Testable against a local/mock proxy.
- **Phase S2 (done) — Sign on upload.** In `REAPIRemoteSync._upload_tarball` (once
  `result.outputDigest` is known), build the DSSE payload, sign it via the proxy,
  and add `signatures: []` to the AC JSON before writing it to the **ledger**.
  Gated on a configured signer (`--sign`); unsigned uploads keep working; skip
  `revision local…`. `schemaVersion` → 3 (additive; old readers ignore the field).
  validate-system entries sign over `actionHash` + `recipeDigest` + `package`
  (no tarball); optional in the MVP.
- **Phase S3 (done) — Verify on consume.** Hook verification into `install.py`
  (`collect_runtime_closure`/`install_entry`), `reconstruct`, and the
  build-with-fetch path (`fetch_tarball`): verify each AC entry against the
  keyring **recursively over the closure**, then confirm the downloaded blob
  hashes to the signed `outputDigest`. New args on `add_reapi_store_args`:
  `--require-signature` (fail closed) / warn-only (default) / off, and
  `--trusted-keys <keyring>`. Policy MVP: "≥1 trusted, in-window, non-revoked
  key." Tests: signed→pass; tampered blob→fail; unsigned+require→fail; untrusted
  /expired/revoked key→fail; one unsigned dep in the closure→fail under require.
- **Phase S4 (partly done) — Keyring distribution + rollout.** The keyring now
  **ships inside the alibuild package** (`alibuild_helpers/keyring.json`) and is
  the trust *anchor*: it arrives with the code the user already executes, i.e.
  over a different channel than the store being verified. That is what makes the
  recipe-free `install` verify anything at all — it has no alidist to read a
  keyring from. `alidist/keyring.json` is merged on top when present, so keys can
  be added without cutting an alibuild release, and `--trusted-keys` replaces the
  set entirely (testing / air-gapped).

  Merging can only ever **narrow** trust: key ids are self-certifying
  (`sha256` of the public key) so the union of keys is conflict-free, validity
  windows **intersect**, and revocation lists **union**. Neither source can
  un-revoke a key or widen a window the other narrowed — which is what lets
  revocation ride on alibuild releases, since builds track the latest alibuild.

  Still to do: signing the keyring itself with a root key (TUF-lite,
  verify-keyring-before-use) and, if the keyring is ever served *from* the store,
  a version counter + expiry so a stale copy cannot be replayed to resurrect a
  revoked key. Then flip the default `warn` → `require` once producers sign;
  unsigned legacy entries stay installable in warn mode.

Deferred to "full" (not MVP): keyless OIDC/Fulcio, Rekor transparency log,
TUF-managed root rotation, OPA/Rego policy — see the infrastructure they require
before adopting.

## S3 backend

A new sync backend (sibling of `Boto3RemoteSync` in `sync.py`), selected by the
`reapi://` URL scheme — named after the design (REAPI AC/CAS) rather than the
transport, to distinguish it from the byte-dumb `s3://`/`b3://` backends. It:

- parameterises the endpoint (`endpoint_url`, region) from the URL / env, so it
  works with AWS, MinIO, Ceph RGW and CERN — unlike the current `b3://`, which
  hardcodes `s3.cern.ch` (`sync.py:521`);
- implements the existing duck-typed interface (`fetch_symlinks`,
  `fetch_tarball`, `upload_symlinks_and_tarball`) for compatibility, and adds AC
  read/write plus CAS get/put keyed by content digest;
- on upload: put the tarball into CAS by content digest, the recipe into CAS,
  and write the AC entry; keep the `store/`+symlink+`.manifest` views as needed
  for the existing publisher / `HttpRemoteSync` during migration.

## Prerequisite: normalized tarballs

Content addressing is only useful if identical file trees produce identical
bytes. `build_template.sh` produces normalized, reproducible tarballs: mtimes pinned to
`SOURCE_DATE_EPOCH`, deterministic entry order via a sorted file list, zeroed
ownership, and `gzip -n`. This normalises the *wrapper + metadata* only;
embedded dates / RPATHs / codegen are the separate long tail of true
reproducibility.

Normalisation is gated by the `NORMALIZE_TARBALL` build-env flag, which
`build.py` sets for every package **except devel packages**: byte-stable output
is useful regardless of the remote store (build-to-build determinism, CAS
dedup, rsync/mirror efficiency, easier debugging), so it is on by default. Devel
packages are excluded because they are never uploaded and normalising would
perturb install-tree mtimes that incremental rebuilds rely on. The extra packing
cost (a full tree-walk to `touch` mtimes + a sorted `find`) is small relative to
compile + `gzip`. A future optimisation could drop the `touch` on modern GNU tar
(>= 1.28) by using `--mtime`/`--sort` directly.

## Fetch action: content-addressed sources

Today a build depends on a live `git` checkout of `source@commit`; the source is
not preserved. So `reconstruct` is only as durable as the upstream repo — which
can be force-pushed, retagged, made private or deleted. To make a build fully
**hermetic**, source acquisition becomes its own first-class, content-addressed
action (the REAPI "input root in the CAS" idea):

```
fetch(source@commit) ─┐
recipe blob ──────────┼─► build(action hash) ─► tarball (CAS)
dep tarballs ─────────┤
container digest ─────┘
```

The build action references the fetch action by hash instead of folding in a
live checkout, so every input (recipe, source, dependencies, container) is
content-addressed and preserved. Payoffs: (1) the same source reused across
recipe revisions, architectures and nearby commits is stored once; (2) rebuilds
no longer depend on upstream git being alive or immutable.

### Source artifact: base + delta

A fetch artifact is stored as a **base** plus a **delta**, so near-identical
source trees don't duplicate:

- **Git sources (preferred):** the source CAS is effectively a shared git
  object store — store objects content-addressed, write each commit as a thin
  pack against what is already present, and `git repack -ad` periodically. Git's
  own delta heuristic chooses delta bases better than any hand-rolled rule, and
  dedup across commits/arches/packages is automatic. Reconstruct = fetch base +
  thin pack, then checkout the commit.
- **Non-git / tarball sources:** the fetched tarball *is* the artifact,
  content-addressed directly; base/delta only applies if we choose to snapshot
  evolving trees as base tarball + binary patch (`xdelta`/`bsdiff`).

### SCM support

aliBuild abstracts the SCM behind `spec["scm"]` (`SCM` base in `scm.py`, with
`Git` and `Sapling` implementations). The fetch-action implementation is
currently **git-only** (`GitSourceStore` uses git bundles; `apply_refs` uses
`git update-ref`). Capture is gated on `isinstance(spec["scm"], Git)`, so
Sapling packages skip cleanly and fall back to upstream at reconstruct time —
nothing breaks, they're just not yet hermetic.

What is already SCM-agnostic: the whole CAS layer, and the refs *mapping* itself
(`scm_refs` is produced via `scm.parseRefs`, so `store_refs`/`load_refs` are
generic). Git-specific: bundle create/restore and `apply_refs`.

Generalisation (follow-up): push the snapshot/restore primitives into the SCM
abstraction — e.g. `scm.snapshotSource`/`scm.restoreSource`/`scm.applyRefs` on
`Git` and `Sapling` — so `source.py` becomes a thin generic driver over
`spec["scm"]` with the CAS layer unchanged. Sapling would use its own
bundle/clone mechanism in place of git bundles.

### Choosing the base

The base-selection rule is a **pure storage optimisation, not a correctness
input**: each fetch artifact records the exact `{baseDigest, deltaDigest}` it
used, so reconstruction follows that pointer and never re-derives the rule. The
rule can therefore be heuristic and can change over time without invalidating
anything already stored.

- Git sources: there is no rule to write — git packing chooses the bases.
- Tarball sources: a simple online greedy rule suffices — **nearest
  release-tag ancestor as the base, re-anchor past a size threshold** (e.g. when
  a delta exceeds ~50% of the base). This keeps chains depth-1 (base→target, no
  long chains), bounding both storage waste and reconstruct cost. Anchoring on
  the source's own history (nearest release tag) rather than local fetch order
  makes independent builders converge on the same base, maximising dedup; even
  if they don't, both artifacts reconstruct correctly — only dedup suffers.

The single knob (re-anchor threshold) is a space/▵ tradeoff — more bases means
more storage but smaller, faster deltas — tunable from telemetry later.

## Migration: legacy store → reapi

Existing releases in the old action-addressed store can be migrated into the
reapi layout *without rebuilding*, and made reconstruct-complete — so the old
tarball can be deleted and still regenerated. The key enabler is that every
tarball already embeds its own provenance in `.meta.json`
(`create_provenance_info`, build.py:510):

- `alidist.commit` — the exact alidist commit that produced the build;
- `defaults` — the `--defaults` name used;
- `package`: `{tag, source, version, revision, hash}`;
- `dependencies.recursive.{build,runtime}` — the full dependency DAG, each entry
  carrying its hash (i.e. exactly the AC `deps`/`runtimeDeps` action hashes).

So migration is metadata extraction, not archaeology.

### Per-release migration steps

An offline `migrate-store` batch, for each old tarball:

1. **Hash the tarball → CAS blob** (sha256); the bytes are preserved.
2. **Extract `.meta.json`** for the provenance above.
3. **Recover the full recipe** via the recorded `alidist.commit`
   (`git show <commit>:<pkg>.sh` against an alidist mirror) → recipe blob in CAS
   + `recipeDigest`. alidist is a single, well-preserved repo, far more durable
   than the scattered upstream sources.
4. **Synthesize the AC entry** (schema v2): `actionHash` = the old store hash,
   `commit`/`source`/`tag`/`defaults` from `.meta.json`, `recipeDigest` from
   step 3, `deps`/`runtimeDeps` from the recursive dependency hashes,
   `result.outputDigest` = the sha256 from step 1.
5. **(Phase 6) snapshot the source** at `commit` into the source CAS, so even
   the upstream repo disappearing doesn't block reconstruction.

### Self-verification

Because `storeHashes` is deterministic, migration **recomputes the action hash**
from the recovered recipe + commit + dependency hashes and checks it matches the
old store key. A match proves the action definition was recovered faithfully; a
mismatch (e.g. the recorded alidist commit no longer reproduces that hash) is
flagged rather than written. Migration is thus checked and auditable.

### Container provenance for legacy builds

Old builds did not record their container. The migrator supplies one:

- `--container <image[@digest]>` to set it explicitly, else
- the architecture's current default builder image — reusing alibuild's own
  derivation (`registry.cern.ch/alisw/<distro>[-arm]-builder`, build.py:448-451;
  worth factoring into a shared helper so build and migration agree).

This is a *best guess*, not the original environment, so it is marked
`"provenance": "migration-default"` (vs `"recorded"` for fresh builds) — keeping
the distinction between captured and assumed provenance explicit. This matches
the frozen-release contract: reconstruct produces a valid, equivalent build, not
a bit-identical one, and ALICE's per-architecture builder images are stable
enough that the current default almost always reproduces a functionally
equivalent artifact.

### Caveats

- Tarballs without `.meta.json` (pre-provenance) → install-only entries (closure
  from `dist-runtime` links, no recipe), flagged non-reconstructible but still
  installable / frozen.
- alidist history must reach the recorded commit (normally true; rewritten
  history would lose some recipes, flagged at step 3).
- `env`/`relocatePaths` aren't in `.meta.json`, but aren't needed for
  reconstruction: a rebuild re-derives them from the recipe + defaults.
- Migrated CAS blobs hash the legacy (non-normalized) bytes, so they won't dedup
  against future normalized rebuilds — fine for frozen releases.

## Status, decisions, and implementation log

The phase-by-phase implementation status and the (now-settled) design decisions
have moved to [`REMOTE_STORE_CAS_AC_LOGBOOK.md`](REMOTE_STORE_CAS_AC_LOGBOOK.md).
In short: the AC/CAS backend, `install`, `reconstruct` (with `--verify`,
`--rebuild`, `--rebaseline`, `--persist`), content-addressed source + refs
snapshots, validate-system actions, legacy-store `migrate`, and signing
(S0–S3 plus keyring distribution) are implemented. **The main outstanding items
are enforcement rollout (`warn` → `require`, which needs producers — notably CI —
to sign), a root-signed keyring, and Sapling source snapshots.**
