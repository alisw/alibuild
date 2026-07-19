import io
import os
import os.path
import tarfile
import tempfile
import unittest
from argparse import Namespace
from unittest.mock import patch

from alibuild_helpers import sync
from alibuild_helpers import install
from alibuild_helpers.install import collect_runtime_closure, install_entry, doInstall

ARCH = "slc7_x86-64"


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


class FakeSync(sync.REAPIRemoteSync):
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


if __name__ == "__main__":
    unittest.main()
