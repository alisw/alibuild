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
RESUME_HASH = "f00dcafef00dcafef00dcafef00dcafef00dcafe"
GOOD_SPEC = {    # fully present on the remote store
    "package": PACKAGE, "version": "v1.3.1", "revision": "1",
    "hash": GOOD_HASH,
    "remote_revision_hash": GOOD_HASH,
    "remote_hashes": [GOOD_HASH],
}
BAD_SPEC = {     # partially present on the remote store
    "package": PACKAGE, "version": "v1.3.1", "revision": "2",
    "hash": BAD_HASH,
    "remote_revision_hash": BAD_HASH,
    "remote_hashes": [BAD_HASH],
}
MISSING_SPEC = {    # completely absent from the remote store
    "package": PACKAGE, "version": "v1.3.1", "revision": "3",
    "hash": NONEXISTENT_HASH,
    "remote_revision_hash": NONEXISTENT_HASH,
    "remote_hashes": [NONEXISTENT_HASH],
}
RESUME_SPEC = {  # symlink published, but the store object never made it
    "package": PACKAGE, "version": "v1.3.1", "revision": "4",
    "hash": RESUME_HASH,
    "remote_revision_hash": RESUME_HASH,
    "remote_hashes": [RESUME_HASH],
}


def tarball_name(spec):
    return ("{package}-{version}-{revision}.{arch}.tar.gz"
            .format(arch=ARCHITECTURE, **spec))


TAR_NAMES = tarball_name(GOOD_SPEC), tarball_name(BAD_SPEC), tarball_name(MISSING_SPEC)


class MockRequest:
    def __init__(self, j, simulate_err=False, redirect=None) -> None:
        self.j = j
        self.simulate_err = simulate_err
        self.status_code = 200 if j else 404
        self._bytes_left = 123456
        self.headers = {"content-length": str(self._bytes_left)}
        if redirect:
            self.headers["x-amz-website-redirect-location"] = redirect

    def close(self):
        pass

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

    @patch("alibuild_helpers.sync.open", new=lambda fn, mode: BytesIO())
    @patch("os.path.isfile", new=MagicMock(return_value=False))
    @patch("os.rename", new=MagicMock(return_value=None))
    @patch("os.makedirs", new=MagicMock(return_value=None))
    @patch("os.listdir", new=MagicMock(return_value=[]))
    @patch("alibuild_helpers.sync.symlink", new=MagicMock(return_value=None))
    @patch("requests.Session.get")
    def test_http_follows_store_redirect(self, mock_get):
        """A store object that is a redirect stub is followed to the real bytes."""
        store = "https://localhost/test"
        cas = "cas/sha256/de/deadbeef"
        requested = []

        def get(url, *args, **kw):
            requested.append(url)
            if url.endswith(tarball_name(GOOD_SPEC)) and "/store/" in url:
                # The legacy store object holds no bytes, just a pointer.
                return MockRequest([{"name": tarball_name(GOOD_SPEC)}],
                                   redirect="/" + cas)
            if url.endswith(cas):
                return MockRequest([{"name": tarball_name(GOOD_SPEC)}])
            return self.mock_get(url, *args, **kw)

        mock_get.side_effect = get
        syncer = sync.HttpRemoteSync(remoteStore=store, architecture=ARCHITECTURE,
                                     workdir="/sw", insecure=False)
        syncer.httpBackoff = 0
        syncer.fetch_tarball(GOOD_SPEC)

        self.assertIn("%s/%s" % (store, cas), requested,
                      "the redirect was not followed: %s" % requested)

    @patch("alibuild_helpers.sync.open", new=lambda fn, mode: BytesIO())
    @patch("os.path.isfile", new=MagicMock(return_value=False))
    @patch("os.rename", new=MagicMock(return_value=None))
    @patch("os.makedirs", new=MagicMock(return_value=None))
    @patch("os.listdir", new=MagicMock(return_value=[]))
    @patch("alibuild_helpers.sync.symlink", new=MagicMock(return_value=None))
    @patch("requests.Session.get")
    def test_http_follows_absolute_store_redirect(self, mock_get):
        """An absolute redirect target is used as given, not joined onto the store.

        That is what lets the legacy TARS/ tree live in one bucket while the CAS
        blobs live in another: joining an absolute URL onto the store being read
        would produce .../<store>/https:/<host>/... and 404 mid-download.
        """
        store = "https://localhost/legacy"
        elsewhere = "https://localhost/cas-bucket/cas/sha256/de/deadbeef"
        requested = []

        def get(url, *args, **kw):
            requested.append(url)
            if url.endswith(tarball_name(GOOD_SPEC)) and "/store/" in url:
                return MockRequest([{"name": tarball_name(GOOD_SPEC)}],
                                   redirect=elsewhere)
            if url == elsewhere:
                return MockRequest([{"name": tarball_name(GOOD_SPEC)}])
            return self.mock_get(url, *args, **kw)

        mock_get.side_effect = get
        syncer = sync.HttpRemoteSync(remoteStore=store, architecture=ARCHITECTURE,
                                     workdir="/sw", insecure=False)
        syncer.httpBackoff = 0
        syncer.fetch_tarball(GOOD_SPEC)

        self.assertIn(elsewhere, requested,
                      "the absolute redirect was not followed as-is: %s" % requested)
        self.assertFalse([u for u in requested if u.startswith(store + "/https")],
                         "the absolute target was joined onto the store: %s" % requested)

    def test_s3cmd_follows_store_redirect(self):
        """s3cmd cannot see the redirect header, so the stub is spotted by content."""
        commands = []
        with patch("alibuild_helpers.sync.execute",
                   new=lambda cmd, printer=None: commands.append(cmd) or 0):
            sync.S3RemoteSync(remoteStore="s3://localhost", writeStore="s3://localhost",
                              architecture=ARCHITECTURE, workdir="/sw") \
                .fetch_tarball(GOOD_SPEC)
        self.assertIn("1f8b", commands[0],
                      "the gzip magic check is gone, so redirect stubs would be "
                      "saved as tarballs again")

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
                       resolve_store_path(ARCHITECTURE, BAD_HASH),
                       resolve_store_path(ARCHITECTURE, RESUME_HASH)):
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
            elif dir.endswith("-" + RESUME_SPEC["revision"]):
                # The interrupted publish also died among the dist symlinks.
                return [{"Contents": [
                    {"Key": dir + Delimiter + "somedep-v1-1.%s.tar.gz" % ARCHITECTURE},
                ]}]
            else:
                raise NotImplementedError("unknown dist prefix " + Prefix)

        def head_object(Bucket, Key):
            if NONEXISTENT_HASH in Key or BAD_HASH in Key or \
               RESUME_HASH in Key or \
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
    def test_tarball_download(self) -> None:
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
        [] if path.endswith("-" + MISSING_SPEC["revision"]) else NotImplemented))
    @patch("os.path.islink", new=MagicMock(return_value=False))
    def test_missing_local_link_is_recreated(self) -> None:
        """A tarball in the local store whose link was never made is publishable."""
        b3sync = sync.Boto3RemoteSync(
            remoteStore="b3://localhost", writeStore="b3://localhost",
            architecture=ARCHITECTURE, workdir="/sw")
        b3sync.s3 = self.mock_s3()
        b3sync.upload_symlinks_and_tarball(MISSING_SPEC)
        tar_path = os.path.join(resolve_store_path(ARCHITECTURE, NONEXISTENT_HASH),
                                tarball_name(MISSING_SPEC))
        # The body is the store path relative to TARS/. build.py parses the
        # local link, which fetch_symlinks builds as "../../" + body, to work
        # out which revisions are taken -- a body carrying the "TARS/" prefix
        # produces a link it cannot parse, so the revision looks free and the
        # next build collides with what is already published.
        body = tar_path[len("TARS/"):]
        b3sync.s3.put_object.assert_any_call(
            Bucket="localhost",
            Key=os.path.join(resolve_links_path(ARCHITECTURE, PACKAGE),
                             tarball_name(MISSING_SPEC)),
            Body=body.encode("utf-8"))
        self.assertNotIn("TARS/", body)
        self.assertTrue(("../../" + body).startswith("../../%s/store/" % ARCHITECTURE),
                        "local link would not parse: %r" % ("../../" + body))

    @patch("os.listdir", new=lambda path: (
        [tarball_name(GOOD_SPEC)] if path.endswith("-" + GOOD_SPEC["revision"]) else
        [tarball_name(BAD_SPEC)] if path.endswith("-" + BAD_SPEC["revision"]) else
        [] if path.endswith("-" + MISSING_SPEC["revision"]) else
        NotImplemented
    ))
    @patch("os.readlink", new=MagicMock(return_value="dummy path"))
    @patch("os.path.islink", new=MagicMock(return_value=True))
    def test_tarball_upload(self) -> None:
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

        # Conflict detection: the remote symlink points at somebody else's
        # store path, so they own this package and we must not touch it.
        b3sync.s3.put_object.reset_mock()
        b3sync.s3.upload_file.reset_mock()
        self.assertRaises(SystemExit, b3sync.upload_symlinks_and_tarball, BAD_SPEC)
        b3sync.s3.put_object.assert_not_called()
        b3sync.s3.upload_file.assert_not_called()

    @patch("os.listdir", new=lambda path: (
        [tarball_name(RESUME_SPEC)] if path.endswith("-" + RESUME_SPEC["revision"]) else
        NotImplemented
    ))
    @patch("os.path.islink", new=MagicMock(return_value=True))
    def test_tarball_upload_resume(self) -> None:
        """A publish interrupted between the symlink and the tarball is resumable."""
        link_target = os.path.join(
            resolve_store_path(ARCHITECTURE, RESUME_HASH), tarball_name(RESUME_SPEC))
        b3sync = sync.Boto3RemoteSync(
            remoteStore="b3://localhost", writeStore="b3://localhost",
            architecture=ARCHITECTURE, workdir="/sw")
        b3sync.s3 = self.mock_s3()
        # The remote symlink points where we are about to write: ours.
        b3sync.s3.get_object = MagicMock(return_value={
            "Body": MagicMock(read=lambda: link_target.encode("utf-8")),
        })

        with patch("os.readlink", new=MagicMock(return_value="../../" + link_target)):
            b3sync.upload_symlinks_and_tarball(RESUME_SPEC)

        b3sync.s3.upload_file.assert_called()
        link_key = os.path.join(resolve_links_path(ARCHITECTURE, PACKAGE),
                                tarball_name(RESUME_SPEC))
        for call in b3sync.s3.put_object.mock_calls:
            self.assertNotEqual(call.kwargs.get("Key"), link_key)

    @patch("os.listdir", new=lambda path: (
        [tarball_name(RESUME_SPEC)] if path.endswith("-" + RESUME_SPEC["revision"]) else
        NotImplemented
    ))
    @patch("os.path.islink", new=MagicMock(return_value=True))
    def test_tarball_present_link_missing(self) -> None:
        """Only the missing symlink is written; the tarball is not re-uploaded."""
        link_target = os.path.join(
            resolve_store_path(ARCHITECTURE, RESUME_HASH), tarball_name(RESUME_SPEC))
        b3sync = sync.Boto3RemoteSync(
            remoteStore="b3://localhost", writeStore="b3://localhost",
            architecture=ARCHITECTURE, workdir="/sw")
        b3sync.s3 = self.mock_s3()
        b3sync._s3_key_exists = lambda path: path == link_target

        with patch("os.readlink", new=MagicMock(return_value="../../" + link_target)):
            b3sync.upload_symlinks_and_tarball(RESUME_SPEC)

        b3sync.s3.upload_file.assert_not_called()
        b3sync.s3.put_object.assert_any_call(
            Bucket="localhost", IfNoneMatch="*",
            Key=os.path.join(resolve_links_path(ARCHITECTURE, PACKAGE),
                             tarball_name(RESUME_SPEC)),
            Body=link_target.encode("utf-8"))

    @patch("os.listdir", new=lambda path: (
        [tarball_name(RESUME_SPEC)] if path.endswith("-" + RESUME_SPEC["revision"]) else
        NotImplemented
    ))
    @patch("os.readlink", new=MagicMock(return_value="dummy path"))
    @patch("os.path.islink", new=MagicMock(return_value=True))
    def test_tarball_upload_unreadable_link(self) -> None:
        """If we cannot tell who owns the existing symlink, we must not touch it."""
        from botocore.exceptions import ClientError
        b3sync = sync.Boto3RemoteSync(
            remoteStore="b3://localhost", writeStore="b3://localhost",
            architecture=ARCHITECTURE, workdir="/sw")
        b3sync.s3 = self.mock_s3()
        b3sync.s3.get_object = MagicMock(side_effect=ClientError(
            {"Error": {"Code": "AccessDenied"}}, "get_object"))

        self.assertRaises(SystemExit, b3sync.upload_symlinks_and_tarball, RESUME_SPEC)
        b3sync.s3.put_object.assert_not_called()
        b3sync.s3.upload_file.assert_not_called()

    def fresh_upload_sync(self):
        """A sync object publishing MISSING_SPEC, which is absent from the remote."""
        b3sync = sync.Boto3RemoteSync(
            remoteStore="b3://localhost", writeStore="b3://localhost",
            architecture=ARCHITECTURE, workdir="/sw")
        b3sync.s3 = self.mock_s3()
        return b3sync

    def test_conditional_write_required(self) -> None:
        """Publishing without If-None-Match support must fail before any work."""
        import boto3
        b3sync = self.fresh_upload_sync()
        # A mock has no service model, standing in for an old botocore.
        self.assertRaises(SystemExit, b3sync._check_conditional_write_support)
        b3sync.s3 = boto3.client("s3", region_name="us-east-1",
                                 aws_access_key_id="x", aws_secret_access_key="y")
        b3sync._check_conditional_write_support()

    @patch("os.listdir", new=lambda path: (
        [] if path.endswith("-" + MISSING_SPEC["revision"]) else NotImplemented))
    @patch("os.readlink", new=MagicMock(return_value="dummy path"))
    @patch("os.path.islink", new=MagicMock(return_value=True))
    def test_symlink_claimed_conditionally(self) -> None:
        """The symlink is claimed with If-None-Match, where the store supports it."""
        b3sync = self.fresh_upload_sync()
        b3sync.upload_symlinks_and_tarball(MISSING_SPEC)
        b3sync.s3.put_object.assert_any_call(
            IfNoneMatch="*", Bucket="localhost",
            Key=os.path.join(resolve_links_path(ARCHITECTURE, PACKAGE),
                             tarball_name(MISSING_SPEC)),
            Body=b"dummy path")

    @patch("os.listdir", new=lambda path: (
        [] if path.endswith("-" + MISSING_SPEC["revision"]) else NotImplemented))
    @patch("os.readlink", new=MagicMock(return_value="dummy path"))
    @patch("os.path.islink", new=MagicMock(return_value=True))
    def test_symlink_claim_lost_to_other_build(self) -> None:
        """Losing the claim to a build of a different hash must abort the upload."""
        from botocore.exceptions import ClientError
        b3sync = self.fresh_upload_sync()
        b3sync.s3.put_object = MagicMock(side_effect=ClientError(
            {"Error": {"Code": "PreconditionFailed"}}, "put_object"))
        # mock_s3's get_object reports a target that is not ours.
        self.assertRaises(SystemExit, b3sync.upload_symlinks_and_tarball, MISSING_SPEC)
        b3sync.s3.upload_file.assert_not_called()

    @patch("os.listdir", new=lambda path: (
        [] if path.endswith("-" + MISSING_SPEC["revision"]) else NotImplemented))
    @patch("os.readlink", new=MagicMock(return_value="dummy path"))
    @patch("os.path.islink", new=MagicMock(return_value=True))
    def test_symlink_claim_lost_to_same_hash(self) -> None:
        """We upload anyway: the winner of the claim may have died mid-publish."""
        b3sync = self.claim_losing_sync()
        b3sync.upload_symlinks_and_tarball(MISSING_SPEC)
        b3sync.s3.upload_file.assert_called()

    @patch("os.listdir", new=lambda path: (
        [] if path.endswith("-" + MISSING_SPEC["revision"]) else NotImplemented))
    @patch("os.readlink", new=MagicMock(return_value="dummy path"))
    @patch("os.path.islink", new=MagicMock(return_value=True))
    def test_symlink_claim_lost_to_finished_build(self) -> None:
        """...but not if the winner already finished: nothing left to do."""
        b3sync = self.claim_losing_sync()
        tar_path = os.path.join(resolve_store_path(ARCHITECTURE, NONEXISTENT_HASH),
                                tarball_name(MISSING_SPEC))
        # It shows up only after the two existence checks at the top.
        checks = []

        def key_exists(path):
            checks.append(path)
            return path == tar_path and len(checks) > 2

        b3sync._s3_key_exists = key_exists
        b3sync.upload_symlinks_and_tarball(MISSING_SPEC)
        b3sync.s3.upload_file.assert_not_called()

    @patch("os.listdir", new=lambda path: (
        [] if path.endswith("-" + MISSING_SPEC["revision"]) else NotImplemented))
    @patch("os.readlink", new=MagicMock(return_value="dummy path"))
    @patch("os.path.islink", new=MagicMock(return_value=True))
    def test_symlink_deleted_under_us(self) -> None:
        """A symlink deleted while we claim it must not leave an unreferenced tarball."""
        from botocore.exceptions import ClientError
        b3sync = self.claim_losing_sync()
        b3sync.s3.get_object = MagicMock(side_effect=ClientError(
            {"Error": {"Code": "NoSuchKey"}}, "get_object"))

        self.assertRaises(SystemExit, b3sync.upload_symlinks_and_tarball, MISSING_SPEC)
        b3sync.s3.upload_file.assert_not_called()

    def claim_losing_sync(self):
        """A sync object that always loses the race to claim the symlink.

        The winner reports the same target as ours, so it is building the same
        hash rather than conflicting with us.
        """
        from botocore.exceptions import ClientError

        def put_object(**kwargs):
            if "IfNoneMatch" in kwargs:
                raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "put_object")

        b3sync = self.fresh_upload_sync()
        b3sync.s3.put_object = MagicMock(side_effect=put_object)
        b3sync.s3.get_object = MagicMock(return_value={
            "Body": MagicMock(read=lambda: b"dummy path")})
        return b3sync


if __name__ == '__main__':
    unittest.main()
