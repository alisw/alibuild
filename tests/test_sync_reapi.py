"""Tests for the reapi:// sync backend (REAPIRemoteSync), split out of
test_sync.py to mirror the sync.py / sync_reapi.py source split."""

import io
import json
import os
import os.path
import unittest
from unittest.mock import patch, MagicMock

from alibuild_helpers import sync
from alibuild_helpers import sync_reapi
from alibuild_helpers import signing
from alibuild_helpers.utilities import resolve_links_path, resolve_store_path
from alibuild_helpers.utilities import resolve_cas_path, resolve_ac_path

# `cryptography` is an optional extra (`pip install alibuild[signing]`), so the
# tests that really sign or build a keyring must skip where it is absent. The
# upload tests below mock sign_via_proxy and so need nothing.
try:
    import cryptography    # noqa: F401
    HAVE_CRYPTOGRAPHY = True
except ImportError:
    HAVE_CRYPTOGRAPHY = False

requires_crypto = unittest.skipUnless(
    HAVE_CRYPTOGRAPHY, "needs the optional 'cryptography' extra")


# Shared fixtures (kept local so this module stands alone).
ARCHITECTURE = "slc7_x86-64"
PACKAGE = "zlib"
SEED = bytes(range(32))


def one_key_ring(seed=SEED, signer="ci"):
    keyid, pub = signing.public_key(seed)
    return signing.load_keyring({"keys": {keyid: {"publicKey": pub, "signer": signer}}})


def tarball_name(spec):
    return ("{package}-{version}-{revision}.{arch}.tar.gz"
            .format(arch=ARCHITECTURE, **spec))


REAPI_HASH = "deadbeef" * 5     # 40 hex chars, like a real action hash
REAPI_RECIPE_DIGEST = "a" * 64
REAPI_CONTENT_HASH = "c" * 64
REAPI_SPEC = {
    "package": PACKAGE, "version": "v1.3.1", "revision": "1",
    "hash": REAPI_HASH,
    "remote_revision_hash": REAPI_HASH,
    "remote_hashes": [REAPI_HASH],
    "recipe": "build steps here",
    "ac_entry": {
        "schemaVersion": 1,
        "action": {
            "actionHash": REAPI_HASH,
            "recipeDigest": "sha256:" + REAPI_RECIPE_DIGEST,
        },
    },
}


@patch("os.makedirs", new=MagicMock(return_value=None))
@patch("alibuild_helpers.sync.symlink", new=MagicMock(return_value=None))
@patch("alibuild_helpers.sync.ProgressPrint", new=MagicMock())
@patch("alibuild_helpers.log.error", new=MagicMock())
@patch("alibuild_helpers.sync_reapi.REAPIRemoteSync._s3_init", new=MagicMock())
class REAPIRemoteSyncTestCase(unittest.TestCase):
    """Check the reapi:// (Action Cache + CAS) remote store."""

    def make_sync(self, client):
        reapi = sync_reapi.REAPIRemoteSync(
            remoteStore="reapi://localhost/bucket",
            writeStore="reapi://localhost/bucket",
            architecture=ARCHITECTURE, workdir="/sw")
        reapi.s3 = client
        return reapi

    def make_client(self, existing=()):
        """Mock S3 client: head_object 404s unless the key is in `existing`,
        and all directory listings are empty (so uploads see no conflicts)."""
        from botocore.exceptions import ClientError

        def head_object(Bucket, Key):
            if Key in existing:
                return {"ContentLength": 4096}
            raise ClientError({"Error": {"Code": "404"}}, "head_object")

        return MagicMock(
            head_object=MagicMock(side_effect=head_object),
            get_paginator=lambda method: MagicMock(
                paginate=lambda **kw: [{"Contents": []}]),
            put_object=MagicMock(return_value=None),
            upload_file=MagicMock(return_value=None),
            download_file=MagicMock(return_value=None),
        )

    def put_keys(self, client):
        return [c.kwargs["Key"] for c in client.put_object.call_args_list]

    def test_resolve_falls_back_to_the_ledger_for_tarball_less_actions(self):
        """A validate-system action produces no tarball, hence no per-package link,
        and used to be unaddressable by name -- with an error that pointed at the
        CAS. It must resolve by scanning the Action Cache instead."""
        entry = {"schemaVersion": 2,
                 "action": {"kind": "validate-system", "package": "make",
                            "version": "4", "revision": "1",
                            "architecture": ARCHITECTURE, "actionHash": "ahash-make"}}
        ac_key = "ac/%s/ah/ahash-make.json" % ARCHITECTURE

        def get_object(Bucket, Key):
            if Key == ac_key:
                return {"Body": io.BytesIO(json.dumps(entry).encode())}
            raise AssertionError("unexpected get_object %s" % Key)

        client = self.make_client()
        # No links anywhere; one AC entry in the ledger listing.
        client.get_paginator = lambda method: MagicMock(
            paginate=lambda **kw: ([{"Contents": [{"Key": ac_key}]}]
                                   if kw.get("Prefix", "").startswith("ac/") else
                                   [{"Contents": []}]))
        client.get_object = MagicMock(side_effect=get_object)
        sync = self.make_sync(client)
        self.assertEqual(sync.resolve_action_hash("make", "4", "1"), "ahash-make")
        # A revision that does not exist must still resolve to nothing.
        self.assertIsNone(sync.resolve_action_hash("make", "4", "9"))

    def test_parse_url(self) -> None:
        self.assertEqual(
            sync_reapi.REAPIRemoteSync._parse_reapi_url("reapi://s3.cern.ch/alibuild-repo", "https"),
            ("https://s3.cern.ch", "alibuild-repo"))
        self.assertEqual(
            sync_reapi.REAPIRemoteSync._parse_reapi_url("reapi://localhost:9000/bkt", "http"),
            ("http://localhost:9000", "bkt"))
        self.assertEqual(sync_reapi.REAPIRemoteSync._parse_reapi_url("", "https"), ("", ""))

    def test_factory(self) -> None:
        obj = sync.remote_from_url("reapi://s3.example/bucket",
                                   "reapi://s3.example/bucket", ARCHITECTURE, "/sw")
        self.assertIsInstance(obj, sync_reapi.REAPIRemoteSync)
        self.assertEqual(obj.remoteStore, "bucket")
        self.assertEqual(obj.endpoint_url, "https://s3.example")

    @patch("alibuild_helpers.sync_reapi.file_digest",
           new=MagicMock(return_value=REAPI_CONTENT_HASH))
    @patch("os.path.getsize", new=MagicMock(return_value=4096))
    @patch("os.listdir",
           new=lambda path: [tarball_name(REAPI_SPEC)] if path.endswith("-1") else [])
    @patch("os.readlink", new=MagicMock(return_value="../../store/de/dead/x.tar.gz"))
    @patch("os.path.islink", new=MagicMock(return_value=True))
    def test_upload_writes_cas_ac_redirect(self) -> None:
        client = self.make_client()
        reapi = self.make_sync(client)
        reapi.upload_symlinks_and_tarball(REAPI_SPEC)

        cas_path = resolve_cas_path(REAPI_CONTENT_HASH)
        recipe_cas = resolve_cas_path(REAPI_RECIPE_DIGEST)
        ac_path = resolve_ac_path(ARCHITECTURE, REAPI_HASH)
        store_key = resolve_store_path(ARCHITECTURE, REAPI_HASH) + "/" + tarball_name(REAPI_SPEC)

        # Tarball bytes go to the CAS via upload_file (content-addressed).
        client.upload_file.assert_called_once()
        self.assertEqual(client.upload_file.call_args.kwargs["Key"], cas_path)

        keys = self.put_keys(client)
        self.assertIn(recipe_cas, keys)   # recipe blob stored in CAS
        self.assertIn(ac_path, keys)      # Action Cache entry written
        self.assertIn(store_key, keys)    # legacy store object written

        # The legacy store object is a redirect to the CAS blob, not the bytes.
        redirect = next(c for c in client.put_object.call_args_list
                        if c.kwargs["Key"] == store_key)
        self.assertEqual(redirect.kwargs["WebsiteRedirectLocation"], "/" + cas_path)

        # The AC entry records the output digest pointing at the CAS blob.
        ac_call = next(c for c in client.put_object.call_args_list
                       if c.kwargs["Key"] == ac_path)
        entry = json.loads(ac_call.kwargs["Body"])
        self.assertEqual(entry["result"]["outputDigest"],
                         "sha256:" + REAPI_CONTENT_HASH)
        self.assertEqual(entry["result"]["size"], 4096)

    @patch("alibuild_helpers.sync_reapi.file_digest",
           new=MagicMock(return_value=REAPI_CONTENT_HASH))
    @patch("os.path.getsize", new=MagicMock(return_value=4096))
    @patch("os.listdir",
           new=lambda path: [tarball_name(REAPI_SPEC)] if path.endswith("-1") else [])
    @patch("os.readlink", new=MagicMock(return_value="../../store/de/dead/x.tar.gz"))
    @patch("os.path.islink", new=MagicMock(return_value=True))
    def test_upload_routes_ledger_and_artifact_to_separate_stores(self) -> None:
        client = self.make_client()
        reapi = sync_reapi.REAPIRemoteSync(
            remoteStore="reapi://localhost/artifacts",
            writeStore="reapi://localhost/artifacts",
            architecture=ARCHITECTURE, workdir="/sw",
            acStore="reapi://localhost/ledger",
            acWriteStore="reapi://localhost/ledger")
        reapi.s3 = client
        reapi.upload_symlinks_and_tarball(REAPI_SPEC)

        cas_path = resolve_cas_path(REAPI_CONTENT_HASH)
        recipe_cas = resolve_cas_path(REAPI_RECIPE_DIGEST)
        ac_path = resolve_ac_path(ARCHITECTURE, REAPI_HASH)
        store_key = resolve_store_path(ARCHITECTURE, REAPI_HASH) + "/" + tarball_name(REAPI_SPEC)
        bucket_of = {c.kwargs["Key"]: c.kwargs["Bucket"]
                     for c in client.put_object.call_args_list}

        # Keep-forever ledger: AC entry + recipe blob.
        self.assertEqual(bucket_of[ac_path], "ledger")
        self.assertEqual(bucket_of[recipe_cas], "ledger")
        # Deletable artifact store: tarball bytes + legacy redirect/link.
        self.assertEqual(client.upload_file.call_args.kwargs["Bucket"], "artifacts")
        self.assertEqual(client.upload_file.call_args.kwargs["Key"], cas_path)
        self.assertEqual(bucket_of[store_key], "artifacts")

    @patch("alibuild_helpers.sync_reapi.file_digest",
           new=MagicMock(return_value=REAPI_CONTENT_HASH))
    @patch("os.path.getsize", new=MagicMock(return_value=4096))
    @patch("os.listdir",
           new=lambda path: [tarball_name(REAPI_SPEC)] if path.endswith("-1") else [])
    @patch("os.readlink", new=MagicMock(return_value="../../store/de/dead/x.tar.gz"))
    @patch("os.path.islink", new=MagicMock(return_value=True))
    def test_upload_dedups_existing_cas_blob(self) -> None:
        # The CAS already has the tarball bytes (e.g. from an equivalent hash).
        client = self.make_client(existing={resolve_cas_path(REAPI_CONTENT_HASH)})
        reapi = self.make_sync(client)
        reapi.upload_symlinks_and_tarball(REAPI_SPEC)
        # We must not re-upload identical bytes, but we still write the AC entry.
        client.upload_file.assert_not_called()
        self.assertIn(resolve_ac_path(ARCHITECTURE, REAPI_HASH), self.put_keys(client))

    @patch("alibuild_helpers.sync_reapi.file_digest",
           new=MagicMock(return_value=REAPI_CONTENT_HASH))
    @patch("os.path.getsize", new=MagicMock(return_value=4096))
    @patch("os.listdir",
           new=lambda path: [tarball_name(REAPI_SPEC)] if path.endswith("-1") else [])
    @patch("os.readlink", new=MagicMock(return_value="../../store/de/dead/x.tar.gz"))
    @patch("os.path.islink", new=MagicMock(return_value=True))
    @patch("alibuild_helpers.signing.sign_via_proxy")
    def test_upload_signs_ac_entry_when_configured(self, sign_via_proxy) -> None:
        sign_via_proxy.return_value = {"keyid": "kid", "signer": "ci", "sig": "s"}
        client = self.make_client()
        reapi = sync_reapi.REAPIRemoteSync(
            remoteStore="reapi://localhost/bucket", writeStore="reapi://localhost/bucket",
            architecture=ARCHITECTURE, workdir="/sw",
            sign_url="https://proxy/sign/alibuild-ac", sign_token="tok", signer="ci")
        reapi.s3 = client
        reapi.upload_symlinks_and_tarball(REAPI_SPEC)

        ac_call = next(c for c in client.put_object.call_args_list
                       if c.kwargs["Key"] == resolve_ac_path(ARCHITECTURE, REAPI_HASH))
        entry = json.loads(ac_call.kwargs["Body"])
        self.assertEqual(entry["signatures"],
                         [{"keyid": "kid", "signer": "ci", "sig": "s"}])
        self.assertEqual(entry["schemaVersion"], 3)
        # It signs the entry *after* the output digest is set, so the signature
        # binds the uploaded tarball.
        signed_entry = sign_via_proxy.call_args.args[0]
        self.assertEqual(signed_entry["result"]["outputDigest"],
                         "sha256:" + REAPI_CONTENT_HASH)

    @patch("alibuild_helpers.sync_reapi.file_digest",
           new=MagicMock(return_value=REAPI_CONTENT_HASH))
    @patch("os.path.getsize", new=MagicMock(return_value=4096))
    @patch("os.listdir",
           new=lambda path: [tarball_name(REAPI_SPEC)] if path.endswith("-1") else [])
    @patch("os.readlink", new=MagicMock(return_value="../../store/de/dead/x.tar.gz"))
    @patch("os.path.islink", new=MagicMock(return_value=True))
    def test_upload_unsigned_by_default(self) -> None:
        # No sign_url configured: the AC entry is written without signatures.
        client = self.make_client()
        reapi = self.make_sync(client)
        reapi.upload_symlinks_and_tarball(REAPI_SPEC)
        ac_call = next(c for c in client.put_object.call_args_list
                       if c.kwargs["Key"] == resolve_ac_path(ARCHITECTURE, REAPI_HASH))
        self.assertNotIn("signatures", json.loads(ac_call.kwargs["Body"]))

    def test_sign_without_token_aborts(self) -> None:
        # Signing configured (sign_url) but no gate token: fail closed.
        reapi = sync_reapi.REAPIRemoteSync(
            remoteStore="reapi://localhost/bucket", writeStore="reapi://localhost/bucket",
            architecture=ARCHITECTURE, workdir="/sw",
            sign_url="https://proxy/sign/alibuild-ac", sign_token="")
        self.assertRaises(SystemExit, reapi._sign_ac_entry,
                          {"action": {"actionHash": "h"}, "result": {}})

    # --- validate-system entries (no tarball) sign over their recipe digest. ---

    def _validate_system_entry(self):
        rd = "b" * 64
        return {"schemaVersion": 2, "action": {
            "kind": "validate-system", "package": "make", "version": "v1",
            "revision": "1", "architecture": ARCHITECTURE, "actionHash": rd,
            "recipeDigest": "sha256:" + rd, "deps": []}}

    def _written_ac(self, client, action_hash):
        ac_path = resolve_ac_path(ARCHITECTURE, action_hash)
        call = next(c for c in client.put_object.call_args_list
                    if c.kwargs["Key"] == ac_path)
        return json.loads(call.kwargs["Body"])

    @patch("alibuild_helpers.signing.sign_via_proxy")
    def test_put_ac_entry_signs_over_recipe_digest_when_requested(self, sign_via_proxy) -> None:
        sign_via_proxy.return_value = {"keyid": "kid", "signer": "ci", "sig": "s"}
        client = self.make_client()
        reapi = sync_reapi.REAPIRemoteSync(
            remoteStore="reapi://localhost/bucket", writeStore="reapi://localhost/bucket",
            architecture=ARCHITECTURE, workdir="/sw",
            sign_url="https://proxy/sign/alibuild-ac", sign_token="tok", signer="ci")
        reapi.s3 = client
        entry = self._validate_system_entry()
        reapi.put_ac_entry(entry, "recipe text", sign=True)

        written = self._written_ac(client, entry["action"]["actionHash"])
        self.assertEqual(written["signatures"], [{"keyid": "kid", "signer": "ci", "sig": "s"}])
        self.assertEqual(written["schemaVersion"], 3)
        # It binds the recipe digest: a validate-system entry has no result block.
        self.assertNotIn("result", sign_via_proxy.call_args.args[0])

    def test_put_ac_entry_unsigned_when_signing_not_configured(self) -> None:
        # sign=True requested but no sign_url (e.g. build --no-sign): stays unsigned.
        client = self.make_client()
        reapi = self.make_sync(client)
        entry = self._validate_system_entry()
        reapi.put_ac_entry(entry, "recipe text", sign=True)
        self.assertNotIn("signatures", self._written_ac(client, entry["action"]["actionHash"]))

    @patch("alibuild_helpers.signing.sign_via_proxy",
           new=MagicMock(return_value={"keyid": "k", "signer": "s", "sig": "x"}))
    @requires_crypto
    def test_put_ac_entry_default_never_signs(self) -> None:
        # migrate calls put_ac_entry() with the default sign=False, so it never
        # signs even on a sync that has signing configured.
        client = self.make_client()
        reapi = sync_reapi.REAPIRemoteSync(
            remoteStore="reapi://localhost/bucket", writeStore="reapi://localhost/bucket",
            architecture=ARCHITECTURE, workdir="/sw",
            sign_url="https://proxy/sign/alibuild-ac", sign_token="tok")
        reapi.s3 = client
        entry = self._validate_system_entry()
        reapi.put_ac_entry(entry, "recipe text")   # default sign=False
        self.assertNotIn("signatures", self._written_ac(client, entry["action"]["actionHash"]))

    # --- Consume side: verifying prebuilt tarballs reused during a build. The
    #     reapi fetch_tarball resolves via the AC entry (get_object) then the CAS
    #     blob (head/download), so we mock the S3 client at those seams. ---

    def _signed_entry(self, seed=SEED):
        entry = {
            "action": {"actionHash": REAPI_HASH, "package": PACKAGE,
                       "architecture": ARCHITECTURE, "recipeDigest": "sha256:r"},
            "result": {"outputDigest": "sha256:" + REAPI_CONTENT_HASH,
                       "tarball": tarball_name(REAPI_SPEC), "size": 4096},
        }
        if seed is not None:
            entry["signatures"] = [signing.sign(entry, seed, "ci")]
        return entry

    def _ac_client(self, entry=None, blob_missing=False):
        """S3 client whose AC get_object returns `entry` (ClientError if None),
        the CAS head_object is present unless blob_missing, and download is a
        no-op."""
        from botocore.exceptions import ClientError

        def get_object(Bucket, Key):
            if entry is None:
                raise ClientError({"Error": {"Code": "404"}}, "get_object")
            body = MagicMock(read=MagicMock(return_value=json.dumps(entry).encode()))
            return {"Body": body}

        def head_object(Bucket, Key):
            if blob_missing:
                raise ClientError({"Error": {"Code": "404"}}, "head_object")
            return {"ContentLength": 4096}

        return MagicMock(get_object=MagicMock(side_effect=get_object),
                         head_object=MagicMock(side_effect=head_object),
                         download_file=MagicMock())

    def _with_checker(self, client, policy, keyring=None):
        reapi = self.make_sync(client)
        reapi.verify_checker = sync_reapi.SignatureChecker(
            policy, keyring if keyring is not None else one_key_ring())
        return reapi

    @patch("alibuild_helpers.sync_reapi.glob.glob", new=MagicMock(return_value=[]))
    @patch("alibuild_helpers.sync_reapi.file_digest",
           new=MagicMock(return_value=REAPI_CONTENT_HASH))
    @requires_crypto
    def test_fetch_verifies_signed_download(self) -> None:
        # Signed entry + bytes matching the signed digest + trusted key: no raise.
        reapi = self._with_checker(self._ac_client(self._signed_entry()), "require")
        reapi.fetch_tarball(REAPI_SPEC)
        reapi.s3.download_file.assert_called_once()

    @patch("alibuild_helpers.sync_reapi.glob.glob", new=MagicMock(return_value=[]))
    @patch("alibuild_helpers.sync_reapi.file_digest",
           new=MagicMock(return_value=REAPI_CONTENT_HASH))
    @requires_crypto
    def test_fetch_rejects_unsigned_under_require(self) -> None:
        reapi = self._with_checker(
            self._ac_client(self._signed_entry(seed=None)), "require")
        self.assertRaises(SystemExit, reapi.fetch_tarball, REAPI_SPEC)

    @patch("alibuild_helpers.sync_reapi.glob.glob", new=MagicMock(return_value=[]))
    @patch("alibuild_helpers.sync_reapi.file_digest",
           new=MagicMock(return_value="f" * 64))   # bytes != signed digest
    @requires_crypto
    def test_fetch_rejects_tampered_blob(self) -> None:
        reapi = self._with_checker(self._ac_client(self._signed_entry()), "require")
        self.assertRaises(SystemExit, reapi.fetch_tarball, REAPI_SPEC)

    @patch("alibuild_helpers.sync_reapi.glob.glob", new=MagicMock(return_value=[]))
    @patch("alibuild_helpers.sync_reapi.file_digest",
           new=MagicMock(return_value=REAPI_CONTENT_HASH))
    @requires_crypto
    def test_fetch_signed_under_warn_ok(self) -> None:
        reapi = self._with_checker(self._ac_client(self._signed_entry()), "warn")
        reapi.fetch_tarball(REAPI_SPEC)   # no raise

    @patch("alibuild_helpers.sync.Boto3RemoteSync.fetch_tarball",
           new=MagicMock(return_value=(REAPI_HASH, "/sw/store/x.tar.gz")))
    @patch("alibuild_helpers.sync_reapi.glob.glob", new=MagicMock(return_value=[]))
    @requires_crypto
    def test_fetch_legacy_unsigned_rejected_under_require(self) -> None:
        # No AC entry: falls back to the legacy store; an unsigned legacy tarball
        # must fail closed under require, and be tolerated under warn.
        self.assertRaises(SystemExit, self._with_checker(
            self._ac_client(entry=None), "require").fetch_tarball, REAPI_SPEC)
        self._with_checker(self._ac_client(entry=None), "warn").fetch_tarball(REAPI_SPEC)

    @patch("alibuild_helpers.sync.Boto3RemoteSync.fetch_tarball",
           new=MagicMock(return_value=None))   # legacy path downloaded nothing
    @patch("alibuild_helpers.sync_reapi.glob.glob", new=MagicMock(return_value=[]))
    @requires_crypto
    def test_fetch_skips_verification_when_nothing_downloaded(self) -> None:
        # No AC entry and legacy fetch found nothing: verification never runs, so
        # even a require policy does not abort.
        self._with_checker(self._ac_client(entry=None), "require").fetch_tarball(REAPI_SPEC)

    @patch("alibuild_helpers.sync_reapi.file_digest",
           new=MagicMock(return_value=REAPI_CONTENT_HASH))
    @patch("os.path.getsize", new=MagicMock(return_value=4096))
    @patch("os.listdir",
           new=lambda path: [tarball_name(REAPI_SPEC)] if path.endswith("-1") else [])
    @patch("os.readlink", new=MagicMock(return_value="../../store/de/dead/x.tar.gz"))
    @patch("os.path.islink", new=MagicMock(return_value=True))
    def test_upload_tags_ephemeral_by_default(self) -> None:
        client = self.make_client()
        reapi = self.make_sync(client)   # default storage = ephemeral
        reapi.upload_symlinks_and_tarball(REAPI_SPEC)
        self.assertEqual(client.upload_file.call_args.kwargs["ExtraArgs"],
                         {"Tagging": "retention=ephemeral"})

    @patch("alibuild_helpers.sync_reapi.file_digest",
           new=MagicMock(return_value=REAPI_CONTENT_HASH))
    @patch("os.path.getsize", new=MagicMock(return_value=4096))
    @patch("os.listdir",
           new=lambda path: [tarball_name(REAPI_SPEC)] if path.endswith("-1") else [])
    @patch("os.readlink", new=MagicMock(return_value="../../store/de/dead/x.tar.gz"))
    @patch("os.path.islink", new=MagicMock(return_value=True))
    def test_permanent_build_promotes_ephemeral_blob(self) -> None:
        # The blob already exists tagged ephemeral; a permanent build promotes it.
        client = self.make_client(existing={resolve_cas_path(REAPI_CONTENT_HASH)})
        client.get_object_tagging = MagicMock(
            return_value={"TagSet": [{"Key": "retention", "Value": "ephemeral"}]})
        client.put_object_tagging = MagicMock()
        reapi = sync_reapi.REAPIRemoteSync("reapi://localhost/bucket", "reapi://localhost/bucket",
                                     architecture=ARCHITECTURE, workdir="/sw",
                                     storage="permanent")
        reapi.s3 = client
        reapi.upload_symlinks_and_tarball(REAPI_SPEC)
        client.upload_file.assert_not_called()        # deduped, not re-uploaded
        client.put_object_tagging.assert_called_once()
        self.assertEqual(client.put_object_tagging.call_args.kwargs["Tagging"],
                         {"TagSet": [{"Key": "retention", "Value": "permanent"}]})

    @patch("os.path.getsize", new=MagicMock(return_value=4096))
    def test_rebaseline_rewrites_digest_preserving_retention(self) -> None:
        old_hash, new_hash = "a" * 64, "b" * 64
        client = self.make_client()
        # The blob being replaced is tagged permanent -> the new one must be too.
        client.get_object_tagging = MagicMock(
            return_value={"TagSet": [{"Key": "retention", "Value": "permanent"}]})
        reapi = self.make_sync(client)   # default storage = ephemeral
        entry = {
            "schemaVersion": 2,
            "action": {"package": "zlib", "version": "v1", "revision": "1",
                       "architecture": ARCHITECTURE, "actionHash": REAPI_HASH,
                       "recipeDigest": "sha256:" + REAPI_RECIPE_DIGEST},
            "result": {"tarball": "zlib-v1-1.%s.tar.gz" % ARCHITECTURE,
                       "outputDigest": "sha256:" + old_hash, "size": 1},
        }
        with patch("alibuild_helpers.sync_reapi.file_digest", return_value=new_hash):
            oh, nh, old_cas = reapi.rebaseline_ac_entry(entry, "/tmp/zlib.tar.gz", "recipe")
        self.assertEqual((oh, nh), (old_hash, new_hash))
        self.assertEqual(old_cas, resolve_cas_path(old_hash))
        # New blob uploaded at the rebuilt content hash, tagged permanent (preserved).
        self.assertEqual(client.upload_file.call_args.kwargs["Key"],
                         resolve_cas_path(new_hash))
        self.assertEqual(client.upload_file.call_args.kwargs["ExtraArgs"],
                         {"Tagging": "retention=permanent"})
        # AC entry rewritten in place with the new outputDigest.
        ac_path = resolve_ac_path(ARCHITECTURE, REAPI_HASH)
        ac_put = next(c for c in client.put_object.call_args_list
                      if c.kwargs["Key"] == ac_path)
        body = json.loads(ac_put.kwargs["Body"].decode())
        self.assertEqual(body["result"]["outputDigest"], "sha256:" + new_hash)
        # storage restored to its original value afterwards (no leak).
        self.assertEqual(reapi.storage, "ephemeral")

    @patch("alibuild_helpers.sync_reapi.file_digest", new=MagicMock(return_value="e" * 64))
    @patch("os.path.getsize", new=MagicMock(return_value=4096))
    def test_put_legacy_artifact(self) -> None:
        client = self.make_client()
        reapi = self.make_sync(client)
        ch = reapi.put_legacy_artifact("zlib", "v1.2.8", "1", "/tmp/zlib.tar.gz")
        self.assertEqual(ch, "e" * 64)
        # Bytes go to the CAS content-addressed.
        self.assertEqual(client.upload_file.call_args.kwargs["Key"], resolve_cas_path("e" * 64))
        keys = self.put_keys(client)
        tarball = "zlib-v1.2.8-1.%s.tar.gz" % ARCHITECTURE
        self.assertIn(resolve_store_path(ARCHITECTURE, "e" * 64) + "/" + tarball, keys)  # redirect
        self.assertIn(resolve_links_path(ARCHITECTURE, "zlib") + "/" + tarball, keys)    # link
        # A kind='legacy' AC entry is written (keyed by the content hash), but no
        # recipe blob (there is no provenance to reconstruct from).
        ac_path = resolve_ac_path(ARCHITECTURE, "e" * 64)
        self.assertIn(ac_path, keys)
        ac_put = next(c for c in client.put_object.call_args_list
                      if c.kwargs["Key"] == ac_path)
        entry = json.loads(ac_put.kwargs["Body"].decode())
        self.assertEqual(entry["action"]["kind"], "legacy")
        self.assertEqual(entry["result"]["outputDigest"], "sha256:" + "e" * 64)
        self.assertNotIn("recipeDigest", entry["action"])   # no provenance

    def test_delete_artifact_blob(self) -> None:
        client = self.make_client()
        client.delete_object = MagicMock()
        reapi = self.make_sync(client)
        reapi.delete_artifact_blob("b" * 64)
        client.delete_object.assert_called_once_with(
            Bucket="bucket", Key=resolve_cas_path("b" * 64))

    @patch("os.path.exists", new=MagicMock(return_value=False))
    def test_download_refreshes_old_ephemeral(self) -> None:
        from datetime import datetime, timezone, timedelta
        client = self.make_client()
        client.get_object_tagging = MagicMock(
            return_value={"TagSet": [{"Key": "retention", "Value": "ephemeral"}]})
        client.head_object = MagicMock(
            return_value={"LastModified": datetime.now(timezone.utc) - timedelta(days=75)})
        client.copy_object = MagicMock()
        reapi = sync_reapi.REAPIRemoteSync("reapi://localhost/bucket", "reapi://localhost/bucket",
                                     architecture=ARCHITECTURE, workdir="/sw",
                                     storage="permanent")
        reapi.s3 = client
        reapi.download_artifact(REAPI_CONTENT_HASH, "/tmp/x")
        client.copy_object.assert_called_once()       # LRU-refreshed (75d >= 60d)

        client.copy_object.reset_mock()
        client.head_object = MagicMock(
            return_value={"LastModified": datetime.now(timezone.utc) - timedelta(days=10)})
        reapi.download_artifact(REAPI_CONTENT_HASH, "/tmp/x")
        client.copy_object.assert_not_called()        # fresh (10d < 60d), no refresh

    @patch("glob.glob", new=MagicMock(return_value=[]))
    @patch("os.makedirs", new=MagicMock())
    def test_fetch_via_action_cache(self) -> None:
        cas_path = resolve_cas_path(REAPI_CONTENT_HASH)
        # The CAS blob exists, so head_object (for its size) succeeds.
        client = self.make_client(existing={cas_path})
        ac_path = resolve_ac_path(ARCHITECTURE, REAPI_HASH)
        entry = {"result": {"tarball": tarball_name(REAPI_SPEC),
                            "outputDigest": "sha256:" + REAPI_CONTENT_HASH}}

        def get_object(Bucket, Key):
            if Key == ac_path:
                return {"Body": MagicMock(read=lambda: json.dumps(entry).encode())}
            raise NotImplementedError(Key)
        client.get_object = MagicMock(side_effect=get_object)

        reapi = self.make_sync(client)
        reapi.fetch_tarball(REAPI_SPEC)

        # We downloaded the CAS blob to the local action-store path.
        client.download_file.assert_called_once()
        self.assertEqual(client.download_file.call_args.kwargs["Key"], cas_path)
        self.assertTrue(client.download_file.call_args.kwargs["Filename"].endswith(
            resolve_store_path(ARCHITECTURE, REAPI_HASH) + "/" + tarball_name(REAPI_SPEC)))


@patch("alibuild_helpers.sync_reapi.REAPIRemoteSync._s3_init", new=MagicMock())
class REAPIDefaultLayoutTestCase(unittest.TestCase):
    """A bare reapi:// URL selects the standard endpoint and bucket layout."""

    def test_bare_url_selects_default_endpoint_and_buckets(self) -> None:
        reapi = sync_reapi.REAPIRemoteSync(
            remoteStore="reapi://", writeStore="reapi://",
            architecture=ARCHITECTURE, workdir="/sw")
        self.assertEqual(reapi.endpoint_url, "https://s3.cern.ch")
        self.assertEqual(reapi.remoteStore, "alibuild-cas")
        self.assertEqual(reapi.writeStore, "alibuild-cas")
        self.assertEqual(reapi.acRemoteStore, "alibuild-ac")
        self.assertEqual(reapi.acWriteStore, "alibuild-ac")
        self.assertEqual(reapi.legacyWriteStore, "alibuild-repo")
        # The legacy links land in a different bucket from the blobs, so the
        # redirect is absolute and needs a consumer-reachable CAS URL. Without
        # a default the bare form would die on the --cas-public-url check.
        self.assertEqual(reapi.casPublicUrl,
                         "https://s3.cern.ch/swift/v1/alibuild-cas")

    def test_explicit_bucket_opts_out_of_the_split(self) -> None:
        """Naming a bucket keeps the single-bucket behaviour, so stores that
        predate these defaults are unaffected."""
        reapi = sync_reapi.REAPIRemoteSync(
            remoteStore="reapi://localhost/bucket",
            writeStore="reapi://localhost/bucket",
            architecture=ARCHITECTURE, workdir="/sw")
        self.assertEqual(reapi.endpoint_url, "https://localhost")
        for store in (reapi.acRemoteStore, reapi.acWriteStore,
                      reapi.legacyWriteStore):
            self.assertEqual(store, "bucket")
        self.assertEqual(reapi.casPublicUrl, "")

    def test_explicit_flags_still_win_over_defaults(self) -> None:
        reapi = sync_reapi.REAPIRemoteSync(
            remoteStore="reapi://", writeStore="reapi://",
            architecture=ARCHITECTURE, workdir="/sw",
            acStore="reapi:///ledger", acWriteStore="reapi:///ledger",
            legacyStore="reapi:///old", casPublicUrl="https://example/cas")
        self.assertEqual(reapi.acRemoteStore, "ledger")
        self.assertEqual(reapi.legacyWriteStore, "old")
        self.assertEqual(reapi.casPublicUrl, "https://example/cas")




@patch("alibuild_helpers.sync_reapi.REAPIRemoteSync._s3_init", new=MagicMock())
@patch("alibuild_helpers.sync.Boto3RemoteSync._s3_init", new=MagicMock())
class LegacyReadStoreTestCase(unittest.TestCase):
    """The legacy tree must be READ from wherever it is WRITTEN.

    --legacy-links-store used to redirect only the writes. Every read -- the
    symlink listing, the manifest, the per-link fetch -- stayed on the artifact
    bucket, whose legacy tree stops being updated the moment the split is turned
    on. The consequence was not a missing file but a wrong number: revision
    assignment learns which revisions are taken from that listing, so it saw
    none, reassigned a revision that already existed, and was then refused by the
    ownership check while claiming a link the same builder had written the day
    before. One bucket for both directions, or neither.
    """

    def test_split_makes_reads_follow_writes(self):
        reapi = sync_reapi.REAPIRemoteSync(
            remoteStore="reapi://localhost/cas", writeStore="reapi://localhost/cas",
            architecture=ARCHITECTURE, workdir="/sw",
            legacyStore="reapi://localhost/legacy",
            casPublicUrl="https://example/cas")
        self.assertEqual(reapi.legacyWriteStore, "legacy")
        self.assertEqual(reapi.legacyReadStore, "legacy",
                         "reads must follow the split, not stay on the artifact bucket")

    def test_unsplit_reads_the_artifact_bucket(self):
        """No split -> unchanged behaviour, so plain reapi:// stores are unaffected."""
        reapi = sync_reapi.REAPIRemoteSync(
            remoteStore="reapi://localhost/bucket", writeStore="reapi://localhost/bucket",
            architecture=ARCHITECTURE, workdir="/sw")
        self.assertEqual(reapi.legacyWriteStore, "bucket")
        self.assertEqual(reapi.legacyReadStore, "bucket")

    @patch("os.makedirs", new=MagicMock(return_value=None))
    @patch("os.listdir", new=MagicMock(return_value=[]))
    @patch("alibuild_helpers.sync.symlink", new=MagicMock(return_value=None))
    def test_symlink_discovery_never_touches_the_artifact_bucket(self):
        """The behavioural half: with the tree split, no read may address the CAS
        bucket. This is the test that would have caught the bug -- the constructor
        assertions above only pin the wiring, while this pins what it is for."""
        buckets = []
        client = MagicMock(
            get_paginator=lambda method: MagicMock(
                paginate=lambda **kw: (buckets.append(kw["Bucket"]),
                                       [{"Contents": [{"Key": "TARS/x/zlib/z-1-1.tar.gz"}]}])[1]),
            get_object=MagicMock(side_effect=lambda Bucket, Key: (
                buckets.append(Bucket),
                {"Body": MagicMock(iter_lines=lambda: iter(()),
                                   read=lambda: b"../../store/de/dead/z.tar.gz")})[1]),
        )
        reapi = sync_reapi.REAPIRemoteSync(
            remoteStore="reapi://localhost/cas", writeStore="reapi://localhost/cas",
            architecture=ARCHITECTURE, workdir="/sw",
            legacyStore="reapi://localhost/legacy",
            casPublicUrl="https://example/cas")
        reapi.s3 = client
        reapi.fetch_symlinks({"package": "zlib"})

        self.assertTrue(buckets, "expected the manifest and the listing to be read")
        self.assertNotIn("cas", buckets,
                         "a read addressed the artifact bucket, whose legacy tree "
                         "stops being written once the split is on")
        self.assertEqual(set(buckets), {"legacy"})

    def test_boto3_defaults_to_the_artifact_bucket(self):
        """b3:// has no split at all; legacyReadStore must simply be remoteStore."""
        b3 = sync.Boto3RemoteSync(remoteStore="b3://read", writeStore="b3://write",
                                  architecture=ARCHITECTURE, workdir="/sw")
        self.assertEqual(b3.legacyReadStore, b3.remoteStore)



@patch("os.makedirs", new=MagicMock(return_value=None))
@patch("alibuild_helpers.sync.ProgressPrint", new=MagicMock())
@patch("alibuild_helpers.sync_reapi.REAPIRemoteSync._s3_init", new=MagicMock())
class FetchTarballBucketTestCase(unittest.TestCase):
    """Where the BYTES are read from follows the redirect, not the listing.

    With the legacy tree split out, a store object is either a stub pointing into
    the CAS bucket or the tarball itself sitting in the legacy bucket. Reading an
    un-redirected object from the CAS bucket 404s -- which is exactly what the
    first ubuntu2204 release did, because its tarballs were published by a plain
    s3:// store that writes bytes where reapi:// writes stubs.
    """

    def make_sync(self, client):
        reapi = sync_reapi.REAPIRemoteSync(
            remoteStore="reapi://localhost/cas", writeStore="reapi://localhost/cas",
            architecture=ARCHITECTURE, workdir="/sw",
            legacyStore="reapi://localhost/legacy",
            casPublicUrl="https://example/cas")
        reapi.s3 = client
        return reapi

    def make_client(self, redirect=None):
        """Record every (bucket, key) the fetch touches."""
        self.reads = []
        head_meta = {"ContentLength": 4096}
        if redirect:
            head_meta = dict(head_meta, WebsiteRedirectLocation=redirect)

        def head_object(Bucket, Key):
            self.reads.append(("head", Bucket, Key))
            # The CAS blob itself never carries a redirect.
            return {"ContentLength": 4096} if Key.startswith("cas/") else head_meta

        def download_file(Bucket, Key, Filename, Callback=None):
            self.reads.append(("get", Bucket, Key))

        # The Action Cache is consulted first; miss it so the legacy path runs,
        # which is the path under test.
        from botocore.exceptions import ClientError

        def get_object(Bucket, Key):
            self.reads.append(("get_object", Bucket, Key))
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "get_object")

        key = "TARS/%s/store/de/dead/x.tar.gz" % ARCHITECTURE
        return MagicMock(
            head_object=MagicMock(side_effect=head_object),
            download_file=MagicMock(side_effect=download_file),
            get_object=MagicMock(side_effect=get_object),
            get_paginator=lambda method: MagicMock(
                paginate=lambda **kw: [{"Contents": [{"Key": key}]}]),
        )

    def fetch(self, redirect=None):
        client = self.make_client(redirect)
        reapi = self.make_sync(client)
        reapi.fetch_tarball({"package": "zlib", "version": "v1",
                             "remote_hashes": ["dead"]})
        return self.reads

    def test_plain_tarball_is_read_from_the_legacy_bucket(self):
        """The regression: no redirect, so the bytes are the legacy object."""
        reads = self.fetch(redirect=None)
        # Only the tarball reads: the Action Cache probe addresses the CAS
        # bucket by design, and asserting against it would pin the wrong thing.
        tarball_reads = [r for r in reads if r[0] in ("head", "get")]
        self.assertTrue([r for r in tarball_reads if r[0] == "get"],
                        "expected a download")
        for kind, bucket, key in tarball_reads:
            self.assertEqual(bucket, "legacy",
                             "%s of %s must come from the legacy bucket" % (kind, key))

    def test_resolve_via_links_reads_the_link_from_the_legacy_bucket(self):
        """Same bug, the other place that pairs a legacy key with a bucket.

        _resolve_via_links lists the legacy tree and then reads the winning
        link's body to recover the store hash. Reading that body from the
        artifact bucket only worked while the two were one bucket.
        """
        buckets = []
        body = b"../../%s/store/de/dead/zlib-v1-1.%s.tar.gz" % (
            ARCHITECTURE.encode(), ARCHITECTURE.encode())
        key = "TARS/%s/zlib/zlib-v1-1.%s.tar.gz" % (ARCHITECTURE, ARCHITECTURE)
        client = MagicMock(
            get_paginator=lambda method: MagicMock(
                paginate=lambda **kw: (buckets.append(kw["Bucket"]),
                                       [{"Contents": [{"Key": key}]}])[1]),
            get_object=MagicMock(side_effect=lambda Bucket, Key: (
                buckets.append(Bucket), {"Body": MagicMock(read=lambda: body)})[1]),
        )
        reapi = sync_reapi.REAPIRemoteSync(
            remoteStore="reapi://localhost/cas", writeStore="reapi://localhost/cas",
            architecture=ARCHITECTURE, workdir="/sw",
            legacyStore="reapi://localhost/legacy",
            casPublicUrl="https://example/cas")
        reapi.s3 = client

        self.assertEqual(reapi._resolve_via_links("zlib", "v1"), "dead")
        self.assertEqual(set(buckets), {"legacy"},
                         "listing and link body must address the same bucket")

    def test_stub_is_followed_into_the_cas_bucket(self):
        """And the other half still works: a stub redirects into the CAS."""
        reads = self.fetch(redirect="/cas/sha256/de/dead")
        gets = [r for r in reads if r[0] == "get"]
        self.assertEqual([(b, k) for _, b, k in gets],
                         [("cas", "cas/sha256/de/dead")])
        # The first head -- the legacy store object -- still addresses the
        # legacy bucket; only the redirected fetch leaves it.
        heads = [r for r in reads if r[0] == "head"]
        self.assertEqual(heads[0][1], "legacy")


@patch("alibuild_helpers.sync_reapi.REAPIRemoteSync._s3_init", new=MagicMock())
class IsFullyMigratedTestCase(unittest.TestCase):
    """A package published by a BUILD must not be migrated again.

    migrate has no --legacy-links-store, so it can only look for the per-package
    link in its own artifact store. A release publishes that link into the SHARED
    legacy bucket instead, so a perfectly published package looked unmigrated,
    was retried every round, and failed on the 78-byte redirect stub that
    --read-store's plain GET returns. Seventeen packages of the ubuntu2204
    O2Suite closure did that on every round.
    """

    def make_sync(self, link_exists, ac_hash=None, published=False):
        reapi = sync_reapi.REAPIRemoteSync(
            remoteStore="reapi://localhost/cas", writeStore="reapi://localhost/cas",
            architecture=ARCHITECTURE, workdir="/sw")
        reapi._exists = MagicMock(return_value=link_exists)
        reapi.resolve_action_hash = MagicMock(return_value=ac_hash)
        reapi.is_published = MagicMock(return_value=published)
        return reapi

    def test_link_present_is_enough(self):
        reapi = self.make_sync(link_exists=True)
        self.assertTrue(reapi.is_fully_migrated(ARCHITECTURE, "zlib", "zlib-v1-1.tar.gz", "v1-1"))
        reapi.resolve_action_hash.assert_not_called()   # cheap path, no AC lookup

    def test_published_elsewhere_counts_as_migrated(self):
        """The regression: no link here, but the AC says it is published."""
        reapi = self.make_sync(link_exists=False, ac_hash="abc123", published=True)
        self.assertTrue(reapi.is_fully_migrated(ARCHITECTURE, "c-ares", "c-ares-1.34.6-1.tar.gz", "1.34.6-1"))
        reapi.resolve_action_hash.assert_called_once_with("c-ares", "1.34.6", "1")

    def test_ac_entry_without_its_blob_is_not_migrated(self):
        """is_published requires the blob too; an entry alone must not skip it."""
        reapi = self.make_sync(link_exists=False, ac_hash="abc123", published=False)
        self.assertFalse(reapi.is_fully_migrated(ARCHITECTURE, "zlib", "zlib-v1-1.tar.gz", "v1-1"))

    def test_unknown_action_is_not_migrated(self):
        reapi = self.make_sync(link_exists=False, ac_hash=None)
        self.assertFalse(reapi.is_fully_migrated(ARCHITECTURE, "zlib", "zlib-v1-1.tar.gz", "v1-1"))

    def test_without_verrev_it_falls_back_to_the_link_only(self):
        """Older callers pass no verrev; they must keep the previous behaviour."""
        reapi = self.make_sync(link_exists=False, ac_hash="abc123", published=True)
        self.assertFalse(reapi.is_fully_migrated(ARCHITECTURE, "zlib", "zlib-v1-1.tar.gz"))
        reapi.resolve_action_hash.assert_not_called()

if __name__ == '__main__':
    unittest.main()

