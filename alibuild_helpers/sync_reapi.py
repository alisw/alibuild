"""REAPI (Action Cache + CAS) sync backend for alibuild.

Split out of sync.py so the reapi:// store -- its content-addressed CAS, the
Action Cache ledger, retention/lifecycle handling and reconstruction helpers --
lives on its own and keeps the shared sync.py surface small. The base
Boto3RemoteSync (scheme b3://) it extends stays in sync.py; remote_from_url()
there lazy-imports this module so importing sync.py never pulls reapi in.
"""

import glob
import hashlib
import json
import os
import os.path
import re
import time
from datetime import datetime, timezone

from alibuild_helpers.log import debug, info, warning, error, dieOnError, byte_progress
from alibuild_helpers.utilities import resolve_store_path, resolve_links_path, symlink
from alibuild_helpers.utilities import resolve_cas_path, resolve_ac_path, file_digest
from alibuild_helpers.sync import Boto3RemoteSync


def add_reapi_store_args(parser, remote_help, arch_help, detected_arch, work_dir_default,
                         work_dir_help="Work directory. Default '%(default)s'."):
  """Add the reapi:// store options shared by the install/reconstruct/migrate
  subcommands: the (required) --remote-store, --insecure, the separate --ac-store
  ledger, -a/--architecture and -w/--work-dir. Per-command help text is passed in.
  Keeping this here lets each command register its own parser from its own module,
  so the reapi arg surface stays out of the shared top-level argument parser."""
  parser.add_argument("--remote-store", dest="remoteStore", metavar="STORE",
                      default="", required=True, help=remote_help)
  parser.add_argument("--insecure", dest="insecure", action="store_true",
                      help="Use http instead of https for the reapi:// endpoint.")
  parser.add_argument("--ac-store", dest="acStore", default="", metavar="STORE",
                      help="Separate reapi:// ledger store (Action Cache + reconstruction "
                           "inputs). Defaults to --remote-store.")
  parser.add_argument("-a", "--architecture", dest="architecture", metavar="ARCH",
                      default=detected_arch, help=arch_help)
  parser.add_argument("-w", "--work-dir", dest="workDir", default=work_dir_default,
                      help=work_dir_help)
  # Signature enforcement (consume side). Default "warn": verify against the
  # keyring but only log failures, so unsigned legacy stores keep working; "off"
  # skips verification, "require" fails closed. Ignored by upload/migrate, which
  # produce rather than consume.
  parser.add_argument("--require-signature", dest="requireSignature",
                      choices=("off", "warn", "require"), default="warn",
                      help="Verify Action Cache signatures against --trusted-keys: "
                           "'warn' (default; log unverified entries), 'off' (skip), "
                           "or 'require' (fail closed on any unverified entry in the "
                           "closure).")
  parser.add_argument("--trusted-keys", dest="trustedKeys", default="", metavar="KEYRING",
                      help="Path to the JSON keyring of trusted signing keys. This "
                           "REPLACES the defaults, which are the keyring shipped with "
                           "alibuild merged with keyring.json from the alidist checkout "
                           "(if any).")


class SignatureChecker:
  """Consume-side signature enforcement, shared by install and reconstruct.

  Wraps the (policy, keyring) pair and turns the pure results of
  ``signing.evaluate_closure`` into alibuild log output and, under ``require``, a
  fatal error. ``check_blob`` additionally binds the *bytes* to the signed digest
  -- a signature over an ``outputDigest`` only means something once we confirm the
  downloaded blob actually hashes to it. Only constructed when policy is not
  ``off`` (see :func:`signature_checker`), so call sites can guard on ``if checker``.
  """

  def __init__(self, policy, keyring):
    self.policy = policy
    self.keyring = keyring

  # Above this many warn-level problems, report one aggregated line per distinct
  # reason instead of one per package. A mixed store during rollout means whole
  # closures are unsigned, and a hundred identical warnings buries anything else.
  # Errors are always listed in full: under 'require' the detail is the point.
  WARN_DETAIL_LIMIT = 5

  def check_closure(self, entries):
    """Verify a whole dependency closure. ``entries`` is an iterable of AC
    entries; warns per unverified entry and dies if any fail under ``require``."""
    from alibuild_helpers import signing
    pairs = [((entry.get("action") or {}).get("package", "?"), entry)
             for entry in entries]
    allowed, problems = signing.evaluate_closure(pairs, self.keyring, self.policy)
    warns = [(package, reason) for package, level, reason in problems if level == "warn"]
    for package, level, reason in problems:
      if level != "warn":
        error("Signature check for %s: %s", package, reason)
    if len(warns) > self.WARN_DETAIL_LIMIT:
      by_reason = {}
      for package, reason in warns:
        by_reason.setdefault(reason, []).append(package)
      for reason, packages in sorted(by_reason.items()):
        warning("Signature check: %d of %d packages in the closure %s (%s%s)",
                len(packages), len(pairs), reason, ", ".join(sorted(packages)[:3]),
                ", ..." if len(packages) > 3 else "")
    else:
      for package, reason in warns:
        warning("Signature check for %s: %s", package, reason)
    dieOnError(not allowed,
               "Signature verification failed under --require-signature=require; "
               "refusing to install untrusted artifacts.")

  def check_blob(self, path, algo, content_hash, entry=None):
    """Confirm downloaded bytes hash to the digest the AC entry claims.

    Fatal when that claim is trustworthy -- policy ``require``, or an entry
    carrying a valid signature -- because then a mismatch means the bytes were
    swapped after signing, which is the attack this whole mechanism exists to
    stop. For an *unsigned* entry under ``warn`` the digest is itself an
    unverified claim (and migrated legacy entries can carry stale ones), so a
    mismatch is reported without blocking: refusing there would fail closed under
    a policy whose entire contract is that it does not.
    """
    from alibuild_helpers import signing
    actual = file_digest(path, algo)
    if actual == content_hash:
      return
    trustworthy = self.policy == signing.POLICY_REQUIRE or (
      entry is not None and signing.verify(entry, self.keyring)[0])
    detail = ("Downloaded blob hashes to %s:%s but the Action Cache entry "
              "expects %s:%s" % (algo, actual, algo, content_hash))
    dieOnError(trustworthy, detail + " -- refusing to use it.")
    warning("%s; the entry is not signed by a trusted key, so neither the bytes "
            "nor the claim are verified (policy=%s).", detail, self.policy)


def keyring_sources(args):
  """Keyrings to verify against, in merge order.

  An explicit ``--trusted-keys`` *replaces* the set -- the escape hatch for
  testing and air-gapped setups. Otherwise the keyring bundled with alibuild is
  always consulted, plus ``keyring.json`` from the alidist checkout when there is
  one (``args.configDir`` for build, ``args.alidist`` for reconstruct).

  The bundled keyring is what makes the recipe-free ``install`` verify anything
  at all: it has no alidist, so before it shipped, the default ``warn`` policy
  silently checked nothing. alidist's copy still matters -- it can add keys
  without cutting an alibuild release -- and merging cannot widen trust, so a key
  revoked in the shipped keyring stays revoked (see signing.merge_keyrings).
  """
  from alibuild_helpers import signing
  explicit = getattr(args, "trustedKeys", "") or ""
  if explicit:
    return [explicit]
  sources = [path for path in (signing.bundled_keyring_path(),)
             if os.path.exists(path)]
  alidist = getattr(args, "configDir", "") or getattr(args, "alidist", "") or ""
  if alidist and os.path.exists(os.path.join(alidist, "keyring.json")):
    sources.append(os.path.join(alidist, "keyring.json"))
  return sources


def signature_checker(args):
  """Build a :class:`SignatureChecker` from consume-side args, or ``None`` when
  verification is not in effect: policy ``off``, or policy ``warn`` (the default)
  with no keyring found at all. Policy ``require`` with no keyring fails fast."""
  from alibuild_helpers import signing
  policy = getattr(args, "requireSignature", signing.POLICY_WARN)
  if policy == signing.POLICY_OFF:
    return None
  sources = [path for path in keyring_sources(args) if os.path.exists(path)]
  if not sources:
    dieOnError(policy == signing.POLICY_REQUIRE,
               "--require-signature=require needs a keyring, but none was found: "
               "pass --trusted-keys (the keyring shipped with alibuild is missing).")
    debug("No signing keyring found; skipping signature verification (policy=%s).",
          policy)
    return None
  try:
    keyring = signing.load_keyrings(sources)
  except RuntimeError as exc:
    # 'cryptography' is an optional extra; without it we cannot verify. Under
    # 'require' that must fail closed, but the default 'warn' degrades to a
    # warning so the optional dependency stays genuinely optional.
    dieOnError(policy == signing.POLICY_REQUIRE,
               "--require-signature=require needs the 'cryptography' package: "
               "pip install alibuild[signing] (%s)" % exc)
    warning("Signature verification requested but 'cryptography' is not installed; "
            "skipping (pip install alibuild[signing]).")
    return None
  return SignatureChecker(policy, keyring)


class REAPIRemoteSync(Boto3RemoteSync):
  """S3 remote store using a REAPI-style Action Cache (AC) + CAS layout.

  Unlike Boto3RemoteSync (scheme ``b3://``), which stores each tarball under its
  *action* hash and hardcodes the CERN endpoint, this backend (scheme
  ``reapi://``):

    * stores the tarball and recipe bytes content-addressed under
      ``cas/<algo>/<h[:2]>/<h>``, so equivalent builds (e.g. tag aliases that
      share a commit) deduplicate to a single blob;
    * writes a small Action Cache entry ``ac/<arch>/<h[:2]>/<h>.json`` recording
      how the tarball was produced (recipe, commit, dependency action hashes,
      build environment), so the CAS can be reconstructed from it;
    * keeps the legacy ``TARS/store`` + symlink + ``.manifest`` layout, with the
      store object as an S3 redirect to the CAS blob, so the existing publisher
      and HttpRemoteSync keep working without duplicating bytes;
    * parameterises the endpoint, so it works against AWS, MinIO, Ceph RGW and
      CERN.

  URL form: ``reapi://<endpoint-host>/<bucket>``. The endpoint scheme defaults
  to https; pass ``insecure=True`` (aliBuild ``--insecure``) to use http, e.g.
  for a local MinIO.

  See REMOTE_STORE_CAS_AC.md for the full design.
  """

  CAS_ALGO = "sha256"
  # What a bare "reapi://<host>" means: the standard three-bucket layout, so
  # the common deployment needs no bucket spelled out anywhere. Naming a bucket
  # in the URL opts out of all of it -- a single-bucket store stays one bucket,
  # as it was before these defaults existed.
  DEFAULT_ENDPOINT_HOST = "s3.cern.ch"
  DEFAULT_CAS_BUCKET = "alibuild-cas"
  DEFAULT_AC_BUCKET = "alibuild-ac"
  DEFAULT_LEGACY_BUCKET = "alibuild-repo"
  # Where a consumer reaches DEFAULT_CAS_BUCKET. Needed because the default
  # layout puts the legacy links in a different bucket from the blobs, which
  # makes the redirect absolute; without it a bare reapi:// would die asking
  # for --cas-public-url and the default would be unusable.
  DEFAULT_CAS_PUBLIC_URL = "https://s3.cern.ch/swift/v1/alibuild-cas"
  # Object-tag lifecycle for the artifact store (see the bucket lifecycle rule,
  # ali-marathon/s3/alibuild-cas-lifecycle.xml, and REMOTE_STORE_CAS_AC.md):
  # objects tagged retention=ephemeral expire 90 days after last-modified;
  # untagged / retention=permanent are kept forever.
  RETENTION_TAG_KEY = "retention"
  EPHEMERAL_TTL_DAYS = 90
  REFRESH_WITHIN_DAYS = 30   # touch (LRU-refresh) ephemeral objects within this of expiry

  def __init__(self, remoteStore, writeStore, architecture, workdir,
               insecure=False, acStore="", acWriteStore="", storage="ephemeral",
               sign_url="", sign_token="", sign_token_file="",
               signer="alibuild", legacyStore="", casPublicUrl="") -> None:
    scheme = "http" if insecure else "https"
    read_endpoint, self.remoteStore = self._parse_reapi_url(remoteStore, scheme)
    write_endpoint, self.writeStore = self._parse_reapi_url(writeStore, scheme)
    # "reapi://<host>" with no bucket selects the default layout below. Tracked
    # rather than inferred later, because "no bucket given" and "bucket given
    # that happens to be alibuild-cas" have to behave differently: only the
    # former also moves the AC and legacy stores off the artifact bucket.
    default_layout = False
    if remoteStore and not self.remoteStore:
      self.remoteStore, default_layout = self.DEFAULT_CAS_BUCKET, True
    if writeStore and not self.writeStore:
      self.writeStore, default_layout = self.DEFAULT_CAS_BUCKET, True
    self.architecture = architecture
    self.workdir = workdir
    # Dep hashes already confirmed present in the ledger (see assert_deps_in_ledger).
    self._deps_seen = set()
    # Read and write endpoints are normally the same host; prefer the read one.
    self.endpoint_url = read_endpoint or write_endpoint
    # The artifact store (self.remoteStore/self.writeStore) holds the large,
    # deletable/regenerable output tarballs. The *ledger* store holds the small,
    # keep-forever set: Action Cache entries plus the reconstruction-input blobs
    # (recipe, source, refs). They have different lifetimes, so they can live in
    # different buckets with different retention policies -- deleting the
    # artifact store is then safe, since reconstruct rebuilds it from the ledger.
    # The ledger defaults to the artifact store (single-bucket setups), and must
    # share the endpoint (one S3 client; only the bucket differs).
    ac_read_ep, self.acRemoteStore = (
        self._parse_reapi_url(acStore, scheme) if acStore else
        ("", self.DEFAULT_AC_BUCKET if default_layout else self.remoteStore))
    ac_write_ep, self.acWriteStore = (
        self._parse_reapi_url(acWriteStore, scheme) if acWriteStore else
        ("", self.DEFAULT_AC_BUCKET if default_layout else self.writeStore))
    # Where the legacy TARS/<arch>/... link and store objects go. Defaults to
    # the artifact store, which is the single-bucket layout everything used
    # before. Point it at an existing legacy repo to keep publishing a classic
    # tree there while the bytes live content-addressed here: consumers that
    # only know TARS/ keep working, and nothing is stored twice.
    #
    # The redirect written into that tree then has to be ABSOLUTE (see
    # _cas_redirect), because a relative one resolves against whichever bucket
    # the client is reading from.
    legacy_ep, self.legacyWriteStore = (
        self._parse_reapi_url(legacyStore, scheme) if legacyStore else
        ("", self.DEFAULT_LEGACY_BUCKET if default_layout else self.writeStore))
    # Reads of the legacy tree follow its writes. Without this the split is
    # write-only: _s3_listdir and fetch_symlinks would still list the artifact
    # bucket, whose legacy tree stops being updated the moment the split is
    # turned on. Revision assignment reads that listing to learn which revisions
    # are taken, so it would see none, reassign one that already exists, and then
    # be refused by the ownership check when it tried to claim the link -- a
    # build colliding with its own publication from the day before.
    self.legacyReadStore = (self.legacyWriteStore
                            if self.legacyWriteStore != self.writeStore
                            else self.remoteStore)
    # Where a CONSUMER reaches the CAS bucket. Only needed when the legacy tree
    # is in a different bucket, because only then is the redirect absolute.
    self.casPublicUrl = casPublicUrl or (self.DEFAULT_CAS_PUBLIC_URL
                                         if default_layout else "")
    dieOnError(self.legacyWriteStore != self.writeStore and not self.casPublicUrl,
               "--legacy-links-store needs --cas-public-url: the store objects "
               "written there redirect to the CAS bucket by absolute URL, and "
               "the address this build uploads through is not necessarily one "
               "a consumer can reach")
    for endpoint in (ac_read_ep, ac_write_ep, legacy_ep):
      dieOnError(bool(endpoint) and bool(self.endpoint_url) and
                 endpoint != self.endpoint_url,
                 "the AC/ledger and legacy stores must share the endpoint with "
                 "the artifact store (%s); a cross-endpoint split is not "
                 "supported" % self.endpoint_url)
    # Artifact retention: "ephemeral" (default; LRU-expired by the bucket
    # lifecycle) or "permanent" (pinned, and promotes any ephemeral blob it
    # reuses). The ledger store is never tagged -- it is always keep-forever.
    dieOnError(storage not in ("ephemeral", "permanent"),
               "storage must be 'ephemeral' or 'permanent', not %r" % storage)
    self.storage = storage
    # Signing config for Action Cache uploads. When sign_url is set, each AC
    # entry is signed via the security-proxy sign route before it is written to
    # the ledger (see _sign_ac_entry). The build path enforces "always sign"
    # (fail closed unless --no-sign); a bare instantiation stays unsigned.
    self.sign_url = sign_url
    self.sign_token = sign_token
    self.sign_token_file = sign_token_file
    self.signer = signer
    # Consume-side signature verification. Set by the build path (see build.py)
    # to a SignatureChecker; when set, fetch_tarball verifies freshly downloaded
    # tarballs against the keyring. None means no verification (the default).
    self.verify_checker = None
    self._s3_init()

  def _cas_redirect(self, cas_path):
    """The x-amz-website-redirect-location to write on a legacy store object.

    Relative while the legacy tree lives in the artifact bucket -- which is the
    default, and what every store written so far contains. Absolute once they
    differ, because the client resolves a relative target against the bucket it
    is READING from, and that is the legacy one: it would look for the blob in
    a bucket that does not have it, and get a 404 in the middle of a download.

    The absolute form is NOT derived from our own endpoint. We may be writing
    through something the readers cannot reach -- a credential broker on
    loopback with a per-allocation port, for instance -- and this URL is baked
    into a persistent object that outlives the build. It has to be the address
    a CONSUMER uses, which only the caller knows, so it is required rather than
    guessed."""
    if self.legacyWriteStore == self.writeStore:
      return "/" + cas_path
    return "%s/%s" % (self.casPublicUrl.rstrip("/"), cas_path)

  @staticmethod
  def _parse_reapi_url(url, scheme):
    """Split ``reapi://<host>/<bucket>`` into ``(endpoint_url, bucket)``.

    Both parts are optional: a bare ``reapi://`` means the default endpoint and
    the default bucket layout, so the common deployment spells out neither."""
    if not url:
      return "", ""
    host, _, bucket = re.sub("^reapi://", "", url).partition("/")
    return ("%s://%s" % (scheme, host or REAPIRemoteSync.DEFAULT_ENDPOINT_HOST),
            bucket.strip("/"))

  def upload_symlinks_and_tarball(self, spec) -> None:
    """Publish a built package, refusing up front if its closure would dangle.

    The check has to happen before the base implementation writes anything: it
    claims the per-package link and uploads the legacy symlinks *before* calling
    _upload_tarball, so aborting from in there leaves a claimed link with no
    artifact behind it for a later build to clean up."""
    ac_entry = spec.get("ac_entry")
    if ac_entry:
      self.assert_deps_in_ledger(ac_entry["action"])
    super().upload_symlinks_and_tarball(spec)

  def _upload_tarball(self, spec, tar_path) -> None:
    """Store the tarball content-addressed in the CAS, write its Action Cache
    entry and the recipe blob, and leave the legacy store object as a redirect
    to the CAS blob.

    Ledger first, bytes last. Both orders leave a window if the process dies
    mid-publish, but they fail very differently. Blob-then-entry leaves an
    unreferenced blob and no entry: the package looks unbuilt to the store while
    the work area says it is built, so build.py skips it on every later run and it
    is never published -- unrecoverable without deleting the local artifacts by
    hand. Entry-then-blob leaves an entry whose blob is missing, which is a state
    the design already handles: fetch_tarball degrades to a rebuild, and
    reconstruct repairs it in bulk. The closure is never dangling either way,
    because dependents reference the entry."""
    local_tar = os.path.join(self.workdir, tar_path)
    content_hash = file_digest(local_tar, self.CAS_ALGO)
    cas_path = resolve_cas_path(content_hash, self.CAS_ALGO)
    output_digest = "%s:%s" % (self.CAS_ALGO, content_hash)

    ac_entry = spec.get("ac_entry")
    if ac_entry:
      # 1. Recipe blob in the *ledger* store (keep-forever reconstruction input),
      #    before the entry that names it: _recipe_intact checks it is there.
      recipe_digest = ac_entry["action"]["recipeDigest"].split(":", 1)[-1]
      recipe_cas = resolve_cas_path(recipe_digest, self.CAS_ALGO)
      if not self._exists(self.acWriteStore, recipe_cas):
        # Store the full recipe (header + body); its digest is recipeDigest.
        recipe_text = spec.get("fullRecipe") or spec.get("recipe") or ""
        self.s3.put_object(Bucket=self.acWriteStore, Key=recipe_cas,
                           Body=recipe_text.encode("utf-8", "ignore"))

      # 2. Action Cache entry. The output digest is computed from the local
      #    tarball above, so it is known before the bytes are uploaded.
      ac_entry = dict(ac_entry, result={
        "tarball": os.path.basename(tar_path),
        "outputDigest": output_digest,
        "size": os.path.getsize(local_tar),
      })
      # Sign it (over the just-set output digest) before it is written, so the
      # ledger only ever holds signed entries when signing is configured.
      ac_entry = self._sign_ac_entry(ac_entry)
      ac_path = resolve_ac_path(self.architecture, ac_entry["action"]["actionHash"])
      self.s3.put_object(Bucket=self.acWriteStore, Key=ac_path,
                         Body=json.dumps(ac_entry, indent=2, sort_keys=True)
                                .encode("utf-8"),
                         ContentType="application/json")

    # 3. Content-addressed tarball bytes. Skip the upload if an identical blob
    #    already exists -- this is where equivalent action hashes deduplicate --
    #    but promote it if this is a permanent build reusing an ephemeral blob.
    if self._exists(self.writeStore, cas_path):
      self._maybe_promote(cas_path)
      debug("CAS already has %s, not re-uploading bytes", cas_path)
    else:
      self.s3.upload_file(Bucket=self.writeStore, Key=cas_path, Filename=local_tar,
                          ExtraArgs={"Tagging": self._retention_tagging()},
                          Callback=byte_progress("upload " + cas_path,
                                                 os.path.getsize(local_tar)))

    if not ac_entry:
      debug("No Action Cache entry for %s; uploaded CAS blob only", tar_path)

    # 4. Legacy store object: a redirect to the CAS blob, so the existing
    #    publisher / HttpRemoteSync resolve it without storing the bytes twice.
    #    Goes to the legacy store, which is the artifact store unless
    #    --legacy-links-store points it elsewhere.
    self.s3.put_object(Bucket=self.legacyWriteStore, Key=tar_path,
                       Body=os.fsencode(cas_path),
                       WebsiteRedirectLocation=self._cas_redirect(cas_path))

  def _sign_ac_entry(self, ac_entry):
    """Sign an AC entry (with its result already set) via the security-proxy
    sign route, returning a copy with a ``signatures`` list and schemaVersion 3.

    A no-op when signing is not configured (``sign_url`` empty) -- the build path
    is what guarantees "always sign" by refusing to upload unsigned unless
    --no-sign; a direct instantiation without sign_url uploads unsigned."""
    if not self.sign_url:
      return ac_entry
    from alibuild_helpers import signing
    signature = signing.sign_via_proxy(ac_entry, self.sign_url,
                                       self._current_sign_token(), self.signer)
    signed = dict(ac_entry, schemaVersion=3)
    signed["signatures"] = [signature]
    return signed

  def _current_sign_token(self):
    """The credential to present to the sign route, resolved *per request*.

    ``sign_token_file`` is read fresh every time rather than cached, because the
    credential may be short-lived and refreshed in place underneath us: a Nomad
    workload-identity JWT has a TTL of minutes, while a release build signs Action
    Cache entries for as long as it runs. Capturing it once at startup -- which is
    what a literal ``--sign-token`` does -- would work for the first upload of a
    long build and fail for the rest.
    """
    if self.sign_token_file:
      try:
        with open(self.sign_token_file) as handle:
          token = handle.read().strip()
      except OSError as exc:
        dieOnError(True, "cannot read the signing credential from %s: %s"
                   % (self.sign_token_file, exc))
      dieOnError(not token, "the signing credential file %s is empty; if it holds a "
                 "short-lived token, it may not have been renewed yet."
                 % self.sign_token_file)
      return token
    dieOnError(not self.sign_token,
               "signing a reapi:// upload needs a credential: pass --sign-token or "
               "--sign-token-file (or --no-sign to upload unsigned).")
    return self.sign_token

  def _verify_download(self, spec, entry, tar_path, algo="", content_hash=""):
    """Verify a freshly downloaded tarball before the build reuses it, when a
    verifier is configured (build path). The AC entry must carry a trusted
    signature (policy-enforced) and the bytes must hash to the signed output
    digest. A missing AC entry (legacy/unsigned tarball) is treated as unsigned:
    warns, or fails under --require-signature=require."""
    if not self.verify_checker:
      return
    if entry is None:
      self.verify_checker.check_closure([{"action": {"package": spec["package"]}}])
      return
    self.verify_checker.check_closure([entry])
    if content_hash:
      self.verify_checker.check_blob(tar_path, algo, content_hash, entry)

  def _exists(self, bucket, key):
    """Return whether key exists in the given bucket."""
    from botocore.exceptions import ClientError
    debug("S3 head_object %s/%s", bucket, key)
    try:
      self.s3.head_object(Bucket=bucket, Key=key)
    except ClientError:
      return False
    return True

  # --- Ledger store: AC entries + reconstruction-input blobs (recipe/source/
  #     refs). Small, keep-forever; read from acRemoteStore, write acWriteStore.

  def read_ac_entry(self, action_hash):
    """Return the parsed Action Cache entry for action_hash, or None if absent."""
    from botocore.exceptions import ClientError
    ac_path = resolve_ac_path(self.architecture, action_hash)
    debug("S3 get_object %s/%s (read AC)", self.acRemoteStore, ac_path)
    try:
      obj = self.s3.get_object(Bucket=self.acRemoteStore, Key=ac_path)
    except ClientError:
      return None
    return json.loads(obj["Body"].read())

  def is_published(self, action_hash):
    """Whether an action is fully published: its Action Cache entry exists *and* the
    CAS blob that entry names is present.

    Both halves matter. A locally built package proves nothing about the store: an
    earlier run may have been interrupted between building and publishing, or have
    built against a different store, and the entry would be missing. And an entry
    whose blob is gone (expired ephemeral artifact, or a publish interrupted between
    entry and bytes) is not something a dependent can be published against either.

    Two HEAD-class requests, no download -- the blob is checked by presence, since it
    is content-addressed and its key is its own digest."""
    entry = self.read_ac_entry(action_hash)
    if entry is None:
      return False
    algo, _, content_hash = (entry.get("result") or {}).get("outputDigest", "").partition(":")
    if not content_hash:
      # validate-system nodes produce no tarball: the entry alone is the artifact.
      return (entry.get("action") or {}).get("kind") == "validate-system"
    return self._exists(self.remoteStore, resolve_cas_path(content_hash, algo))

  def download_blob(self, content_hash, dest, algo="sha256"):
    """Download a ledger (input) blob -- e.g. a source bundle -- to dest."""
    self.s3.download_file(Bucket=self.acRemoteStore,
                          Key=resolve_cas_path(content_hash, algo), Filename=dest)

  def read_blob(self, content_hash, algo="sha256"):
    """Return the bytes of a ledger (input) blob -- e.g. a recipe or refs blob."""
    return self.s3.get_object(Bucket=self.acRemoteStore,
                              Key=resolve_cas_path(content_hash, algo))["Body"].read()

  def put_file_as_blob(self, path, algo="sha256"):
    """Upload a ledger (input) blob from a file -- e.g. a source bundle. Dedups.
    Returns the content hash."""
    content_hash = file_digest(path, algo)
    cas_path = resolve_cas_path(content_hash, algo)
    if not self._exists(self.acWriteStore, cas_path):
      self.s3.upload_file(Bucket=self.acWriteStore, Key=cas_path, Filename=path)
    return content_hash

  def put_bytes_as_blob(self, data, algo="sha256"):
    """Upload an in-memory ledger (input) blob -- e.g. a refs blob. Dedups."""
    content_hash = hashlib.new(algo, data).hexdigest()
    cas_path = resolve_cas_path(content_hash, algo)
    if not self._exists(self.acWriteStore, cas_path):
      self.s3.put_object(Bucket=self.acWriteStore, Key=cas_path, Body=data)
    return content_hash

  def read_object_json(self, key):
    """Return the JSON object at key in the ledger store, or None."""
    from botocore.exceptions import ClientError
    try:
      obj = self.s3.get_object(Bucket=self.acRemoteStore, Key=key)
    except ClientError:
      return None
    return json.loads(obj["Body"].read())

  def write_object_json(self, key, obj):
    """Write a small JSON object at key in the ledger store."""
    self.s3.put_object(Bucket=self.acWriteStore, Key=key,
                       Body=json.dumps(obj, sort_keys=True).encode("utf-8"),
                       ContentType="application/json")

  # --- Artifact store: large, deletable/regenerable output tarball blobs;
  #     read from remoteStore, write writeStore.

  def _retention_tagging(self):
    """The retention tag to apply to freshly uploaded artifact blobs."""
    return "%s=%s" % (self.RETENTION_TAG_KEY, self.storage)

  def _retention_of(self, bucket, key):
    """Return the retention tag value of an object, or None if untagged/absent."""
    from botocore.exceptions import ClientError
    try:
      tags = self.s3.get_object_tagging(Bucket=bucket, Key=key)["TagSet"]
    except ClientError:
      return None
    return next((t["Value"] for t in tags if t["Key"] == self.RETENTION_TAG_KEY), None)

  def _maybe_promote(self, cas_path):
    """When uploading as 'permanent' and the blob already exists tagged
    ephemeral, promote it to permanent so it is no longer LRU-expired."""
    if self.storage != "permanent":
      return
    if self._retention_of(self.writeStore, cas_path) == "ephemeral":
      self.s3.put_object_tagging(
        Bucket=self.writeStore, Key=cas_path,
        Tagging={"TagSet": [{"Key": self.RETENTION_TAG_KEY, "Value": "permanent"}]})
      debug("Promoted %s from ephemeral to permanent", cas_path)

  def put_artifact_blob(self, path, algo="sha256"):
    """Upload an output tarball to the artifact CAS keyed by content hash,
    tagged with the current retention. Dedups; promotes on a permanent reuse."""
    content_hash = file_digest(path, algo)
    cas_path = resolve_cas_path(content_hash, algo)
    if self._exists(self.writeStore, cas_path):
      self._maybe_promote(cas_path)
    else:
      size = os.path.getsize(path)
      debug("S3 upload_file %s/%s (%d bytes)", self.writeStore, cas_path, size)
      self.s3.upload_file(Bucket=self.writeStore, Key=cas_path, Filename=path,
                          ExtraArgs={"Tagging": self._retention_tagging()},
                          Callback=byte_progress("upload " + cas_path, size))
    return content_hash

  def _touch_if_expiring(self, cas_path):
    """LRU-refresh: if the blob is ephemeral and within REFRESH_WITHIN_DAYS of
    its EPHEMERAL_TTL_DAYS expiry, copy it onto itself (preserving the tag) to
    reset last-modified. Best-effort and only when we can write the same bucket."""
    from botocore.exceptions import ClientError
    if not self.writeStore or self.writeStore != self.remoteStore:
      return
    try:
      if self._retention_of(self.remoteStore, cas_path) != "ephemeral":
        return
      head = self.s3.head_object(Bucket=self.remoteStore, Key=cas_path)
      age_days = (datetime.now(timezone.utc) - head["LastModified"]).days
      if age_days < self.EPHEMERAL_TTL_DAYS - self.REFRESH_WITHIN_DAYS:
        return
      debug("Refreshing ephemeral %s (%d days old)", cas_path, age_days)
      self.s3.copy_object(Bucket=self.writeStore, Key=cas_path,
                          CopySource={"Bucket": self.remoteStore, "Key": cas_path},
                          MetadataDirective="COPY", TaggingDirective="COPY")
    except ClientError as exc:
      debug("Could not refresh %s: %s", cas_path, exc)

  def download_artifact(self, content_hash, dest, algo="sha256"):
    """Download an output tarball blob from the artifact store to dest, LRU-
    refreshing it if it is ephemeral and close to expiry."""
    cas_path = resolve_cas_path(content_hash, algo)
    self._touch_if_expiring(cas_path)
    debug("S3 download_file %s/%s", self.remoteStore, cas_path)
    self.s3.download_file(Bucket=self.remoteStore, Key=cas_path, Filename=dest)

  def artifact_blob_exists(self, content_hash, algo="sha256"):
    """Return whether an output tarball blob exists in the artifact store."""
    return self._exists(self.remoteStore, resolve_cas_path(content_hash, algo))

  def is_fully_migrated(self, architecture, package, tarball, verrev=None):
    """Whether `tarball` is already in the reapi store, by either route.

    migrate_put writes the per-package link LAST, so its presence means the whole
    entry (tarball + recipe + AC + redirect + link) is complete -- a cheap
    completion marker for idempotent re-runs, and one the AC cannot give because
    it is written earlier. That is the first check.

    It is not sufficient alone. A package published by a BUILD puts its link
    wherever that build's --legacy-links-store points, and migrate has no such
    option: it can only look in its own store. So a package the release already
    published perfectly -- blob, recipe, AC entry, redirect stub in the shared
    legacy bucket -- looked unmigrated here and was retried every round. It then
    downloaded the 78-byte stub over --read-store (a plain GET, which does not
    follow the redirect) and reported "file could not be opened successfully".
    Seventeen packages of the ubuntu2204 O2Suite closure did that, every round.

    Hence the fallback: ask the Action Cache, which is the same question a BUILD
    asks before reusing something (is_published: entry present AND blob present).
    If that holds, migrating again would rewrite identical bytes and an identical
    entry, and could only add a legacy link in a bucket no consumer of this store
    reads. verrev is optional so older callers keep the link-only behaviour.
    """
    if self._exists(self.legacyWriteStore,
                    os.path.join(resolve_links_path(architecture, package), tarball)):
      return True
    if not verrev:
      return False
    version, _, revision = verrev.rpartition("-")
    action_hash = self.resolve_action_hash(package, version, revision or None)
    return bool(action_hash) and self.is_published(action_hash)

  def iter_ac_entry_hashes(self, architecture):
    """Yield the action hash of every Action Cache entry under ac/<arch>/ in the
    ledger. Used to walk a migrated set for source enrichment without the old
    store or a closure enumeration."""
    prefix = "ac/%s/" % architecture
    pages = self.s3.get_paginator("list_objects_v2") \
                   .paginate(Bucket=self.acRemoteStore, Prefix=prefix)
    for page in pages:
      for item in page.get("Contents", ()):
        key = item["Key"]
        if key.endswith(".json"):
          yield os.path.basename(key)[:-len(".json")]

  def assert_deps_in_ledger(self, action):
    """Refuse to publish an entry whose dependencies are not in the ledger.

    Nothing else notices a hole: deps are serialised as hashes without being
    resolved, and the consume-side check_closure only evaluates signature policy
    over entries a client already resolved -- an absent dep never becomes an entry.
    reconstruct then dies on the closure long afterwards, and AC entries are
    keep-forever, so the hole is permanent.

    The usual cause is a package that was already built locally and therefore never
    uploaded (build.py skips it as "in sync with whatever remote store", inferring
    remote presence from local), or an earlier run that failed part-way through a
    closure."""
    missing = [dep for dep in action.get("deps", ())
               if dep["actionHash"] not in self._deps_seen and
               not self._exists(self.acWriteStore,
                                resolve_ac_path(self.architecture, dep["actionHash"]))]
    dieOnError(bool(missing),
               "refusing to publish %s: %d of its dependencies have no Action Cache "
               "entry in %s, so the closure would be unresolvable:\n%s\n"
               "Rebuild them into the store -- delete their install dir and tarballs "
               "(TARS/, including the store/ blob) and build again; the action hash is "
               "unchanged, so this entry's references stay valid." % (
                 action.get("package", "?"), len(missing), self.acWriteStore,
                 "\n".join("  %s %s" % (dep["actionHash"], dep["package"])
                           for dep in missing)))
    # Only reached when all resolved: remember them so a closure of N packages
    # sharing dependencies costs one HEAD per distinct dep, not per dependent.
    self._deps_seen.update(dep["actionHash"] for dep in action.get("deps", ()))

  def put_ac_entry(self, entry, recipe_text="", sign=False):
    """Write an Action Cache entry that has no output tarball (e.g. a
    'validate-system' action for a system/prefer_system package): its recipe blob
    (a reconstruction input) plus the entry itself, both in the ledger. No CAS
    blob, redirect or link -- there is no artifact. Idempotent (dedups the recipe,
    overwrites the entry). No-op on a read-only store (no ledger write target).

    With sign=True (and signing configured) the entry is signed over its
    recipeDigest -- signed_payload falls back to it when there is no output digest
    -- so a validate-system node in a closure is trusted like any other under
    --require-signature. Callers that must never sign (migrate: legacy provenance
    reconstructed after the fact) leave sign=False."""
    if not self.acWriteStore:
      return
    if sign:
      entry = self._sign_ac_entry(entry)
    action = entry["action"]
    recipe_digest = action.get("recipeDigest", "").split(":", 1)[-1]
    if recipe_digest:
      recipe_cas = resolve_cas_path(recipe_digest, self.CAS_ALGO)
      if not self._exists(self.acWriteStore, recipe_cas):
        debug("S3 put_object %s/%s (recipe, %s)", self.acWriteStore, recipe_cas,
              action.get("kind", "build"))
        self.s3.put_object(Bucket=self.acWriteStore, Key=recipe_cas,
                           Body=(recipe_text or "").encode("utf-8", "ignore"))
    ac_path = resolve_ac_path(self.architecture, action["actionHash"])
    debug("S3 put_object %s/%s (%s AC entry)", self.acWriteStore, ac_path,
          action.get("kind", "build"))
    self.s3.put_object(Bucket=self.acWriteStore, Key=ac_path,
                       Body=json.dumps(entry, indent=2, sort_keys=True).encode("utf-8"),
                       ContentType="application/json")

  def update_ac_entry(self, entry):
    """Overwrite an existing Action Cache entry in the ledger -- e.g. to add a
    source snapshot to an already-migrated release. The entry is keyed by its
    own action hash, so this rewrites in place and preserves the result block."""
    ac_path = resolve_ac_path(self.architecture, entry["action"]["actionHash"])
    debug("S3 put_object %s/%s (update AC entry)", self.acWriteStore, ac_path)
    self.s3.put_object(Bucket=self.acWriteStore, Key=ac_path,
                       Body=json.dumps(entry, indent=2, sort_keys=True).encode("utf-8"),
                       ContentType="application/json")

  @staticmethod
  def _highest_revision(candidates):
    """Pick the entry with the highest revision: numeric first, else lexicographic."""
    def sort_key(item):
      rev = item[0]
      return (1, int(rev)) if rev.isdigit() else (0, rev)
    return max(candidates, key=sort_key)

  def resolve_action_hash(self, package, version, revision=None):
    """Resolve a human label (package, version[, revision]) to an action hash.

    Primary path: the per-package symlink objects written at upload time. Those
    only exist for actions that produced a *tarball*, so a validate-system node
    (``make``, ``yacc-like``, ...) has none and used to be unaddressable by name
    -- the failure even pointed at the CAS, which is the wrong place to look for
    something that deliberately has no artifact. Hence the fallback: scan the
    ledger, which describes every action whether or not it produced bytes.

    With no revision, the highest available one for the version is chosen.
    Returns None if nothing matches.
    """
    hit = self._resolve_via_links(package, version, revision)
    return hit if hit is not None else self._resolve_via_ac(package, version, revision)

  def _resolve_via_ac(self, package, version, revision=None):
    """Resolve a label by scanning the Action Cache. O(entries for the arch), so
    this is the fallback rather than the primary path."""
    prefix = os.path.dirname(resolve_ac_path(self.architecture, "0" * 40)).rsplit("/", 1)[0]
    pages = self.s3.get_paginator("list_objects_v2") \
                   .paginate(Bucket=self.acRemoteStore, Prefix=prefix.rstrip("/") + "/")
    candidates = []
    for page in pages:
      for item in page.get("Contents", ()):
        if not item["Key"].endswith(".json"):
          continue
        entry = self.read_ac_entry(os.path.basename(item["Key"])[:-len(".json")])
        action = (entry or {}).get("action") or {}
        if action.get("package") != package or str(action.get("version")) != str(version):
          continue
        if revision is not None and str(action.get("revision")) != str(revision):
          continue
        candidates.append((str(action.get("revision", "")), action.get("actionHash")))
    if not candidates:
      return None
    return self._highest_revision(candidates)[1]

  def _resolve_via_links(self, package, version, revision=None):
    links_path = resolve_links_path(self.architecture, package)
    name_prefix = "%s-%s-" % (package, version)
    name_suffix = ".%s.tar.gz" % self.architecture
    candidates = []   # (revision, link key)
    for key in self._s3_listdir(links_path):
      name = os.path.basename(key)
      if name.startswith(name_prefix) and name.endswith(name_suffix):
        candidates.append((name[len(name_prefix):-len(name_suffix)], key))
    if revision is not None:
      candidates = [(rev, key) for rev, key in candidates if rev == str(revision)]
    if not candidates:
      return None
    _, link_key = self._highest_revision(candidates)
    # link_key came out of _s3_listdir, which reads the legacy tree; its body has
    # to be read from the same place. Reading it from the artifact bucket only
    # worked while the two were one bucket -- the same mistake as the byte fetch
    # in Boto3RemoteSync.fetch_tarball, in the one other spot that pairs a
    # legacy key with a bucket.
    target = os.fsdecode(self.s3.get_object(Bucket=self.legacyReadStore,
                                            Key=link_key)["Body"].read())
    match = re.search(r"store/[0-9a-f]{2}/([0-9a-f]+)/", target)
    return match.group(1) if match else None

  def migrate_put(self, ac_entry, tarball_path, recipe_text):
    """Write a migrated legacy release into the reapi store: the tarball as a
    CAS blob, the recovered recipe blob, the Action Cache entry, plus the legacy
    store redirect and per-package link so it stays installable and
    publisher-compatible. Returns the tarball's content hash.

    Migrated entries are intentionally left *unsigned*: their provenance is
    reconstructed after the fact, so a signature would falsely assert a trusted
    signer built them. They are consumed as legacy (tolerated under
    --require-signature=warn, refused under require). Do not sign here."""
    action = ac_entry["action"]
    arch, pkg = action["architecture"], action["package"]
    action_hash = action["actionHash"]
    tarball = "{package}-{version}-{revision}.{arch}.tar.gz".format(arch=arch, **action)

    # Tarball -> artifact store; recipe + AC -> ledger store.
    content_hash = self.put_artifact_blob(tarball_path, self.CAS_ALGO)
    cas_path = resolve_cas_path(content_hash, self.CAS_ALGO)

    recipe_digest = action["recipeDigest"].split(":", 1)[-1]
    recipe_cas = resolve_cas_path(recipe_digest, self.CAS_ALGO)
    if not self._exists(self.acWriteStore, recipe_cas):
      debug("S3 put_object %s/%s (recipe)", self.acWriteStore, recipe_cas)
      self.s3.put_object(Bucket=self.acWriteStore, Key=recipe_cas,
                         Body=(recipe_text or "").encode("utf-8", "ignore"))

    entry = dict(ac_entry, result={
      "tarball": tarball,
      "outputDigest": "%s:%s" % (self.CAS_ALGO, content_hash),
      "size": os.path.getsize(tarball_path),
    })
    ac_path = resolve_ac_path(arch, action_hash)
    debug("S3 put_object %s/%s (AC entry)", self.acWriteStore, ac_path)
    self.s3.put_object(Bucket=self.acWriteStore, Key=ac_path,
                       Body=json.dumps(entry, indent=2, sort_keys=True).encode("utf-8"),
                       ContentType="application/json")

    store_key = os.path.join(resolve_store_path(arch, action_hash), tarball)
    debug("S3 put_object %s/%s (store redirect)", self.writeStore, store_key)
    self.s3.put_object(Bucket=self.legacyWriteStore, Key=store_key,
                       Body=os.fsencode(cas_path),
                       WebsiteRedirectLocation=self._cas_redirect(cas_path))

    link_target = "../../%s/store/%s/%s/%s" % (arch, action_hash[:2], action_hash, tarball)
    link_key = os.path.join(resolve_links_path(arch, pkg), tarball)
    debug("S3 put_object %s/%s (link)", self.writeStore, link_key)
    # The link stays RELATIVE: it points at the store object beside it in the
    # same tree, and the client reads its body rather than following the header.
    self.s3.put_object(Bucket=self.legacyWriteStore, Key=link_key,
                       Body=link_target.encode("utf-8"),
                       WebsiteRedirectLocation=link_target)
    return content_hash

  def put_legacy_artifact(self, package, version, revision, tarball_path):
    """Store a pre-provenance legacy tarball (no .meta.json, so no recipe can be
    recovered) so its version-revision is reserved in the store and it stays
    installable. Writes: the CAS blob (content-addressed), a *legacy* AC entry
    (kind='legacy', keyed by the tarball's content hash in place of an action hash,
    with no recipe or deps), and the legacy store redirect + per-package link. The
    kind='legacy' entry distinguishes these preserved-but-non-reconstructable
    artifacts from full builds and validate-system entries in the ledger.
    Idempotent (content-addressed dedup). Returns the content hash."""
    arch = self.architecture
    tarball = "{package}-{version}-{revision}.{arch}.tar.gz".format(
      package=package, version=version, revision=revision, arch=arch)
    content_hash = self.put_artifact_blob(tarball_path, self.CAS_ALGO)
    cas_path = resolve_cas_path(content_hash, self.CAS_ALGO)

    # Legacy AC entry: no recipe/deps (no provenance), keyed by the content hash.
    entry = {
      "schemaVersion": 2,
      "action": {
        "kind": "legacy", "package": package, "version": version,
        "revision": revision, "architecture": arch, "actionHash": content_hash,
      },
      "result": {
        "tarball": tarball, "outputDigest": "%s:%s" % (self.CAS_ALGO, content_hash),
        "size": os.path.getsize(tarball_path),
      },
    }
    ac_path = resolve_ac_path(arch, content_hash)
    debug("S3 put_object %s/%s (legacy AC entry)", self.acWriteStore, ac_path)
    self.s3.put_object(Bucket=self.acWriteStore, Key=ac_path,
                       Body=json.dumps(entry, indent=2, sort_keys=True).encode("utf-8"),
                       ContentType="application/json")

    store_key = os.path.join(resolve_store_path(arch, content_hash), tarball)
    debug("S3 put_object %s/%s (legacy store redirect)", self.writeStore, store_key)
    self.s3.put_object(Bucket=self.legacyWriteStore, Key=store_key,
                       Body=os.fsencode(cas_path),
                       WebsiteRedirectLocation=self._cas_redirect(cas_path))

    link_target = "../../%s/store/%s/%s/%s" % (arch, content_hash[:2], content_hash, tarball)
    link_key = os.path.join(resolve_links_path(arch, package), tarball)
    debug("S3 put_object %s/%s (legacy link)", self.writeStore, link_key)
    # The link stays RELATIVE: it points at the store object beside it in the
    # same tree, and the client reads its body rather than following the header.
    self.s3.put_object(Bucket=self.legacyWriteStore, Key=link_key,
                       Body=link_target.encode("utf-8"),
                       WebsiteRedirectLocation=link_target)
    return content_hash

  def rebaseline_ac_entry(self, entry, tarball_path, recipe_text=""):
    """Re-baseline an existing AC entry onto a freshly rebuilt tarball whose
    content hash differs from the recorded one (e.g. a legacy pre-normalisation
    build). Writes the new CAS blob, then rewrites the entry's outputDigest and
    the store redirect + link -- all keyed by the *unchanged* action hash, so it
    is an in-place pointer swap. The new blob is stored *before* the AC entry is
    repointed, so a failure never leaves the entry dangling; the old blob is left
    orphaned (delete it separately via delete_artifact_blob). The retention of the
    blob being replaced is preserved (untagged == keep-forever == permanent).
    Returns (old_hash, new_hash, old_cas_path)."""
    old_digest = (entry.get("result") or {}).get("outputDigest", "")
    old_hash = old_digest.split(":", 1)[-1]
    old_cas_path = resolve_cas_path(old_hash, self.CAS_ALGO) if old_hash else None
    # Preserve the retention of the blob we are replacing (untagged => permanent).
    prev_storage = self.storage
    if old_cas_path:
      self.storage = self._retention_of(self.writeStore, old_cas_path) or "permanent"
    try:
      new_hash = self.migrate_put(
        {k: v for k, v in entry.items() if k != "result"}, tarball_path, recipe_text)
    finally:
      self.storage = prev_storage
    return old_hash, new_hash, old_cas_path

  def delete_artifact_blob(self, content_hash, algo="sha256"):
    """Delete an output tarball blob from the artifact store by content hash.
    Used to reclaim the blob orphaned by a re-baseline. Safe to call on the
    artifact store only -- ledger blobs are keep-forever and never deleted here."""
    cas_path = resolve_cas_path(content_hash, algo)
    debug("S3 delete_object %s/%s (orphaned blob)", self.writeStore, cas_path)
    self.s3.delete_object(Bucket=self.writeStore, Key=cas_path)

  def fetch_tarball(self, spec) -> None:
    """Resolve the tarball via the Action Cache (action hash -> AC entry ->
    output digest -> CAS blob). Falls back to the legacy store layout when no
    AC entry exists, so mixed / migrating stores keep working."""
    from botocore.exceptions import ClientError

    # If we already have a tarball with any equivalent hash, don't hit S3.
    for pkg_hash in spec["remote_hashes"]:
      store_path = resolve_store_path(self.architecture, pkg_hash)
      if glob.glob(os.path.join(self.workdir, store_path, "%s-*.tar.gz" % spec["package"])):
        debug("Reusing existing tarball for %s@%s", spec["package"], pkg_hash)
        return

    saw_ac_entry = False
    for pkg_hash in spec["remote_hashes"]:
      ac_path = resolve_ac_path(self.architecture, pkg_hash)
      try:
        obj = self.s3.get_object(Bucket=self.acRemoteStore, Key=ac_path)
      except ClientError:
        continue
      entry = json.loads(obj["Body"].read())
      result = entry.get("result", {})
      digest = result.get("outputDigest", "")
      if ":" not in digest:
        debug("AC entry %s has no usable output digest", ac_path)
        continue
      saw_ac_entry = True
      algo, _, content_hash = digest.partition(":")
      cas_path = resolve_cas_path(content_hash, algo)
      store_path = resolve_store_path(self.architecture, pkg_hash)
      tarball = result.get("tarball") or \
        "{package}-{version}-{revision}.{arch}.tar.gz".format(arch=self.architecture, **spec)
      dest = os.path.join(self.workdir, store_path, tarball)
      os.makedirs(os.path.join(self.workdir, store_path), exist_ok=True)
      debug("Fetching CAS blob %s for %s@%s", cas_path, spec["package"], pkg_hash)
      # The AC entry exists but its CAS blob may not (an ephemeral artifact that
      # expired, or one deleted for reconstruction). fetch_tarball's contract is
      # to leave the local tarball absent so the caller rebuilds -- a missing blob
      # must degrade to a rebuild, never crash the whole build.
      try:
        meta = self.s3.head_object(Bucket=self.remoteStore, Key=cas_path)
        total_size = int(meta.get("ContentLength", 0))
        debug("Downloading tarball for %s@%s: %s (%d MB)", spec["package"],
              spec["version"], cas_path, total_size >> 20)
        # boto3 invokes Callback with the per-chunk *delta*, not the cumulative
        # total; byte_progress accumulates it (a raw delta looks stuck at 256 KB).
        self.s3.download_file(
          Bucket=self.remoteStore, Key=cas_path, Filename=dest,
          Callback=byte_progress("download %s@%s" % (spec["package"], spec["version"]),
                                 total_size))
        # Verify the freshly downloaded bytes against the keyring (build path)
        # before the build trusts them; fails closed under --require-signature.
        self._verify_download(spec, entry, dest, algo, content_hash)
        return
      except ClientError:
        warning("CAS blob %s for %s@%s is missing though its AC entry exists; "
                "it will be rebuilt.", cas_path, spec["package"], pkg_hash)
        continue

    # Only fall back to the legacy store layout when there was no usable AC entry
    # at all (a mixed / pre-AC store). If an AC entry was found but its blob was
    # gone, return empty so the package is rebuilt, rather than resurrecting a
    # stale legacy redirect that points at the same missing blob.
    if saw_ac_entry:
      debug("AC entries for %s reference missing CAS blobs; leaving it to rebuild.",
            spec["package"])
      return
    debug("No Action Cache entry for %s with hashes %s; trying legacy store",
          spec["package"], ", ".join(spec["remote_hashes"]))
    fetched = super().fetch_tarball(spec)
    # A legacy tarball has no AC entry, hence no signature: let the policy decide.
    if self.verify_checker and fetched:
      self._verify_download(spec, None, fetched[1])
