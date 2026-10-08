---
name: s3-conditional-writes
description: Use this skill when the b3:// S3 backend fails with "your boto3/botocore is too old to publish", when asked to support an S3 store that does not implement conditional writes (If-None-Match on PUT), or when changing how packages are claimed and published in Boto3RemoteSync.
version: 0.1.0
---

# Conditional writes in the b3:// backend

Publishing a package writes two objects with no transaction spanning them:

1. `TARS/<arch>/<pkg>/<pkg>-<ver>-<rev>.<arch>.tar.gz` — a symlink object whose
   body is the store path of the tarball.
2. `TARS/<arch>/store/<xx>/<hash>/<tarball>` — the tarball itself.

The symlink is written first, with `IfNoneMatch="*"`, which makes it an atomic
claim: a second build publishing the same package gets a 412 instead of
silently overwriting. `Boto3RemoteSync._put_link()` does this, and it is the
only write to that key -- completing a publish already established as ours
skips it, because `_link_is_ours()` has just verified the body is what we would
write. There is deliberately no unconditional overwrite anywhere, so no
`IfMatch` is needed (its RGW support is unmeasured in any case).

**This is a hard requirement, checked at startup.**
`_check_conditional_write_support()` runs from `_s3_init()` whenever a write
store is configured, and exits with an actionable message if botocore cannot
send the parameter. Read-only use is unaffected.

## Why supporting stores without it was rejected

A store that does not implement conditional writes **ignores** `If-None-Match`
rather than rejecting it. It returns 200 for a claim that should have failed,
so the fallback is undetectable from the response: the code would believe it
held an exclusive claim while actually running the old check-then-act logic.
Silently degrading a mutual-exclusion guarantee is worse than refusing to run.

CERN's Ceph RGW was measured to enforce it (a second
`put_object(..., IfNoneMatch="*")` on an existing key returns
`PreconditionFailed`). AWS S3 has supported it since August 2024.

## What re-adding compatibility would take

Only do this if a store that genuinely cannot honour the header has to be
supported. In rough order:

1. **Detect the client side.** Restore the probe as a predicate rather than a
   fatal check:
   ```python
   "IfNoneMatch" in self.s3.meta.service_model \
       .operation_model("PutObject").input_shape.members
   ```
   Cache it on the instance; it cannot change at runtime. This is cheap,
   offline and reliable.

2. **Decide about the store side, which is not detectable.** There is no
   read-only probe. The only conclusive test is writing the same key twice with
   `IfNoneMatch="*"` and seeing whether the second attempt returns 412, which
   means a write to the real store at startup. Options, none free:
   - trust a config flag / URL parameter set by whoever runs the build;
   - probe once against a throwaway key and cache the answer;
   - accept the degradation silently, which is what this design refuses.

3. **Gate the claim.** Give `_put_link` a flag and fall back to a plain
   `put_object` when unsupported.

4. **Keep the recovery path intact.** `_link_is_ours()` and the
   partial-publish completion in `upload_symlinks_and_tarball` do not depend on
   conditional writes and must keep working either way — they are what makes a
   claim stranded by a killed build recoverable at all.

5. **Test both paths.** The removed test asserted no `IfNoneMatch` appears in
   any `put_object` call when support is absent; the surviving
   `test_symlink_claimed_conditionally` asserts the opposite when it is
   present. Reinstate the pair, parameterising the fixture helper
   `fresh_upload_sync()` on support.

## Known residual race

A symlink deleted between our claim failing and our reading it aborts the
publish rather than retrying. Retrying does not help: the same race can hit the
retry, and a deleter can remove the link after a successful write anyway.
Nothing in aliBuild deletes links, so this needs a cleanup job running
concurrently with a build.

## Invariants not to break

- **Partial dist directories are rewritten, not treated as conflicts.** Safe
  only because the package symlink claim arbitrates ownership of the revision,
  and foreign builds die before writing anything; do not loosen one without
  the other.
- **The tarball is written last.** `aliPublishS3` treats a tarball appearing
  under `store/` as its signal to publish and reads the package's runtime
  dependencies from `dist-runtime/`. An incomplete listing there is not an
  error, it is a package published with dependencies missing — so every
  symlink must be in place before the tarball becomes visible.
- **A claim must stay recoverable.** With conditional writes and no recovery
  logic, a build killed between the claim and the tarball would strand a
  symlink no later build could ever retake.
- **Losing a claim to the same hash is not fatal**, but the winner must not be
  assumed to have finished: check for the tarball, and upload if it is absent.
  The winner may have died mid-publish, and liveness is not observable.
