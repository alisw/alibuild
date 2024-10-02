import os
import os.path
import sys
import unittest
from io import BytesIO

from unittest.mock import patch, MagicMock

from alibuild_helpers import sync
from alibuild_helpers.utilities import resolve_links_path, resolve_store_path


ARCHITECTURE = "slc7_x86-64"
PACKAGE = "zlib"
GOOD_HASH = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
BAD_HASH = "baadf00dbaadf00dbaadf00dbaadf00dbaadf00d"
NONEXISTENT_HASH = "TRIGGERS_A_404"
GOOD_SPEC = {    # fully present on the remote store
    "package": PACKAGE, "version": "v1.2.3", "revision": "1",
    "hash": GOOD_HASH,
    "remote_revision_hash": GOOD_HASH,
    "remote_hashes": [GOOD_HASH],
}
BAD_SPEC = {     # partially present on the remote store
    "package": PACKAGE, "version": "v1.2.3", "revision": "2",
    "hash": BAD_HASH,
    "remote_revision_hash": BAD_HASH,
    "remote_hashes": [BAD_HASH],
}
MISSING_SPEC = {    # completely absent from the remote store
    "package": PACKAGE, "version": "v1.2.3", "revision": "3",
    "hash": NONEXISTENT_HASH,
    "remote_revision_hash": NONEXISTENT_HASH,
    "remote_hashes": [NONEXISTENT_HASH],
}


def tarball_name(spec):
    return ("{package}-{version}-{revision}.{arch}.tar.gz"
            .format(arch=ARCHITECTURE, **spec))


TAR_NAMES = tarball_name(GOOD_SPEC), tarball_name(BAD_SPEC), tarball_name(MISSING_SPEC)


class MockRequest:
    def __init__(self, j, simulate_err=False):
        self.j = j
        self.simulate_err = simulate_err
        self.status_code = 200 if j else 404
        self._bytes_left = 123456
        self.headers = {"content-length": str(self._bytes_left)}

    def raise_for_status(self):
        return True

    def json(self):
        return self.j

    def iter_content(self, chunk_size=10):
        if not self.simulate_err:
            while self._bytes_left > 0:
                toread = min(chunk_size, self._bytes_left)
                yield b"x" * toread
                self._bytes_left -= toread


@patch("alibuild_helpers.sync.ProgressPrint", new=MagicMock())
class SyncTestCase(unittest.TestCase):
    def mock_get(self, url, *args, **kw):
        if NONEXISTENT_HASH in url:
            return MockRequest(None)
        if "/store/" in url:
            if GOOD_HASH in url:
                return MockRequest([{"name": tarball_name(GOOD_SPEC)}])
            elif BAD_HASH in url:
                return MockRequest([{"name": tarball_name(BAD_SPEC)}],
                                   simulate_err=True)
        elif url.endswith(".manifest"):
            return MockRequest("")
        elif ("/%s/" % PACKAGE) in url:
            return MockRequest([{"name": tarball_name(GOOD_SPEC)},
                                {"name": tarball_name(BAD_SPEC)}])
        raise NotImplementedError(url)

    @patch("alibuild_helpers.sync.open", new=lambda fn, mode: BytesIO())
    @patch("os.path.isfile", new=MagicMock(return_value=False))
    @patch("os.rename", new=MagicMock(return_value=None))
    @patch("os.makedirs", new=MagicMock(return_value=None))
    @patch("os.listdir", new=MagicMock(return_value=[]))
    @patch("alibuild_helpers.sync.symlink", new=MagicMock(return_value=None))
    @patch("alibuild_helpers.sync.execute", new=MagicMock(return_value=None))
    @patch("alibuild_helpers.sync.debug")
    @patch("alibuild_helpers.sync.error")
    @patch("requests.Session.get")
    def test_http_remote(self, mock_get, mock_error, mock_debug):
        """Test HTTPS remote store."""
        mock_get.side_effect = self.mock_get
        syncer = sync.HttpRemoteSync(remoteStore="https://localhost/test",
                                     architecture=ARCHITECTURE,
                                     workdir="/sw", insecure=False)
        syncer.httpBackoff = 0  # speed up tests

        # Try good spec
        mock_error.reset_mock()

        syncer.fetch_symlinks(GOOD_SPEC)
        syncer.fetch_tarball(GOOD_SPEC)
        mock_error.assert_not_called()
        syncer.upload_symlinks_and_tarball(GOOD_SPEC)

        # Try bad spec
        mock_error.reset_mock()

        syncer.fetch_symlinks(BAD_SPEC)
        syncer.fetch_tarball(BAD_SPEC)

        # We can't use mock_error.assert_called_once_with because two
        # PartialDownloadError instances don't compare equal.
        self.assertEqual(len(mock_error.call_args_list), 1)
        self.assertEqual(mock_error.call_args_list[0][0][0],
                         "GET %s failed: %s")
        self.assertEqual(mock_error.call_args_list[0][0][1],
                         "https://localhost/test/TARS/%s/store/%s/%s/%s" %
                         (ARCHITECTURE, BAD_SPEC["remote_revision_hash"][:2],
                          BAD_SPEC["remote_revision_hash"],
                          tarball_name(BAD_SPEC)))
        self.assertIsInstance(mock_error.call_args_list[0][0][2],
                              sync.PartialDownloadError)

        syncer.upload_symlinks_and_tarball(BAD_SPEC)

        # Try missing spec
        mock_debug.reset_mock()
        syncer.fetch_symlinks(MISSING_SPEC)
        syncer.fetch_tarball(MISSING_SPEC)
        mock_debug.assert_called_with("Nothing fetched for %s (%s)",
                                      MISSING_SPEC["package"], NONEXISTENT_HASH)

    @patch("alibuild_helpers.sync.execute", new=lambda cmd, printer=None: 0)
    @patch("alibuild_helpers.sync.os")
    def test_sync(self, mock_os):
        """Check NoRemoteSync, rsync:// and s3:// remote stores."""
        # file does not exist locally: force download
        mock_os.path.exists.side_effect = lambda path: False
        mock_os.path.islink.side_effect = lambda path: False
        mock_os.path.isfile.side_effect = lambda path: False

        syncers = [
            sync.NoRemoteSync(),
            sync.RsyncRemoteSync(remoteStore="ssh://localhost/test",
                                 writeStore="ssh://localhost/test",
                                 architecture=ARCHITECTURE,
                                 workdir="/sw"),
            sync.S3RemoteSync(remoteStore="s3://localhost",
                              writeStore="s3://localhost",
                              architecture=ARCHITECTURE,
                              workdir="/sw"),
        ]

        for spec in (GOOD_SPEC, BAD_SPEC):
            for syncer in syncers:
                syncer.fetch_symlinks(spec)
                syncer.fetch_tarball(spec)
                syncer.upload_symlinks_and_tarball(spec)

        for syncer in syncers:
            syncer.fetch_symlinks(MISSING_SPEC)
            syncer.fetch_tarball(MISSING_SPEC)


@unittest.skipIf(sys.version_info < (3, 6), "python >= 3.6 is required for boto3")
@patch("os.makedirs", new=MagicMock(return_value=None))
@patch("alibuild_helpers.sync.symlink", new=MagicMock(return_value=None))
@patch("alibuild_helpers.sync.ProgressPrint", new=MagicMock())
@patch("alibuild_helpers.log.error", new=MagicMock())
@patch("alibuild_helpers.sync.Boto3RemoteSync._s3_init", new=MagicMock())
class Boto3TestCase(unittest.TestCase):
    """Check the b3:// remote is working properly."""

    def mock_s3(self):
        """Create a mock object imitating an S3 client.

        Which spec we are listing contents for controls the simulated contents
        of the store under dist*/:

        - MISSING_SPEC: Simulate a case where the store is empty; we can safely
          upload objects to the remote.
        - GOOD_SPEC: Simulate a case where we can fetch tarballs from the store;
          we mustn't upload as that would overwrite existing packages.
        - BAD_SPEC: Simulate a case where we must abort our upload.

        This currently only affects the simulated contents of dist*
        directories.
        """
        from botocore.exceptions import ClientError

        def paginate_listdir(Bucket, Delimiter, Prefix):
            dir = Prefix.rstrip(Delimiter)
            if dir in (resolve_store_path(ARCHITECTURE, NONEXISTENT_HASH),
                       resolve_store_path(ARCHITECTURE, BAD_HASH)):
                return [{}]
            elif dir in (resolve_store_path(ARCHITECTURE, GOOD_HASH),
                         resolve_links_path(ARCHITECTURE, PACKAGE)):
                return [{"Contents": [
                    {"Key": dir + Delimiter + tarball_name(GOOD_SPEC)},
                ]}]
            elif "/dist" not in Prefix:
                raise NotImplementedError("unknown prefix " + Prefix)
            elif dir.endswith("-" + GOOD_SPEC["revision"]):
                # The expected dist symlinks already exist on S3. As our
                # test package has no dependencies, the prefix should only
                # contain a link to the package itself.
                return [{"Contents": [
                    {"Key": dir + Delimiter + "%s.%s.tar.gz" %
                     (os.path.basename(dir), ARCHITECTURE)},
                ]}]
            elif dir.endswith("-" + BAD_SPEC["revision"]):
                # Simulate partially complete upload of symlinks, e.g. by
                # another aliBuild running in parallel.
                return [{"Contents": [
                    {"Key": dir + Delimiter + "somepackage-v1-1.%s.tar.gz" % ARCHITECTURE},
                ]}]
            elif dir.endswith("-" + MISSING_SPEC["revision"]):
                # No pre-existing symlinks under dist*.
                return [{"Contents": []}]
            else:
                raise NotImplementedError("unknown dist prefix " + Prefix)

        def head_object(Bucket, Key):
            if NONEXISTENT_HASH in Key or BAD_HASH in Key or \
               os.path.basename(Key) == tarball_name(MISSING_SPEC):
                raise ClientError({"Error": {"Code": "404"}}, "head_object")
            return {}

        def download_file(Bucket, Key, Filename, Callback=None):
            self.assertNotIn(NONEXISTENT_HASH, Key, "tried to fetch missing tarball")
            self.assertNotIn(BAD_HASH, Key, "tried to follow bad symlink")

        def get_object(Bucket, Key):
            if Key.endswith(".manifest"):
                return {"Body": MagicMock(iter_lines=lambda: [
                    tarball_name(GOOD_SPEC).encode("utf-8") + b"\t...from manifest\n",
                ])}
            return {"Body": MagicMock(read=lambda: b"...fetched individually")}

        def get_paginator(method):
            if method == "list_objects_v2":
                return MagicMock(paginate=paginate_listdir)
            raise NotImplementedError(method)

        return MagicMock(
            get_paginator=get_paginator,
            head_object=head_object,
            download_file=MagicMock(side_effect=download_file),
            get_object=get_object,
            put_object=MagicMock(return_value=None),
            upload_file=MagicMock(return_value=None),
        )

    @patch("glob.glob", new=MagicMock(return_value=[]))
    @patch("os.listdir", new=MagicMock(return_value=[]))
    @patch("os.makedirs", new=MagicMock())
    # Pretend file does not exist locally to force download.
    @patch("os.path.exists", new=MagicMock(return_value=False))
    @patch("os.path.isfile", new=MagicMock(return_value=False))
    @patch("os.path.islink", new=MagicMock(return_value=False))
    @patch("alibuild_helpers.sync.execute", new=MagicMock(return_value=0))
    def test_tarball_download(self):
        """Test boto3 behaviour when downloading tarballs from the remote."""
        b3sync = sync.Boto3RemoteSync(
            remoteStore="b3://localhost", writeStore="b3://localhost",
            architecture=ARCHITECTURE, workdir="/sw")
        b3sync.s3 = self.mock_s3()

        b3sync.s3.download_file.reset_mock()
        b3sync.fetch_symlinks(GOOD_SPEC)
        b3sync.fetch_tarball(GOOD_SPEC)
        b3sync.s3.download_file.assert_called()

        b3sync.s3.download_file.reset_mock()
        b3sync.fetch_symlinks(BAD_SPEC)
        b3sync.fetch_tarball(BAD_SPEC)
        b3sync.s3.download_file.assert_not_called()

        b3sync.s3.download_file.reset_mock()
        b3sync.fetch_symlinks(MISSING_SPEC)
        b3sync.fetch_tarball(MISSING_SPEC)
        b3sync.s3.download_file.assert_not_called()

    @patch("os.listdir", new=lambda path: (
        [tarball_name(GOOD_SPEC)] if path.endswith("-" + GOOD_SPEC["revision"]) else
        [tarball_name(BAD_SPEC)] if path.endswith("-" + BAD_SPEC["revision"]) else
        [] if path.endswith("-" + MISSING_SPEC["revision"]) else
        NotImplemented
    ))
    @patch("os.readlink", new=MagicMock(return_value="dummy path"))
    @patch("os.path.islink", new=MagicMock(return_value=True))
    def test_tarball_upload(self):
        """Test boto3 behaviour when building packages for upload locally."""
        b3sync = sync.Boto3RemoteSync(
            remoteStore="b3://localhost", writeStore="b3://localhost",
            architecture=ARCHITECTURE, workdir="/sw")
        b3sync.s3 = self.mock_s3()

        # Make sure upload of a fresh, new tarball works fine.
        b3sync.s3.put_object.reset_mock()
        b3sync.s3.upload_file.reset_mock()
        b3sync.upload_symlinks_and_tarball(MISSING_SPEC)
        # We simulated local builds, so we should upload the tarballs to
        # the remote.
        b3sync.s3.put_object.assert_called()
        b3sync.s3.upload_file.assert_called()

        b3sync.s3.put_object.reset_mock()
        b3sync.s3.upload_file.reset_mock()
        b3sync.upload_symlinks_and_tarball(GOOD_SPEC)
        # We simulated downloading tarballs from the remote, so we mustn't
        # upload them again and overwrite the remote.
        b3sync.s3.put_object.assert_not_called()
        b3sync.s3.upload_file.assert_not_called()

        # Make sure conflict detection is working for tarball sync.
        b3sync.s3.put_object.reset_mock()
        b3sync.s3.upload_file.reset_mock()
        self.assertRaises(SystemExit, b3sync.upload_symlinks_and_tarball, BAD_SPEC)
        b3sync.s3.put_object.assert_not_called()
        b3sync.s3.upload_file.assert_not_called()


if __name__ == '__main__':
    unittest.main()
