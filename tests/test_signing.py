import base64
import json
import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from alibuild_helpers import signing

# `cryptography` is an optional extra (`pip install alibuild[signing]`), so these
# tests must skip rather than fail where it is absent -- e.g. a CI job that does
# not install the extra. tox installs it via `extras = signing`, so they normally
# do run.
try:
    import cryptography    # noqa: F401
    HAVE_CRYPTOGRAPHY = True
except ImportError:
    HAVE_CRYPTOGRAPHY = False

requires_crypto = unittest.skipUnless(
    HAVE_CRYPTOGRAPHY, "needs the optional 'cryptography' extra")


# Deterministic Ed25519 seeds (any 32 bytes work).
SEED_A = bytes(range(32))
SEED_B = bytes(range(32, 64))


def ac_entry(**override):
    entry = {
        "action": {"actionHash": "a" * 40, "package": "zlib",
                   "architecture": "slc7_x86-64", "recipeDigest": "sha256:r"},
        "result": {"outputDigest": "sha256:o", "size": 10, "tarball": "zlib.tgz"},
    }
    entry.update(override)
    return entry


def keyring(*seed_signers, revoked=(), not_before=None, not_after=None):
    keys = {}
    for seed, signer in seed_signers:
        keyid, pub = signing.public_key(seed)
        item = {"publicKey": pub, "signer": signer}
        if not_before:
            item["notBefore"] = not_before
        if not_after:
            item["notAfter"] = not_after
        keys[keyid] = item
    return signing.load_keyring({"keys": keys, "revoked": list(revoked)})


@requires_crypto
class SigningTestCase(unittest.TestCase):
    def test_dsse_pae_format(self) -> None:
        self.assertEqual(signing.dsse_pae("t", b"hi"), b"DSSEv1 1 t 2 hi")

    def test_signed_payload_deterministic_and_binds_output(self) -> None:
        self.assertEqual(signing.signed_payload(ac_entry()),
                         signing.signed_payload(ac_entry()))
        # Swapping the artifact the entry points at changes the signed payload.
        self.assertNotEqual(
            signing.signed_payload(ac_entry()),
            signing.signed_payload(ac_entry(result={"outputDigest": "sha256:X"})))

    def test_validate_system_entry_binds_recipe_digest(self) -> None:
        # No result tarball -> bind recipeDigest instead of outputDigest.
        entry = {"action": {"actionHash": "h", "package": "make",
                            "architecture": "slc7_x86-64", "recipeDigest": "sha256:r"}}
        self.assertIn(b"sha256:r", signing.signed_payload(entry))

    def test_sign_then_verify(self) -> None:
        entry = ac_entry()
        entry["signatures"] = [signing.sign(entry, SEED_A, "alice-ci")]
        ok, reason = signing.verify(entry, keyring((SEED_A, "alice-ci")))
        self.assertTrue(ok, reason)

    def test_tampered_output_digest_fails(self) -> None:
        entry = ac_entry()
        entry["signatures"] = [signing.sign(entry, SEED_A, "ci")]
        entry["result"]["outputDigest"] = "sha256:EVIL"   # point at another blob
        ok, reason = signing.verify(entry, keyring((SEED_A, "ci")))
        self.assertFalse(ok)
        self.assertIn("bad signature", reason)

    def test_untrusted_key_fails(self) -> None:
        entry = ac_entry()
        entry["signatures"] = [signing.sign(entry, SEED_A, "ci")]
        ok, reason = signing.verify(entry, keyring((SEED_B, "other")))
        self.assertFalse(ok)
        self.assertIn("untrusted", reason)

    def test_unsigned_fails(self) -> None:
        ok, reason = signing.verify(ac_entry(), keyring((SEED_A, "ci")))
        self.assertFalse(ok)
        self.assertIn("no signatures", reason)

    def test_revoked_key_fails(self) -> None:
        entry = ac_entry()
        sig = signing.sign(entry, SEED_A, "ci")
        entry["signatures"] = [sig]
        ok, reason = signing.verify(entry, keyring((SEED_A, "ci"), revoked=[sig["keyid"]]))
        self.assertFalse(ok)
        self.assertIn("revoked", reason)

    def test_expired_key_fails(self) -> None:
        entry = ac_entry()
        entry["signatures"] = [signing.sign(entry, SEED_A, "ci")]
        past = datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat()
        ok, reason = signing.verify(entry, keyring((SEED_A, "ci"), not_after=past))
        self.assertFalse(ok)
        self.assertIn("expired", reason)

    def test_not_yet_valid_key_fails(self) -> None:
        entry = ac_entry()
        entry["signatures"] = [signing.sign(entry, SEED_A, "ci")]
        future = datetime(2999, 1, 1, tzinfo=timezone.utc).isoformat()
        ok, reason = signing.verify(entry, keyring((SEED_A, "ci"), not_before=future))
        self.assertFalse(ok)
        self.assertIn("not yet valid", reason)

    def test_threshold_requires_distinct_keys(self) -> None:
        entry = ac_entry()
        entry["signatures"] = [signing.sign(entry, SEED_A, "a")]
        ring = keyring((SEED_A, "a"), (SEED_B, "b"))
        self.assertFalse(signing.verify(entry, ring, min_signatures=2)[0])
        entry["signatures"].append(signing.sign(entry, SEED_B, "b"))
        self.assertTrue(signing.verify(entry, ring, min_signatures=2)[0])

    def test_keyid_must_match_public_key(self) -> None:
        _, pub = signing.public_key(SEED_A)
        with self.assertRaises(ValueError):
            signing.load_keyring({"keys": {"deadbeef": {"publicKey": pub}}})


@requires_crypto
class PolicyTestCase(unittest.TestCase):
    def _signed(self):
        entry = ac_entry()
        entry["signatures"] = [signing.sign(entry, SEED_A, "ci")]
        return entry

    def test_off_ignores_signatures(self) -> None:
        # Unsigned entry, empty keyring: "off" allows and flags nothing.
        allowed, level, _reason = signing.evaluate(
            ac_entry(), keyring((SEED_A, "ci")), signing.POLICY_OFF)
        self.assertTrue(allowed)
        self.assertIsNone(level)

    def test_warn_allows_but_flags_unsigned(self) -> None:
        allowed, level, reason = signing.evaluate(
            ac_entry(), keyring((SEED_A, "ci")), signing.POLICY_WARN)
        self.assertTrue(allowed)
        self.assertEqual(level, "warn")
        self.assertIn("no signatures", reason)

    def test_warn_clean_on_valid_signature(self) -> None:
        allowed, level, _reason = signing.evaluate(
            self._signed(), keyring((SEED_A, "ci")), signing.POLICY_WARN)
        self.assertTrue(allowed)
        self.assertIsNone(level)

    def test_require_fails_closed_on_unsigned(self) -> None:
        allowed, level, _reason = signing.evaluate(
            ac_entry(), keyring((SEED_A, "ci")), signing.POLICY_REQUIRE)
        self.assertFalse(allowed)
        self.assertEqual(level, "error")

    def test_require_passes_on_valid_signature(self) -> None:
        allowed, level, _reason = signing.evaluate(
            self._signed(), keyring((SEED_A, "ci")), signing.POLICY_REQUIRE)
        self.assertTrue(allowed)
        self.assertIsNone(level)

    def test_closure_require_fails_on_one_unsigned_dep(self) -> None:
        # A signed package with one unsigned dependency must fail under require.
        ring = keyring((SEED_A, "ci"))
        entries = [("zlib", self._signed()), ("boost", ac_entry())]
        allowed, problems = signing.evaluate_closure(entries, ring, signing.POLICY_REQUIRE)
        self.assertFalse(allowed)
        self.assertEqual([p[0] for p in problems], ["boost"])
        self.assertEqual(problems[0][1], "error")

    def test_closure_warn_collects_all_problems_without_blocking(self) -> None:
        ring = keyring((SEED_A, "ci"))
        entries = [("zlib", self._signed()), ("boost", ac_entry()),
                   ("root", ac_entry())]
        allowed, problems = signing.evaluate_closure(entries, ring, signing.POLICY_WARN)
        self.assertTrue(allowed)
        self.assertEqual({p[0] for p in problems}, {"boost", "root"})
        self.assertTrue(all(p[1] == "warn" for p in problems))

    def test_closure_all_signed_passes_clean(self) -> None:
        ring = keyring((SEED_A, "ci"))
        entries = [("zlib", self._signed()), ("boost", self._signed())]
        allowed, problems = signing.evaluate_closure(entries, ring, signing.POLICY_REQUIRE)
        self.assertTrue(allowed)
        self.assertEqual(problems, [])


@requires_crypto
class MergeKeyringTestCase(unittest.TestCase):
    """Merging must only ever *narrow* trust: alidist (or any later keyring) may
    add keys, but must not be able to un-revoke one or widen a validity window
    the shipped keyring narrowed. That is what makes revoking by shipping a new
    alibuild release actually stick."""

    def test_union_of_keys(self) -> None:
        merged = signing.merge_keyrings([keyring((SEED_A, "a")), keyring((SEED_B, "b"))])
        self.assertEqual(set(merged.keys),
                         {signing.public_key(SEED_A)[0], signing.public_key(SEED_B)[0]})

    def test_revocation_cannot_be_undone_by_a_later_keyring(self) -> None:
        entry = ac_entry()
        sig = signing.sign(entry, SEED_A, "ci")
        entry["signatures"] = [sig]
        revoking = keyring((SEED_A, "ci"), revoked=[sig["keyid"]])
        permissive = keyring((SEED_A, "ci"))
        for order in ((revoking, permissive), (permissive, revoking)):
            ok, reason = signing.verify(entry, signing.merge_keyrings(order))
            self.assertFalse(ok)
            self.assertIn("revoked", reason)

    def test_validity_windows_intersect(self) -> None:
        entry = ac_entry()
        entry["signatures"] = [signing.sign(entry, SEED_A, "ci")]
        past = datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat()
        expired = keyring((SEED_A, "ci"), not_after=past)
        open_ended = keyring((SEED_A, "ci"))
        for order in ((expired, open_ended), (open_ended, expired)):
            ok, reason = signing.verify(entry, signing.merge_keyrings(order))
            self.assertFalse(ok, "a later keyring must not extend an expired key")
            self.assertIn("expired", reason)

    def test_added_key_is_trusted(self) -> None:
        entry = ac_entry()
        entry["signatures"] = [signing.sign(entry, SEED_B, "later")]
        merged = signing.merge_keyrings([keyring((SEED_A, "shipped")),
                                         keyring((SEED_B, "later"))])
        self.assertTrue(signing.verify(entry, merged)[0])


class _DumbSignerProxy(BaseHTTPRequestHandler):
    """A stand-in for the security-proxy sign route: Ed25519-signs the exact bytes
    posted, gated by a bearer token, and returns {"keyid", "sig"}. Holds SEED_A --
    the private key never leaves the "proxy" (the real one lives out of process)."""

    seed = SEED_A
    expected_token = "gate-token"

    def log_message(self, *_args):
        pass  # keep the test output quiet

    def _respond(self, code, body=b""):
        # Always send an explicit Content-Length so the client reads a bounded
        # body rather than until connection close (which races under teardown).
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_POST(self):
        body_in = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.headers.get("Authorization") != "Bearer %s" % self.expected_token:
            self._respond(401)
            return
        from cryptography.hazmat.primitives.asymmetric import ed25519
        sk = ed25519.Ed25519PrivateKey.from_private_bytes(self.seed)
        keyid, _pub = signing.public_key(self.seed)
        reply = json.dumps({"keyid": keyid,
                            "sig": base64.b64encode(sk.sign(body_in)).decode("ascii")})
        self._respond(200, reply.encode("utf-8"))


@requires_crypto
class SignViaProxyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _DumbSignerProxy)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = "http://127.0.0.1:%d/sign/alibuild-ac" % self.server.server_port

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_proxy_signature_verifies(self) -> None:
        entry = ac_entry()
        entry["signatures"] = [
            signing.sign_via_proxy(entry, self.endpoint, "gate-token", "alice-ci")]
        ok, reason = signing.verify(entry, keyring((SEED_A, "alice-ci")))
        self.assertTrue(ok, reason)

    def test_proxy_matches_local_sign_byte_for_byte(self) -> None:
        # The proxy path and the local sign() path must produce the identical
        # signature bytes -- Ed25519 is deterministic and both sign the same PAE.
        entry = ac_entry()
        via_proxy = signing.sign_via_proxy(entry, self.endpoint, "gate-token", "ci")
        local = signing.sign(entry, SEED_A, "ci")
        self.assertEqual(via_proxy, local)

    def test_bad_gate_token_rejected(self) -> None:
        import requests
        with self.assertRaises(requests.HTTPError):
            signing.sign_via_proxy(ac_entry(), self.endpoint, "wrong-token", "ci")


if __name__ == "__main__":
    unittest.main()
