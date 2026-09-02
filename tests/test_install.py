import hashlib
import io
import json
import os
import os.path
import tarfile
import tempfile
import unittest
from argparse import Namespace
from unittest.mock import patch

from alibuild_helpers import signing
from alibuild_helpers import sync
from alibuild_helpers import sync_reapi
from alibuild_helpers import install
from alibuild_helpers.install import collect_runtime_closure, install_entry, doInstall

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


ARCH = "slc7_x86-64"
SEED_A = bytes(range(32))
SEED_B = bytes(range(32, 64))


def make_tarball(pkg, version, revision):
    """Build an in-memory tarball laid out like a real aliBuild package:
    <arch>/<pkg>/<ver>-<rev>/... with an init.sh, a file needing relocation
    (plus its .unrelocated pristine copy) and a relocate-me.sh that mimics the
    real one (sed from .unrelocated, drop a marker we can assert on)."""
    pkgpath = "%s/%s/%s-%s" % (ARCH, pkg, version, revision)
    relocate = (
        "#!/bin/bash -e\n"
        ': "${WORK_DIR:?Please define WORK_DIR}"\n'
        'PP=%s\n'
        'sed -e "s|@PLACEHOLDER@|$WORK_DIR/$PP|g" "$PP/lib/foo.txt.unrelocated" > "$PP/lib/foo.txt"\n'
        'touch "$WORK_DIR/$PP/relocated.marker"\n'
    ) % pkgpath
    files = {
        pkgpath + "/etc/profile.d/init.sh": "# init for %s\n" % pkg,
        pkgpath + "/lib/foo.txt.unrelocated": "prefix is @PLACEHOLDER@\n",
        pkgpath + "/lib/foo.txt": "prefix is @PLACEHOLDER@\n",
        pkgpath + "/relocate-me.sh": relocate,
    }
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in sorted(files.items()):
            data = content.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class FakeSync(sync_reapi.REAPIRemoteSync):
    """A REAPIRemoteSync whose S3 reads are served from in-memory fixtures."""

    def __init__(self, entries, label_to_hash, blobs):
        self.architecture = ARCH
        self._entries = entries            # action hash -> AC entry
        self._label_to_hash = label_to_hash  # (pkg, ver, rev) -> action hash
        self._blobs = blobs                # content hash -> tarball bytes

    def read_ac_entry(self, action_hash):
        return self._entries.get(action_hash)

    def resolve_action_hash(self, package, version, revision=None):
        return self._label_to_hash.get((package, version, revision))

    def download_artifact(self, content_hash, dest, algo="sha256"):
        with open(dest, "wb") as destf:
            destf.write(self._blobs[content_hash])


def make_entry(pkg, version, revision, content_hash, runtime=()):
    return {
        "schemaVersion": 1,
        "action": {
            "package": pkg, "version": version, "revision": revision,
            "architecture": ARCH, "actionHash": "hash-" + pkg,
            "runtimeDeps": [{"package": p, "actionHash": h} for p, h in runtime],
        },
        "result": {
            "tarball": "%s-%s-%s.%s.tar.gz" % (pkg, version, revision, ARCH),
            "outputDigest": "sha256:" + content_hash, "size": 4096,
        },
    }


class InstallTestCase(unittest.TestCase):
    def setUp(self):
        # zlib (top) with one runtime dependency, GCC.
        self.entries = {
            "hash-zlib": make_entry("zlib", "v1", "1", "c" * 64,
                                    runtime=[("GCC", "hash-GCC")]),
            "hash-GCC": make_entry("GCC", "v9", "2", "d" * 64),
        }
        self.blobs = {
            "c" * 64: make_tarball("zlib", "v1", "1"),
            "d" * 64: make_tarball("GCC", "v9", "2"),
        }
        self.sync = FakeSync(self.entries,
                             {("zlib", "v1", None): "hash-zlib",
                              ("zlib", "v1", "1"): "hash-zlib"},
                             self.blobs)

    def test_collect_runtime_closure(self):
        closure = collect_runtime_closure(self.sync, "hash-zlib")
        self.assertEqual([e["action"]["package"] for e in closure], ["zlib", "GCC"])

    def test_collect_runtime_closure_missing_dep(self):
        del self.entries["hash-GCC"]
        self.assertRaises(SystemExit, collect_runtime_closure, self.sync, "hash-zlib")

    def test_install_entry_extracts_and_relocates(self):
        with tempfile.TemporaryDirectory() as prefix:
            install_entry(self.sync, self.entries["hash-zlib"], prefix, ARCH)
            base = os.path.join(prefix, ARCH, "zlib", "v1-1")
            # Extracted.
            self.assertTrue(os.path.exists(os.path.join(base, "etc/profile.d/init.sh")))
            # relocate-me.sh ran (marker dropped, with WORK_DIR == prefix).
            self.assertTrue(os.path.exists(os.path.join(base, "relocated.marker")))
            # The placeholder was rewritten to the final prefix path.
            with open(os.path.join(base, "lib/foo.txt")) as foo:
                self.assertIn(os.path.join(prefix, ARCH, "zlib", "v1-1"), foo.read())
            # The .unrelocated pristine copy was cleaned up.
            self.assertFalse(os.path.exists(os.path.join(base, "lib/foo.txt.unrelocated")))
            # latest symlink points at the installed revision.
            self.assertEqual(os.readlink(os.path.join(prefix, ARCH, "zlib", "latest")), "v1-1")

    def test_install_entry_skips_if_present(self):
        with tempfile.TemporaryDirectory() as prefix:
            os.makedirs(os.path.join(prefix, ARCH, "zlib", "v1-1"))
            with patch.object(self.sync, "download_blob") as dl:
                install_entry(self.sync, self.entries["hash-zlib"], prefix, ARCH)
                dl.assert_not_called()

    def test_doInstall_end_to_end(self):
        with tempfile.TemporaryDirectory() as prefix:
            args = Namespace(package="zlib", version="v1", revision=None,
                             architecture=ARCH, remoteStore="reapi://localhost/bucket",
                             insecure=False, workDir=prefix, prefix=prefix)
            with patch("alibuild_helpers.install.remote_from_url", return_value=self.sync):
                self.assertTrue(doInstall(args, None))
            # Both the package and its runtime dependency are installed.
            self.assertTrue(os.path.exists(
                os.path.join(prefix, ARCH, "zlib", "v1-1", "etc/profile.d/init.sh")))
            self.assertTrue(os.path.exists(
                os.path.join(prefix, ARCH, "GCC", "v9-2", "etc/profile.d/init.sh")))

    def test_doInstall_requires_reapi_store(self):
        args = Namespace(package="zlib", version="v1", revision=None,
                         architecture=ARCH, remoteStore="https://s3.cern.ch/foo",
                         insecure=False, workDir="/sw", prefix=None)
        # A non-reapi store yields a non-REAPIRemoteSync backend, which must abort.
        self.assertRaises(SystemExit, doInstall, args, None)


def write_keyring(path, *seed_signers):
    """Write a JSON keyring trusting the given (seed, signer) public keys."""
    keys = {}
    for seed, signer in seed_signers:
        keyid, pub = signing.public_key(seed)
        keys[keyid] = {"publicKey": pub, "signer": signer}
    with open(path, "w") as handle:
        json.dump({"keys": keys}, handle)


@requires_crypto
class SignatureWiringTestCase(unittest.TestCase):
    """End-to-end: --require-signature / --trusted-keys gating doInstall."""

    def setUp(self):
        # Real tarball bytes so their sha256 is the entry's output digest -- the
        # signature binds that digest, and install re-hashes to confirm the bytes.
        self.zlib_bytes = make_tarball("zlib", "v1", "1")
        self.gcc_bytes = make_tarball("GCC", "v9", "2")
        self.zlib_h = hashlib.sha256(self.zlib_bytes).hexdigest()
        self.gcc_h = hashlib.sha256(self.gcc_bytes).hexdigest()
        self.blobs = {self.zlib_h: self.zlib_bytes, self.gcc_h: self.gcc_bytes}

    def _entry(self, pkg, ver, rev, content_hash, runtime=(), seed=SEED_A):
        entry = make_entry(pkg, ver, rev, content_hash, runtime)
        if seed is not None:
            entry["signatures"] = [signing.sign(entry, seed, "ci")]
        return entry

    def _sync(self, gcc_seed=SEED_A, blobs=None):
        entries = {
            "hash-zlib": self._entry("zlib", "v1", "1", self.zlib_h,
                                     runtime=[("GCC", "hash-GCC")]),
            "hash-GCC": self._entry("GCC", "v9", "2", self.gcc_h, seed=gcc_seed),
        }
        return FakeSync(entries,
                        {("zlib", "v1", None): "hash-zlib",
                         ("zlib", "v1", "1"): "hash-zlib"},
                        blobs if blobs is not None else self.blobs)

    def _run(self, sync_obj, prefix, policy, trusted_seed=SEED_A):
        keyring_path = os.path.join(prefix, "keyring.json")
        write_keyring(keyring_path, (trusted_seed, "ci"))
        args = Namespace(package="zlib", version="v1", revision=None,
                         architecture=ARCH, remoteStore="reapi://localhost/bucket",
                         insecure=False, workDir=prefix, prefix=prefix,
                         requireSignature=policy, trustedKeys=keyring_path)
        with patch("alibuild_helpers.install.remote_from_url", return_value=sync_obj):
            return doInstall(args, None)

    def test_require_installs_signed_closure(self):
        with tempfile.TemporaryDirectory() as prefix:
            self.assertTrue(self._run(self._sync(), prefix, "require"))
            self.assertTrue(os.path.exists(
                os.path.join(prefix, ARCH, "GCC", "v9-2", "etc/profile.d/init.sh")))

    def test_require_rejects_unsigned_dependency(self):
        with tempfile.TemporaryDirectory() as prefix:
            self.assertRaises(SystemExit, self._run,
                              self._sync(gcc_seed=None), prefix, "require")

    def test_require_rejects_untrusted_key(self):
        with tempfile.TemporaryDirectory() as prefix:
            # Signed with SEED_A, but the keyring only trusts SEED_B.
            self.assertRaises(SystemExit, self._run,
                              self._sync(), prefix, "require", trusted_seed=SEED_B)

    def test_warn_installs_unsigned(self):
        with tempfile.TemporaryDirectory() as prefix:
            sync_obj = self._sync(gcc_seed=None)
            sync_obj._entries["hash-zlib"].pop("signatures", None)
            self.assertTrue(self._run(sync_obj, prefix, "warn"))
            self.assertTrue(os.path.exists(
                os.path.join(prefix, ARCH, "zlib", "v1-1", "etc/profile.d/init.sh")))

    def test_require_rejects_blob_not_matching_signed_digest(self):
        with tempfile.TemporaryDirectory() as prefix:
            # Signatures are valid, but the CAS serves the wrong bytes for zlib:
            # the blob-digest binding must catch it.
            bad = dict(self.blobs, **{self.zlib_h: self.gcc_bytes})
            self.assertRaises(SystemExit, self._run,
                              self._sync(blobs=bad), prefix, "require")

    def test_off_skips_verification_entirely(self):
        with tempfile.TemporaryDirectory() as prefix:
            # Unsigned, no keyring needed: policy off installs as before.
            sync_obj = self._sync(gcc_seed=None)
            sync_obj._entries["hash-zlib"].pop("signatures", None)
            args = Namespace(package="zlib", version="v1", revision=None,
                             architecture=ARCH, remoteStore="reapi://localhost/bucket",
                             insecure=False, workDir=prefix, prefix=prefix,
                             requireSignature="off", trustedKeys="")
            with patch("alibuild_helpers.install.remote_from_url", return_value=sync_obj):
                self.assertTrue(doInstall(args, None))


@requires_crypto
class CheckerFactoryTestCase(unittest.TestCase):
    """signature_checker default resolution: policy default + keyring lookup."""

    def _args(self, **over):
        base = dict(requireSignature="warn", trustedKeys="")
        base.update(over)
        return Namespace(**base)

    def test_bundled_keyring_is_used_without_alidist(self):
        # The recipe-free `install` has no alidist; the keyring shipped inside the
        # package is what makes it verify anything at all.
        checker = sync_reapi.signature_checker(self._args())
        self.assertIsInstance(checker, sync_reapi.SignatureChecker)
        self.assertEqual(sync_reapi.keyring_sources(self._args()),
                         [signing.bundled_keyring_path()])

    def test_bundled_keyring_ships_and_loads(self):
        path = signing.bundled_keyring_path()
        self.assertTrue(os.path.exists(path), "keyring.json must ship with the package")
        self.assertTrue(signing.load_keyring(path).keys, "shipped keyring has no keys")

    def test_off_is_none(self):
        self.assertIsNone(sync_reapi.signature_checker(
            self._args(requireSignature="off")))

    def test_require_without_any_keyring_aborts(self):
        with patch("alibuild_helpers.signing.bundled_keyring_path",
                   return_value="/nonexistent/keyring.json"):
            self.assertRaises(SystemExit, sync_reapi.signature_checker,
                              self._args(requireSignature="require"))

    def test_alidist_keyring_merges_on_top_of_the_bundled_one(self):
        with tempfile.TemporaryDirectory() as alidist:
            keyring_path = os.path.join(alidist, "keyring.json")
            write_keyring(keyring_path, (SEED_A, "ci"))
            # configDir (build) and alidist (reconstruct) both resolve to it, and
            # neither replaces the bundled keyring -- both are consulted.
            for kwargs in ({"configDir": alidist}, {"alidist": alidist}):
                self.assertEqual(sync_reapi.keyring_sources(self._args(**kwargs)),
                                 [signing.bundled_keyring_path(), keyring_path])
            checker = sync_reapi.signature_checker(self._args(configDir=alidist))
            self.assertIsInstance(checker, sync_reapi.SignatureChecker)
            self.assertEqual(checker.policy, "warn")
            # The alidist key is trusted, and so is everything already shipped.
            bundled = signing.load_keyring(signing.bundled_keyring_path())
            self.assertIn(signing.public_key(SEED_A)[0], checker.keyring.keys)
            for keyid in bundled.keys:
                self.assertIn(keyid, checker.keyring.keys)

    def test_missing_cryptography_degrades_under_warn(self):
        # cryptography is optional: warn skips when it can't load the keyring,
        # require fails closed.
        with tempfile.TemporaryDirectory() as d:
            keyring_path = os.path.join(d, "keyring.json")
            write_keyring(keyring_path, (SEED_A, "ci"))
            with patch("alibuild_helpers.signing.load_keyring",
                       side_effect=RuntimeError("no cryptography")):
                self.assertIsNone(sync_reapi.signature_checker(
                    self._args(trustedKeys=keyring_path)))
                self.assertRaises(SystemExit, sync_reapi.signature_checker,
                                  self._args(requireSignature="require",
                                             trustedKeys=keyring_path))

    def test_explicit_trusted_keys_replaces_the_defaults(self):
        # An explicit --trusted-keys is an escape hatch: it must not silently
        # keep trusting the shipped keys on top of what the user asked for.
        with tempfile.TemporaryDirectory() as d:
            explicit = os.path.join(d, "mykeys.json")
            write_keyring(explicit, (SEED_A, "ci"))
            self.assertEqual(
                sync_reapi.keyring_sources(
                    self._args(trustedKeys=explicit, configDir="/some/alidist")),
                [explicit])
            checker = sync_reapi.signature_checker(self._args(trustedKeys=explicit))
            self.assertEqual(set(checker.keyring.keys), {signing.public_key(SEED_A)[0]})


if __name__ == "__main__":
    unittest.main()
