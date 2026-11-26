import hashlib
import io
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from enc_editor import updates


INSTALLER = b"test installer"
RELEASE = updates.Release("3.10.0", "v3.10.0", len(INSTALLER), hashlib.sha256(INSTALLER).hexdigest())


def metadata():
    return {
        "tag_name": RELEASE.tag,
        "body": "Release notes",
        "assets": [{
            "name": RELEASE.filename,
            "state": "uploaded",
            "digest": f"sha256:{RELEASE.sha256}",
            "browser_download_url": RELEASE.url,
            "size": RELEASE.size,
        }],
    }


class ReleaseTests(unittest.TestCase):
    def test_only_new_stable_releases_are_offered(self):
        data = metadata()
        release = updates.parse_release(data, current="3.9.9")
        self.assertEqual(release.notes, "Release notes")
        self.assertEqual(release.url, RELEASE.url)
        self.assertIsNone(updates.parse_release(data, current="3.10.0"))
        for flag in ("prerelease", "draft"):
            self.assertIsNone(updates.parse_release({**data, flag: True}, current="3.9.9"))

    def test_rejects_missing_digest_and_unofficial_or_mismatched_assets(self):
        for key, invalid in (
            ("digest", None), ("size", True), ("name", "source.zip"),
            ("browser_download_url", RELEASE.url.replace("github.com", "example.org")),
            ("browser_download_url", RELEASE.url.replace("v3.10.0", "v3.11.0")),
        ):
            with self.subTest(key=key, invalid=invalid):
                data = metadata()
                data["assets"][0][key] = invalid
                with self.assertRaises(updates.UpdateError):
                    updates.parse_release(data, current="3.9.9")


class DownloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.target = self.directory / RELEASE.filename

    def test_uses_only_verified_cache_and_replaces_tampered_files(self):
        self.target.write_bytes(b"?" * RELEASE.size)
        with patch.object(updates, "_open", return_value=io.BytesIO(INSTALLER)) as request:
            self.assertEqual(updates.download_update(RELEASE, directory=self.directory), self.target)
            self.assertEqual(updates.download_update(RELEASE, directory=self.directory), self.target)
        request.assert_called_once_with(RELEASE.url)
        self.assertEqual(self.target.read_bytes(), INSTALLER)
        self.assertEqual(list(self.directory.iterdir()), [self.target])

    def test_invalid_download_leaves_no_installer_or_partial(self):
        for payload in (INSTALLER[:-1], INSTALLER + b"?", b"?" * RELEASE.size):
            with self.subTest(payload=payload), patch.object(updates, "_open", return_value=io.BytesIO(payload)):
                with self.assertRaises(updates.UpdateError):
                    updates.download_update(RELEASE, directory=self.directory)
            self.assertEqual(list(self.directory.iterdir()), [])

    def test_cancelling_a_download_cleans_partial_file(self):
        cancel = threading.Event()
        with patch.object(updates, "_open", return_value=io.BytesIO(INSTALLER)):
            with self.assertRaises(updates.DownloadCancelled):
                updates.download_update(RELEASE, directory=self.directory, cancel=cancel,
                                        progress=lambda _value: cancel.set())
        self.assertEqual(list(self.directory.iterdir()), [])
