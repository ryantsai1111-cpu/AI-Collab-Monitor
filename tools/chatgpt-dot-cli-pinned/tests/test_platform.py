import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from chatgpt_dot.api import AuthError, load_auth
from chatgpt_dot.platform import FileLock, atomic_write_text, codex_auth_path, configure_stdio, posix_mode


class PlatformTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("CODEX_HOME", None)

    def test_auth_path_is_under_home(self):
        home = Path("C:/Users/example") if os.name == "nt" else Path("/tmp/example-home")
        with mock.patch("chatgpt_dot.platform.Path.home", return_value=home):
            self.assertEqual(codex_auth_path(), home / ".codex" / "auth.json")

    def test_auth_path_follows_codex_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["CODEX_HOME"] = tmp
            self.assertEqual(codex_auth_path(), Path(tmp) / "auth.json")
            with self.assertRaises(AuthError) as caught:
                load_auth()
        self.assertIn("CODEX_HOME", str(caught.exception))
        self.assertNotIn(tmp, str(caught.exception))

    def test_explicit_auth_path_expands_tilde(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "auth.json").write_text(
                json.dumps({"auth_mode": "chatgpt", "tokens": {"access_token": "tok", "account_id": "acct"}}),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"HOME": tmp, "USERPROFILE": tmp}):
                self.assertEqual(load_auth("~/auth.json"), ("tok", "acct"))

    def test_auth_file_that_is_not_an_object_is_an_auth_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            for body in (b"[1, 2]", b'"text"', b"\xff\xfe\x00"):
                auth = Path(tmp) / "auth.json"
                auth.write_bytes(body)
                with self.assertRaises(AuthError):
                    load_auth(auth)

    def test_load_auth_reads_home_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            auth = home / ".codex" / "auth.json"
            auth.parent.mkdir()
            auth.write_text(
                json.dumps(
                    {"auth_mode": "chatgpt", "tokens": {"access_token": "tok", "account_id": "acct"}}
                ),
                encoding="utf-8",
                newline="\n",
            )
            with mock.patch("chatgpt_dot.platform.Path.home", return_value=home):
                self.assertEqual(load_auth(), ("tok", "acct"))

    def test_missing_auth_file_says_how_to_log_in_without_the_home_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with mock.patch("chatgpt_dot.platform.Path.home", return_value=home):
                with self.assertRaises(AuthError) as caught:
                    load_auth()
        message = str(caught.exception)
        self.assertTrue(message.startswith("cannot read auth file: "))
        self.assertIn("~/.codex/auth.json", message)
        self.assertIn("codex login", message)
        self.assertNotIn(str(home), message)

    def test_missing_explicit_auth_file_does_not_echo_the_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "elsewhere.json"
            with self.assertRaises(AuthError) as caught:
                load_auth(missing)
        message = str(caught.exception)
        self.assertIn("the --auth file", message)
        self.assertNotIn(tmp, message)

    def test_configure_stdio_windows(self):
        stdout = mock.Mock()
        stderr = mock.Mock()
        with (
            mock.patch("chatgpt_dot.platform.os.name", "nt"),
            mock.patch("chatgpt_dot.platform.sys.platform", "win32"),
            mock.patch("chatgpt_dot.platform.sys.stdout", stdout),
            mock.patch("chatgpt_dot.platform.sys.stderr", stderr),
        ):
            configure_stdio()
        expected = {"encoding": "utf-8", "errors": "replace", "newline": "\n"}
        stdout.reconfigure.assert_called_once_with(**expected)
        stderr.reconfigure.assert_called_once_with(**expected)

    def test_configure_stdio_posix_skips(self):
        stdout = mock.Mock()
        with (
            mock.patch("chatgpt_dot.platform.os.name", "posix"),
            mock.patch("chatgpt_dot.platform.sys.platform", "linux"),
            mock.patch("chatgpt_dot.platform.sys.stdout", stdout),
        ):
            configure_stdio()
        stdout.reconfigure.assert_not_called()

    def test_configure_stdio_ignores_reconfigure_errors(self):
        stdout = mock.Mock()
        stdout.reconfigure.side_effect = OSError("closed")
        stderr = mock.Mock()
        with (
            mock.patch("chatgpt_dot.platform.os.name", "nt"),
            mock.patch("chatgpt_dot.platform.sys.platform", "win32"),
            mock.patch("chatgpt_dot.platform.sys.stdout", stdout),
            mock.patch("chatgpt_dot.platform.sys.stderr", stderr),
        ):
            configure_stdio()
        stderr.reconfigure.assert_called_once()

    def test_posix_mode_skipped_on_windows(self):
        # Build the path first. Python 3.11 refuses to construct a path
        # while os.name is patched to nt on a POSIX host.
        path = Path("missing-auth.json")
        with (
            mock.patch("chatgpt_dot.platform.os.name", "nt"),
            mock.patch("chatgpt_dot.platform.sys.platform", "win32"),
        ):
            self.assertIsNone(posix_mode(path))

    def test_posix_mode_on_posix(self):
        # Mock the stat result. Windows chmod does not store Unix 0600 bits,
        # so this branch must not depend on the host filesystem.
        path = Path("auth.json")
        stat_result = mock.Mock(st_mode=0o100600)
        with (
            mock.patch("chatgpt_dot.platform.os.name", "posix"),
            mock.patch("chatgpt_dot.platform.sys.platform", "linux"),
            mock.patch.object(Path, "stat", return_value=stat_result),
        ):
            self.assertEqual(posix_mode(path), 0o600)

    def test_atomic_write_uses_lf_and_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.txt"
            lock = Path(tmp) / "note.lock"
            with FileLock(lock):
                atomic_write_text(path, "你好\n")
            self.assertEqual(path.read_text(encoding="utf-8"), "你好\n")
            self.assertNotIn(b"\r\n", path.read_bytes())

    def test_file_lock_windows_branch(self):
        fake = mock.Mock()
        fake.LK_LOCK = 0
        fake.LK_UNLCK = 1
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock"
            with (
                mock.patch("chatgpt_dot.platform.os.name", "nt"),
                mock.patch("chatgpt_dot.platform.sys.platform", "win32"),
                mock.patch.dict(sys.modules, {"msvcrt": fake}),
            ):
                with FileLock(path):
                    pass
        self.assertEqual(fake.locking.call_count, 2)


if __name__ == "__main__":
    unittest.main()
