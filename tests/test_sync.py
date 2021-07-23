import sys
import unittest
from io import BytesIO

try:
    from unittest.mock import patch, MagicMock   # In Python 3, mock is built-in
except ImportError:
    from mock import patch, MagicMock   # Python 2

from alibuild_helpers import sync


TEST_HASHES = GOOD_HASH, BAD_HASH = ("deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
                                     "baadf00dbaadf00dbaadf00dbaadf00dbaadf00d")
DUMMY_SPEC = {"package": "zlib",
              "version": "v1.2.3",
              "revision": "1",
              "remote_store_path": "/sw/path",
              "remote_links_path": "/sw/links",
              "remote_tar_hash_dir": "/sw/TARS",
              "remote_tar_link_dir": "/sw/TARS"}


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


class SyncTestCase(unittest.TestCase):
    def setUp(self):
        self.spec = DUMMY_SPEC.copy()

    def mock_get(self, url, *args, **kw):
        if "triggers_a_404" in url:
            return MockRequest(None)
        if self.spec["remote_store_path"] in url:
            if self.spec["remote_revision_hash"] == GOOD_HASH:
                return MockRequest([{"name": "zlib-v1.2.3-1.slc7_x86-64.tar.gz"}])
            elif self.spec["remote_revision_hash"] == BAD_HASH:
                return MockRequest([{"name": "zlib-v1.2.3-2.slc7_x86-64.tar.gz"}],
                                   simulate_err=True)
        elif self.spec["remote_links_path"] in url:
            return MockRequest([{"name": "zlib-v1.2.3-1.slc7_x86-64.tar.gz"},
                                {"name": "zlib-v1.2.3-2.slc7_x86-64.tar.gz"}])
        raise NotImplementedError(url)

    @patch("alibuild_helpers.sync.open", new=lambda fn, mode: BytesIO())
    @patch("alibuild_helpers.sync.execute", new=lambda cmd, printer=None: 0)
    @patch("alibuild_helpers.sync.warning")
    @patch("alibuild_helpers.sync.error")
    @patch("alibuild_helpers.sync.get")
    def test_http_remote(self, mock_get, mock_error, mock_warning):
        mock_get.side_effect = self.mock_get
        syncer = sync.HttpRemoteSync(remoteStore="https://localhost/test",
                                     architecture="osx_x86-64",
                                     workdir="/sw", insecure=False)

        for test_hash in TEST_HASHES:
            mock_error.reset_mock()
            mock_warning.reset_mock()
            self.spec["remote_revision_hash"] = test_hash

            syncer.syncToLocal("zlib", self.spec)

            if test_hash == GOOD_HASH:
                mock_error.assert_not_called()
            elif test_hash == BAD_HASH:
                # We can't use mock_error.assert_called_once_with because two
                # PartialDownloadError instances don't compare equal.
                self.assertEqual(len(mock_error.call_args_list), 1)
                self.assertEqual(mock_error.call_args_list[0][0][0],
                                 "GET %s failed: %s")
                self.assertEqual(mock_error.call_args_list[0][0][1],
                                 "https://localhost/test//sw/path/"
                                 "zlib-v1.2.3-2.slc7_x86-64.tar.gz")
                self.assertIsInstance(mock_error.call_args_list[0][0][2],
                                      sync.PartialDownloadError)
                mock_warning.assert_not_called()
                mock_warning.assert_not_called()
            else:
                raise ValueError("unhandled hash")

            syncer.syncToRemote("zlib", self.spec)
            syncer.syncDistLinksToRemote("/sw/dist")

        self.spec["remote_store_path"] = "/triggers_a_404/path"
        syncer.syncToLocal("zlib", self.spec)
        mock_warning.assert_called_once_with(
            "%s (%s) not fetched: have you tried updating the recipes?",
            "zlib", BAD_HASH)

    @patch("alibuild_helpers.sync.execute", new=lambda cmd, printer=None: 0)
    @patch("alibuild_helpers.sync.os")
    def test_sync(self, mock_os):
        # file does not exist locally: force download
        mock_os.path.exists.side_effect = lambda path: False
        mock_os.path.islink.side_effect = lambda path: False
        mock_os.path.isfile.side_effect = lambda path: False

        syncers = [
            sync.NoRemoteSync(),
            sync.RsyncRemoteSync(remoteStore="ssh://localhost/test",
                                 writeStore="ssh://localhost/test",
                                 architecture="osx_x86-64",
                                 workdir="/sw", rsyncOptions=""),
            sync.S3RemoteSync(remoteStore="s3://localhost",
                              writeStore="s3://localhost",
                              architecture="slc7_x86-64",
                              workdir="/sw"),
        ]

        for test_hash in TEST_HASHES:
            self.spec["remote_revision_hash"] = test_hash
            for syncer in syncers:
                syncer.syncToLocal("zlib", self.spec)
                syncer.syncToRemote("zlib", self.spec)
                syncer.syncDistLinksToRemote("/sw/dist")

        self.spec["remote_store_path"] = "/triggers_a_404/path"
        for syncer in syncers:
            syncer.syncToLocal("zlib", self.spec)


class Boto3TestCase(unittest.TestCase):
    def setUp(self):
        self.spec = DUMMY_SPEC.copy()

    def mock_s3(self):
        from botocore.exceptions import ClientError

        def paginate_listdir(Bucket, Delimiter, Prefix):
            if Prefix == self.spec["remote_store_path"] + "/":
                if self.spec["remote_revision_hash"] == GOOD_HASH:
                    return [{"Contents": [{"Key": "zlib-v1.2.3-1.slc7_x86-64.tar.gz"}]}]
                elif self.spec["remote_revision_hash"] == BAD_HASH:
                    return [{"Contents": [{"Key": self.spec["remote_store_path"] +
                                           Delimiter + "zlib-v1.2.3-2.slc7_x86-64.tar.gz"}]}]
            elif Prefix == self.spec["remote_links_path"] + "/":
                return [{"Contents": [{"Key": self.spec["remote_links_path"] +
                                       Delimiter + "zlib-v1.2.3-1.slc7_x86-64.tar.gz"},
                                      {"Key": self.spec["remote_links_path"] +
                                       Delimiter + "zlib-v1.2.3-2.slc7_x86-64.tar.gz"}]}]
            raise NotImplementedError("unknown prefix " + Prefix)

        def head_object(Bucket, Key):
            if BAD_HASH in Key:
                err = ClientError()
                err.response = {"Error": {"Code": "404"}}
                raise err

        def download_file(Bucket, Key, Filename):
            self.assertNotIn(BAD_HASH, Key, "tried to fetch nonexistent key")

        def get_object(Bucket, Key):
            if Key.endswith(".manifest"):
                return {"Body": MagicMock(iter_lines=lambda: [
                    b"zlib-v1.2.3-1.slc7_x86-64.tar.gz\t...from manifest\n"])}
            return {"Body": MagicMock(read=lambda: b"...fetched individually")}

        return MagicMock(
            get_paginator=lambda method: (MagicMock(paginate=paginate_listdir)
                                          if method == "list_objects_v2"
                                          else NotImplemented),
            head_object=head_object,
            download_file=download_file,
            get_object=get_object,
        )

    @patch("alibuild_helpers.sync.execute", new=lambda cmd, printer=None: 0)
    @patch("alibuild_helpers.sync.glob.glob", new=lambda path: [])
    @patch("alibuild_helpers.sync.os.listdir", new=lambda path: [])
    @patch("alibuild_helpers.sync.Boto3RemoteSync._s3_init", new=lambda _: None)
    @patch("alibuild_helpers.sync.os")
    def test_boto3(self, mock_os):
        if sys.version_info < (3, 6):
            return
        # file does not exist locally: force download
        mock_os.path.exists.side_effect = lambda path: False
        mock_os.path.islink.side_effect = lambda path: False
        mock_os.path.isfile.side_effect = lambda path: False

        b3sync = sync.Boto3RemoteSync(
            remoteStore="b3://localhost", writeStore="b3://localhost",
            architecture="slc7_x86-64", workdir="/sw")
        b3sync.s3 = self.mock_s3()

        for test_hash in TEST_HASHES:
            self.spec["remote_revision_hash"] = test_hash
            b3sync.syncToLocal("zlib", self.spec)
            b3sync.syncToRemote("zlib", self.spec)
            b3sync.syncDistLinksToRemote("/sw/dist")


if __name__ == '__main__':
  unittest.main()
