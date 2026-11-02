"""Detached signing and verification of reapi Action Cache entries.

MVP scheme (see REMOTE_STORE_CAS_AC.md, "Signing and trust"): Ed25519 keys, a
DSSE (Dead Simple Signing Envelope) pre-authentication encoding over a canonical
payload derived from the AC entry, and a keyring of trusted public keys.

The private key is never held here. In production signing goes through the
security-proxy (`sign_via_proxy`, phase S1): the proxy holds the Ed25519 key and
alibuild only sends it the DSSE bytes to sign. This module holds the shared
DSSE/payload construction so signer and verifier agree byte-for-byte, plus
keyring loading and verification. Everything except `sign_via_proxy` is a pure
function with no network. `cryptography` is an optional dependency, imported
lazily, so importing alibuild never requires it -- only sign()/verify()/
load_keyring()/public_key() do (and `sign_via_proxy` needs neither, since the
proxy does the signing).
"""

import base64
import hashlib
import json
import os.path
from datetime import datetime, timezone

# Payload type for the DSSE PAE. Bump the version suffix if signed_payload changes,
# so an old signature can never be mistaken for one over the new binding.
PAYLOAD_TYPE = "application/vnd.alibuild.ac-signature.v1+json"


def _ed25519():
    """Import cryptography's Ed25519 lazily, with a clear error if it is absent."""
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        return ed25519, Encoding, PublicFormat
    except ImportError as exc:
        raise RuntimeError("signing requires the 'cryptography' package "
                           "(pip install cryptography)") from exc


def dsse_pae(payload_type, payload):
    """DSSE v1 Pre-Authentication Encoding -- the exact bytes that get signed.

        PAE = "DSSEv1" SP LEN(type) SP type SP LEN(payload) SP payload

    (LEN is ASCII decimal; everything concatenated as bytes.) Signing the PAE
    rather than raw JSON is what frees us from JSON-canonicalisation worries.
    """
    typ = payload_type.encode("utf-8")
    body = payload if isinstance(payload, bytes) else payload.encode("utf-8")
    return b" ".join((b"DSSEv1",
                      str(len(typ)).encode("ascii"), typ,
                      str(len(body)).encode("ascii"), body))


def signed_payload(ac_entry):
    """Canonical bytes bound by a signature for an AC entry.

    Binds identity + inputs + output so a signature cannot be replayed onto a
    different action: actionHash, package, architecture, and the digest -- the
    tarball's outputDigest for build entries, or recipeDigest for tarball-less
    validate-system entries. Deterministic (sorted keys, no whitespace) so signer
    and verifier produce identical bytes.
    """
    action = ac_entry.get("action") or {}
    result = ac_entry.get("result") or {}
    digest = result.get("outputDigest") or action.get("recipeDigest") or ""
    body = {
        "actionHash": action.get("actionHash", ""),
        "package": action.get("package", ""),
        "architecture": action.get("architecture", ""),
        "digest": digest,
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def keyid_for(public_key_bytes):
    """Self-certifying key id: sha256 of the raw 32-byte Ed25519 public key."""
    return hashlib.sha256(public_key_bytes).hexdigest()


def public_key(private_key_seed):
    """Return (keyid, base64 raw public key) for an Ed25519 seed -- used to build
    keyrings and for the proxy to publish its public key."""
    ed25519, encoding, public_format = _ed25519()
    sk = ed25519.Ed25519PrivateKey.from_private_bytes(private_key_seed)
    pub = sk.public_key().public_bytes(encoding.Raw, public_format.Raw)
    return keyid_for(pub), base64.b64encode(pub).decode("ascii")


def sign(ac_entry, private_key_seed, signer):
    """Return a signatures[] element for the AC entry.

    private_key_seed is the raw 32-byte Ed25519 seed. Used by tests and, with the
    identical DSSE/payload construction, by the security-proxy signing route (S1).
    """
    ed25519, encoding, public_format = _ed25519()
    sk = ed25519.Ed25519PrivateKey.from_private_bytes(private_key_seed)
    pub = sk.public_key().public_bytes(encoding.Raw, public_format.Raw)
    sig = sk.sign(dsse_pae(PAYLOAD_TYPE, signed_payload(ac_entry)))
    return {"keyid": keyid_for(pub), "signer": signer,
            "sig": base64.b64encode(sig).decode("ascii")}


def sign_via_proxy(ac_entry, endpoint, token, signer, timeout=30):
    """Sign an AC entry through the security-proxy and return a signatures[] element.

    The private key lives in the proxy; alibuild never holds it (and this path
    needs no `cryptography`). The client builds the full DSSE PAE bytes here --
    ``dsse_pae(PAYLOAD_TYPE, signed_payload(ac_entry))`` -- and the proxy is a
    dumb signer: it Ed25519-signs exactly those bytes and returns
    ``{"keyid", "sig"}``. Because the PAE is constructed here, the bytes the proxy
    signs are identical to what ``sign()`` produces locally, so a proxy signature
    verifies against a keyring built from the same key.

    endpoint is the proxy's sign URL and token its gate token, both resolved by
    the caller at use-time (the port and token rotate). Returns
    ``{"keyid", "signer", "sig"}``.
    """
    import requests
    message = dsse_pae(PAYLOAD_TYPE, signed_payload(ac_entry))
    response = requests.post(
        endpoint, data=message, timeout=timeout,
        headers={"Authorization": "Bearer %s" % token,
                 "Content-Type": "application/octet-stream"})
    response.raise_for_status()
    reply = response.json()
    return {"keyid": reply["keyid"], "signer": signer, "sig": reply["sig"]}


def _parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


class Keyring:
    """Trusted Ed25519 public keys (by self-certifying keyid) + a revocation set."""

    def __init__(self, keys, revoked):
        self.keys = keys           # keyid -> {"pub", "signer", "notBefore", "notAfter"}
        self.revoked = set(revoked)


def bundled_keyring_path():
    """Path to the keyring shipped inside the alibuild package.

    This is the trust *anchor*: it arrives with the code the user already runs,
    i.e. over a different channel than the store being verified. A keyring served
    from the store itself would be forgeable by anyone who can write to the store
    -- exactly the attacker signatures exist to stop -- so the store can at best
    *distribute* a keyring, never anchor one.
    """
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "keyring.json")


def _later(one, two):
    return one if two is None else two if one is None else max(one, two)


def _earlier(one, two):
    return one if two is None else two if one is None else min(one, two)


def merge_keyrings(keyrings):
    """Merge several keyrings into one, never widening trust.

    Key ids are self-certifying (sha256 of the public key), so the same id can
    never denote two different keys and the union of keys is conflict-free. Where
    a key appears in more than one source with different validity windows the
    *intersection* wins, and revocation lists are unioned. So a later keyring can
    add keys, but cannot un-revoke a key or extend a window another source
    narrowed -- which is what lets a revocation shipped in alibuild stand even if
    a stale alidist keyring still lists the key as good.
    """
    keys, revoked = {}, set()
    for keyring in keyrings:
        revoked |= set(keyring.revoked)
        for keyid, entry in keyring.keys.items():
            current = keys.get(keyid)
            if current is None:
                keys[keyid] = dict(entry)
            else:
                current["notBefore"] = _later(current["notBefore"], entry["notBefore"])
                current["notAfter"] = _earlier(current["notAfter"], entry["notAfter"])
    return Keyring(keys, revoked)


def load_keyrings(sources):
    """Load and merge several keyrings (paths or dicts). See merge_keyrings."""
    return merge_keyrings([load_keyring(source) for source in sources])


def load_keyring(source):
    """Load a keyring from a JSON file path or an already-parsed dict.

    Format::

        { "keys": { "<keyid>": { "publicKey": "<base64 raw ed25519>",
                                 "signer": "alice-ci",
                                 "notBefore": "2026-01-01T00:00:00Z",   # optional
                                 "notAfter":  "2027-01-01T00:00:00Z" } },  # optional
          "revoked": [ "<keyid>", ... ] }                                  # optional

    Each keyid must equal sha256(publicKey), so an id cannot be spoofed onto a
    different key.
    """
    ed25519, _, _ = _ed25519()
    if isinstance(source, dict):
        data = source
    else:
        with open(source) as handle:
            data = json.load(handle)
    keys = {}
    for keyid, entry in (data.get("keys") or {}).items():
        pub_raw = base64.b64decode(entry["publicKey"])
        if keyid != keyid_for(pub_raw):
            raise ValueError("keyring keyid %s does not match its public key" % keyid)
        keys[keyid] = {
            "pub": ed25519.Ed25519PublicKey.from_public_bytes(pub_raw),
            "signer": entry.get("signer", ""),
            "notBefore": _parse_time(entry.get("notBefore")),
            "notAfter": _parse_time(entry.get("notAfter")),
        }
    return Keyring(keys, data.get("revoked") or [])


# Signature-enforcement policy for the consume side (install / reconstruct /
# build-with-fetch). "off" ignores signatures entirely; "warn" verifies but only
# logs on failure (the rollout default while producers start signing); "require"
# fails closed on any entry that is not covered by a trusted, in-window,
# non-revoked signature.
POLICY_OFF = "off"
POLICY_WARN = "warn"
POLICY_REQUIRE = "require"
POLICIES = (POLICY_OFF, POLICY_WARN, POLICY_REQUIRE)


def evaluate(ac_entry, keyring, policy, min_signatures=1, now=None):
    """Apply a signature policy to a single AC entry.

    Returns ``(allowed, level, reason)``:

    * ``off``     -> ``(True, None, "")`` -- signatures ignored.
    * ``warn``    -> allowed either way; ``level`` is ``"warn"`` with a reason
                     when verification fails, else ``None``.
    * ``require`` -> allowed only when verification passes; otherwise
                     ``(False, "error", reason)``.

    Keeping enforcement here (rather than at each call site) means install,
    reconstruct and fetch share one policy interpretation.
    """
    if policy == POLICY_OFF:
        return True, None, ""
    ok, reason = verify(ac_entry, keyring, min_signatures=min_signatures, now=now)
    if ok:
        return True, None, reason
    if policy == POLICY_WARN:
        return True, "warn", reason
    return False, "error", reason


def evaluate_closure(entries, keyring, policy, min_signatures=1, now=None):
    """Apply a signature policy across a build's dependency closure.

    ``entries`` is an iterable of ``(package, ac_entry)`` pairs -- the AC entry
    for the package being consumed plus one for every dependency, since a
    tarball is only trustworthy if everything it was built from is too. Returns
    ``(allowed, problems)`` where ``problems`` is a list of
    ``(package, level, reason)`` for every entry that did not verify cleanly
    (both ``warn`` and ``error`` levels). ``allowed`` is False as soon as any
    entry fails under ``require``.
    """
    allowed, problems = True, []
    for package, ac_entry in entries:
        ok, level, reason = evaluate(ac_entry, keyring, policy,
                                     min_signatures=min_signatures, now=now)
        if level:
            problems.append((package, level, reason))
        if not ok:
            allowed = False
    return allowed, problems


def verify(ac_entry, keyring, min_signatures=1, now=None):
    """Verify an AC entry's signatures against a keyring.

    Returns ``(ok, reason)``. ok is True when at least ``min_signatures``
    *distinct* trusted keys -- each within its validity window and not revoked --
    carry a valid signature over the entry's signed payload.
    """
    now = now or datetime.now(timezone.utc)
    signatures = ac_entry.get("signatures") or []
    if not signatures:
        return False, "no signatures"
    message = dsse_pae(PAYLOAD_TYPE, signed_payload(ac_entry))
    accepted, reasons = set(), []
    for sig in signatures:
        keyid = sig.get("keyid", "")
        short = (keyid[:12] or "?")
        if keyid in keyring.revoked:
            reasons.append("%s revoked" % short)
        elif keyid not in keyring.keys:
            reasons.append("%s untrusted" % short)
        else:
            key = keyring.keys[keyid]
            if key["notBefore"] and now < key["notBefore"]:
                reasons.append("%s not yet valid" % short)
            elif key["notAfter"] and now > key["notAfter"]:
                reasons.append("%s expired" % short)
            else:
                try:
                    key["pub"].verify(base64.b64decode(sig.get("sig", "")), message)
                    accepted.add(keyid)
                except Exception:   # bad signature or malformed base64
                    reasons.append("%s bad signature" % short)
    if len(accepted) >= min_signatures:
        return True, "%d trusted signature(s)" % len(accepted)
    return False, "insufficient trusted signatures (%d/%d)%s" % (
        len(accepted), min_signatures, (": " + "; ".join(reasons)) if reasons else "")
