import os
import os.path
import sys
import unittest
from io import BytesIO

from unittest.mock import patch, MagicMock

from alibuild_helpers import sync
from alibuild_helpers.utilities import resolve_links_path, resolve_store_path
from alibuild_helpers.utilities import resolve_cas_path, resolve_ac_path
import json


ARCHITECTURE = "slc7_x86-64"
PACKAGE = "zlib"
GOOD_HASH = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
BAD_HASH = "baadf00dbaadf00dbaadf00dbaadf00dbaadf00d"
NONEXISTENT_HASH = "TRIGGERS_A_404"
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


def tarball_name(spec):
    return ("{package}-{version}-{revision}.{arch}.tar.gz"
            .format(arch=ARCHITECTURE, **spec))


TAR_NAMES = tarball_name(GOOD_SPEC), tarball_name(BAD_SPEC), tarball_name(MISSING_SPEC)


class MockRequest:
    def __init__(self, j, simulate_err=False) -> None:
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

        # Make sure conflict detection is working for tarball sync.
        b3sync.s3.put_object.reset_mock()
        b3sync.s3.upload_file.reset_mock()
        self.assertRaises(SystemExit, b3sync.upload_symlinks_and_tarball, BAD_SPEC)
        b3sync.s3.put_object.assert_not_called()
        b3sync.s3.upload_file.assert_not_called()


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
@patch("alibuild_helpers.sync.REAPIRemoteSync._s3_init", new=MagicMock())
class REAPIRemoteSyncTestCase(unittest.TestCase):
    """Check the reapi:// (Action Cache + CAS) remote store."""

    def make_sync(self, client):
        reapi = sync.REAPIRemoteSync(
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

    def test_parse_url(self) -> None:
        self.assertEqual(
            sync.REAPIRemoteSync._parse_reapi_url("reapi://s3.cern.ch/alibuild-repo", "https"),
            ("https://s3.cern.ch", "alibuild-repo"))
        self.assertEqual(
            sync.REAPIRemoteSync._parse_reapi_url("reapi://localhost:9000/bkt", "http"),
            ("http://localhost:9000", "bkt"))
        self.assertEqual(sync.REAPIRemoteSync._parse_reapi_url("", "https"), ("", ""))

    def test_factory(self) -> None:
        obj = sync.remote_from_url("reapi://s3.example/bucket",
                                   "reapi://s3.example/bucket", ARCHITECTURE, "/sw")
        self.assertIsInstance(obj, sync.REAPIRemoteSync)
        self.assertEqual(obj.remoteStore, "bucket")
        self.assertEqual(obj.endpoint_url, "https://s3.example")

    @patch("alibuild_helpers.sync.file_digest",
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

    @patch("alibuild_helpers.sync.file_digest",
           new=MagicMock(return_value=REAPI_CONTENT_HASH))
    @patch("os.path.getsize", new=MagicMock(return_value=4096))
    @patch("os.listdir",
           new=lambda path: [tarball_name(REAPI_SPEC)] if path.endswith("-1") else [])
    @patch("os.readlink", new=MagicMock(return_value="../../store/de/dead/x.tar.gz"))
    @patch("os.path.islink", new=MagicMock(return_value=True))
    def test_upload_routes_ledger_and_artifact_to_separate_stores(self) -> None:
        client = self.make_client()
        reapi = sync.REAPIRemoteSync(
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

    @patch("alibuild_helpers.sync.file_digest",
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

    @patch("alibuild_helpers.sync.file_digest",
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

    @patch("alibuild_helpers.sync.file_digest",
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
        reapi = sync.REAPIRemoteSync("reapi://localhost/bucket", "reapi://localhost/bucket",
                                     architecture=ARCHITECTURE, workdir="/sw",
                                     storage="permanent")
        reapi.s3 = client
        reapi.upload_symlinks_and_tarball(REAPI_SPEC)
        client.upload_file.assert_not_called()        # deduped, not re-uploaded
        client.put_object_tagging.assert_called_once()
        self.assertEqual(client.put_object_tagging.call_args.kwargs["Tagging"],
                         {"TagSet": [{"Key": "retention", "Value": "permanent"}]})

    @patch("os.path.exists", new=MagicMock(return_value=False))
    def test_download_refreshes_old_ephemeral(self) -> None:
        from datetime import datetime, timezone, timedelta
        client = self.make_client()
        client.get_object_tagging = MagicMock(
            return_value={"TagSet": [{"Key": "retention", "Value": "ephemeral"}]})
        client.head_object = MagicMock(
            return_value={"LastModified": datetime.now(timezone.utc) - timedelta(days=75)})
        client.copy_object = MagicMock()
        reapi = sync.REAPIRemoteSync("reapi://localhost/bucket", "reapi://localhost/bucket",
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


if __name__ == '__main__':
    unittest.main()
