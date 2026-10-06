import argparse
import io
import json
import re
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from chatgpt_dot import __version__
from chatgpt_dot.api import (
    MESSAGE_LIMIT_MAX,
    ApiError,
    assert_allowed,
    get_many,
    list_messages,
    redact,
    request_json,
    require_dot_id,
    resolve_dot,
    send_message,
)
from chatgpt_dot.cli import main
from chatgpt_dot.summaries import dot_sender_ids, message_line


class AllowlistTests(unittest.TestCase):
    def test_get_paths(self):
        assert_allowed("GET", "/wham/usage")
        assert_allowed("GET", "/tbo")
        assert_allowed("GET", "/tbo/primary")
        assert_allowed("GET", "/tbo/abc-123~def/threads")
        assert_allowed("GET", "/tbo/by-thread/abc")
        assert_allowed("GET", "/messaging/rooms/room1/messages")

    def test_post_only_talks(self):
        assert_allowed("POST", "/messaging/rooms/room1/messages")
        assert_allowed("POST", "/tbo/abc/messaging-room")
        with self.assertRaises(ApiError):
            assert_allowed("POST", "/tbo/abc/runtime/pause")
        with self.assertRaises(ApiError):
            assert_allowed("DELETE", "/tbo/abc")
        with self.assertRaises(ApiError):
            assert_allowed("GET", "/tbo/abc/../../wham/usage")
        with self.assertRaises(ApiError):
            assert_allowed("GET", "/ps/orbit/thread/teams")

    def test_bad_id(self):
        with self.assertRaises(ApiError):
            assert_allowed("GET", "/tbo/has space/threads")
        with self.assertRaises(ApiError):
            assert_allowed("POST", "/messaging/rooms/../messages")


class RedactTests(unittest.TestCase):
    def test_masks_secret_keys(self):
        cleaned = redact(
            {
                "id": "ok",
                "access_token": "secret",
                "nested": {"Authorization": "Bearer x", "role": "user"},
            }
        )
        self.assertEqual(cleaned["id"], "ok")
        self.assertEqual(cleaned["access_token"], "***")
        self.assertEqual(cleaned["nested"]["Authorization"], "***")
        self.assertEqual(cleaned["nested"]["role"], "user")


class RequestTests(unittest.TestCase):
    def test_request_is_get_and_hides_token(self):
        captured = {}

        class Response:
            status = 200

            def read(self):
                return b'{"items":[]}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def urlopen(req, timeout=0):
            captured["method"] = req.get_method()
            captured["url"] = req.full_url
            captured["auth"] = req.get_header("Authorization")
            return Response()

        with mock.patch("chatgpt_dot.api.urllib.request.urlopen", urlopen):
            status, payload = request_json("super-secret-token", "acct", "/tbo")
        self.assertEqual(status, 200)
        self.assertEqual(captured["method"], "GET")
        self.assertTrue(captured["url"].endswith("/tbo"))
        self.assertIn("super-secret-token", captured["auth"])
        self.assertNotIn("super-secret-token", json.dumps(payload))

    def test_blocked_before_network(self):
        def urlopen(*args, **kwargs):
            raise AssertionError("network")

        with mock.patch("chatgpt_dot.api.urllib.request.urlopen", urlopen):
            with self.assertRaises(ApiError):
                request_json("tok", "acct", "/tbo/x/runtime/pause", method="POST", body={})

    def test_json_403_is_not_retried(self):
        calls = {"n": 0}

        def urlopen(req, timeout=0):
            calls["n"] += 1
            raise urllib.error.HTTPError(
                req.full_url, 403, "no", hdrs=None, fp=io.BytesIO(b'{"detail":{"code":"ineligible"}}')
            )

        with mock.patch("chatgpt_dot.api.urllib.request.urlopen", urlopen):
            status, payload = request_json("tok", "acct", "/tbo/abc/channels/email")
        self.assertEqual(calls["n"], 1)
        self.assertEqual(status, 403)
        self.assertEqual(payload["detail"]["code"], "ineligible")


class ResolveTests(unittest.TestCase):
    def test_multi_dot_points_at_list(self):
        with mock.patch("chatgpt_dot.api.list_dots", return_value=[{"id": "a"}, {"id": "b"}]):
            with self.assertRaises(ApiError) as ctx:
                resolve_dot("t", "acct", None)
        self.assertIn("chatgpt-dot-cli list", str(ctx.exception))

    def test_single_dot(self):
        with mock.patch(
            "chatgpt_dot.api.list_dots",
            return_value=[{"id": "dot-1", "display_name": ""}],
        ):
            dot = resolve_dot("a", "b", None)
        self.assertEqual(dot["id"], "dot-1")

    def test_send_posts_text(self):
        seen = {}

        def fake_post(access, account, path, body):
            seen["path"] = path
            seen["body"] = body
            seen["access"] = access
            return 200, {"id": "m1", "role": "user"}

        with mock.patch("chatgpt_dot.api.post_json", fake_post):
            payload = send_message("secret-token", "acct", "room1", "hello")
        self.assertEqual(seen["path"], "/messaging/rooms/room1/messages")
        self.assertEqual(seen["body"]["content"]["text"], "hello")
        self.assertEqual(seen["body"]["request_id"], seen["body"]["idempotency_token"])
        self.assertNotIn("secret-token", json.dumps(payload))


class SpeakerTests(unittest.TestCase):
    def test_aeon_member_is_dot(self):
        dot = {
            "messaging_room_preview": {
                "members": [
                    {"account_user_id": "calpi-abc", "aeon_id": "aeon-1"},
                    {"account_user_id": "user-xyz", "aeon_id": None},
                ]
            }
        }
        ids = dot_sender_ids(dot)
        self.assertEqual(ids, {"calpi-abc"})
        said = {"role": "user", "account_user_id": "calpi-abc", "content": {"text": "hi"}}
        asked = {"role": "user", "account_user_id": "user-xyz", "content": {"text": "yo"}}
        self.assertEqual(message_line(said, dot_ids=ids), "dot: hi")
        self.assertEqual(message_line(asked, dot_ids=ids), "you: yo")
        self.assertEqual(message_line(said), "user: hi")


class ToolSurfaceTests(unittest.TestCase):
    def test_tool_names(self):
        import pathlib

        text = (pathlib.Path(__file__).resolve().parents[1] / "chatgpt_dot" / "mcp_server.py").read_text()
        names = set(__import__("re").findall(r"^def (dot_\w+)\(", text, __import__("re").M))
        self.assertEqual(
            names,
            {
                "dot_summary",
                "dot_usage",
                "dot_primary",
                "dot_list",
                "dot_get",
                "dot_threads",
                "dot_activity",
                "dot_root_thread",
                "dot_computers",
                "dot_environment_status",
                "dot_automations",
                "dot_email_channel_status",
                "dot_by_thread",
                "dot_messages",
                "dot_send",
            },
        )
        self.assertNotIn("runtime/pause", text)
        self.assertNotIn("/ps/orbit", text)


class CliOutputTests(unittest.TestCase):
    def test_list_does_not_print_token(self):
        dots = [{"id": "dot-1", "display_name": "", "status": "active", "is_paused": False, "aeon_kind": "orbit"}]
        buf = io.StringIO()
        err = io.StringIO()
        with (
            mock.patch("chatgpt_dot.cli.load_auth", return_value=("secret-token-value", "acct")),
            mock.patch("chatgpt_dot.cli.list_dots", return_value=dots),
            mock.patch("sys.stdout", buf),
            mock.patch("sys.stderr", err),
        ):
            code = main(["list"])
        text = buf.getvalue() + err.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("Your dot", text)
        self.assertIn("id=dot-1", text)
        self.assertNotIn("secret-token-value", text)

    def test_json_redacts(self):
        buf = io.StringIO()
        with (
            mock.patch("chatgpt_dot.cli.load_auth", return_value=("secret-token-value", "acct")),
            mock.patch(
                "chatgpt_dot.cli.get_json",
                return_value=(200, {"plan_type": "pro", "access_token": "secret-token-value"}),
            ),
            mock.patch("sys.stdout", buf),
        ):
            code = main(["usage", "--json"])
        text = buf.getvalue()
        self.assertEqual(code, 0)
        self.assertNotIn("secret-token-value", text)
        self.assertIn("***", text)

    def test_bad_auth_exits_2(self):
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            code = main(["--auth", "/no/such/auth.json", "list"])
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err.getvalue())

    def test_auth_equals_form(self):
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            code = main(["--auth=/no/such/auth.json", "list"])
        self.assertEqual(code, 2)

    def test_network_error_exits_3(self):
        import urllib.error

        err = io.StringIO()
        with (
            mock.patch("chatgpt_dot.cli.load_auth", return_value=("tok", "acct")),
            mock.patch(
                "chatgpt_dot.api.urllib.request.urlopen",
                side_effect=urllib.error.URLError("offline"),
            ),
            mock.patch("sys.stderr", err),
        ):
            code = main(["usage"])
        self.assertEqual(code, 3)
        self.assertIn("network error", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_401_tells_user_to_login(self):
        err = io.StringIO()

        def urlopen(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 401, "no", hdrs=None, fp=io.BytesIO(b"{}"))

        with (
            mock.patch("chatgpt_dot.cli.load_auth", return_value=("tok", "acct")),
            mock.patch("chatgpt_dot.api.urllib.request.urlopen", urlopen),
            mock.patch("sys.stderr", err),
        ):
            code = main(["list"])
        self.assertEqual(code, 3)
        self.assertIn("codex login", err.getvalue())

    def test_messages_does_not_create_room(self):
        dots = [{"id": "dot-1", "display_name": "", "messaging_room_id": None}]
        out = io.StringIO()
        with (
            mock.patch("chatgpt_dot.cli.load_auth", return_value=("tok", "acct")),
            mock.patch("chatgpt_dot.cli.resolve_dot", return_value=dots[0]),
            mock.patch("chatgpt_dot.cli.ensure_room", side_effect=AssertionError("posted")),
            mock.patch("sys.stdout", out),
        ):
            code = main(["messages"])
        self.assertEqual(code, 0)
        self.assertIn("no messages yet", out.getvalue())


def _response(status: int, raw: bytes):
    class Response:
        def __init__(self):
            self.status = status

        def read(self):
            return raw

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    return Response()


class LimitTests(unittest.TestCase):
    def test_constant_is_32(self):
        self.assertEqual(MESSAGE_LIMIT_MAX, 32)

    def test_list_messages_rejects_out_of_range(self):
        def urlopen(*args, **kwargs):
            raise AssertionError("network")

        with mock.patch("chatgpt_dot.api.urllib.request.urlopen", urlopen):
            for limit in (0, 33, 50):
                with self.assertRaises(ApiError):
                    list_messages("tok", "acct", "room1", limit)

    def test_cli_limit_exits_2_without_request(self):
        def explode(*args, **kwargs):
            raise AssertionError("called")

        for bad in ("0", "33", "50"):
            err = io.StringIO()
            with (
                mock.patch("chatgpt_dot.cli.load_auth", side_effect=explode),
                mock.patch("chatgpt_dot.api.urllib.request.urlopen", side_effect=explode),
                mock.patch("sys.stderr", err),
            ):
                with self.assertRaises(SystemExit) as ctx:
                    main(["messages", "--limit", bad])
            self.assertEqual(ctx.exception.code, 2)
            self.assertIn("32", err.getvalue())

    def test_422_detail_omits_input_and_url(self):
        body = json.dumps(
            {
                "detail": [
                    {
                        "loc": ["query", "limit"],
                        "msg": "Input should be less than or equal to 32",
                        "input": 33,
                    }
                ],
                "url": "https://chatgpt.com/secret",
            }
        ).encode()

        def urlopen(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 422, "no", hdrs=None, fp=io.BytesIO(body))

        with mock.patch("chatgpt_dot.api.urllib.request.urlopen", urlopen):
            with self.assertRaises(ApiError) as ctx:
                list_messages("tok", "acct", "room1", 32)
        text = str(ctx.exception)
        self.assertIn("query.limit", text)
        self.assertIn("less than or equal to 32", text)
        self.assertNotIn("33", text)
        self.assertNotIn("http", text.lower())
        self.assertNotIn("chatgpt.com", text)


class PageTests(unittest.TestCase):
    def test_before_after_passed_and_cursor_omitted(self):
        captured = {}

        def urlopen(req, timeout=0):
            captured["url"] = req.full_url
            return _response(200, b'{"items":[]}')

        with mock.patch("chatgpt_dot.api.urllib.request.urlopen", urlopen):
            self.assertEqual(list_messages("tok", "acct", "room1", 5, before="m-old", after="m-new"), [])
        self.assertIn("before=m-old", captured["url"])
        self.assertIn("after=m-new", captured["url"])
        self.assertIn("limit=5", captured["url"])
        self.assertNotIn("cursor", captured["url"])


class MessageShapeTests(unittest.TestCase):
    def test_json_shape_with_and_without_room(self):
        empty = {"id": "dot-1", "display_name": "", "messaging_room_id": None}
        out = io.StringIO()
        with (
            mock.patch("chatgpt_dot.cli.load_auth", return_value=("tok", "acct")),
            mock.patch("chatgpt_dot.cli.resolve_dot", return_value=empty),
            mock.patch("sys.stdout", out),
        ):
            code = main(["messages", "--json"])
        self.assertEqual(code, 0)
        without = json.loads(out.getvalue())
        self.assertEqual(without["lines"], [])
        self.assertEqual(without["messages"], [])
        self.assertIn("note", without)
        self.assertIn("name", without)

        items = [
            {
                "id": "new",
                "created_at": "2020-01-02T00:00:00Z",
                "role": "user",
                "account_user_id": "ae",
                "content": {"text": "second"},
            },
            {
                "id": "old",
                "created_at": "2020-01-01T00:00:00Z",
                "role": "user",
                "account_user_id": "me",
                "content": {"text": "first"},
            },
        ]
        dot = {
            "id": "dot-1",
            "display_name": "N",
            "messaging_room_id": "room1",
            "messaging_room_preview": {
                "members": [
                    {"account_user_id": "ae", "aeon_id": "aeon-1"},
                    {"account_user_id": "me", "aeon_id": None},
                ]
            },
        }
        out = io.StringIO()
        with (
            mock.patch("chatgpt_dot.cli.load_auth", return_value=("tok", "acct")),
            mock.patch("chatgpt_dot.cli.resolve_dot", return_value=dot),
            mock.patch("chatgpt_dot.cli.list_messages", return_value=items),
            mock.patch("sys.stdout", out),
        ):
            code = main(["--json", "messages"])
        self.assertEqual(code, 0)
        with_room = json.loads(out.getvalue())
        self.assertEqual([item["id"] for item in with_room["messages"]], ["old", "new"])
        self.assertTrue(with_room["lines"][0].startswith("dot:"))
        self.assertTrue(with_room["lines"][1].startswith("you:"))
        self.assertNotIn("note", with_room)
        for payload in (without, with_room):
            self.assertIsInstance(payload["name"], str)
            self.assertIsInstance(payload["lines"], list)
            self.assertIsInstance(payload["messages"], list)


class RedactKeyTests(unittest.TestCase):
    def test_exact_keys_and_kept_fields(self):
        cleaned = redact(
            {
                "email": "hidden-email",
                "account_id": "hidden-account",
                "user_id": "hidden-user",
                "account_user_id": "keep-user",
                "signaling_url": "hidden-signal",
                "magic_link_url": "hidden-magic",
                "magic_link_share_text": "hidden-share",
                "inspector_url": "hidden-inspector",
                "id": "keep-id",
                "aeon_id": "keep-aeon",
                "created_at": "2020-01-01",
                "content": {"text": "hello"},
                "preview": "hi",
                "display_name": "N",
                "kind": "user",
                "is_attached": True,
                "access_token": "hidden-token",
            }
        )
        for key in (
            "email",
            "account_id",
            "user_id",
            "signaling_url",
            "magic_link_url",
            "magic_link_share_text",
            "inspector_url",
            "access_token",
        ):
            self.assertEqual(cleaned[key], "***")
        self.assertEqual(cleaned["account_user_id"], "keep-user")
        self.assertEqual(cleaned["id"], "keep-id")
        self.assertEqual(cleaned["aeon_id"], "keep-aeon")
        self.assertEqual(cleaned["created_at"], "2020-01-01")
        self.assertEqual(cleaned["content"], {"text": "hello"})
        self.assertEqual(cleaned["preview"], "hi")
        self.assertEqual(cleaned["display_name"], "N")
        self.assertEqual(cleaned["kind"], "user")
        self.assertIs(cleaned["is_attached"], True)
        dumped = json.dumps(cleaned)
        for secret in ("hidden-email", "hidden-account", "hidden-user", "hidden-signal", "hidden-token"):
            self.assertNotIn(secret, dumped)


class RequireDotTests(unittest.TestCase):
    def test_given_id_skips_list_and_404_message(self):
        with (
            mock.patch("chatgpt_dot.api.list_dots", side_effect=AssertionError("listed")),
            mock.patch("chatgpt_dot.api.get_json", return_value=(200, {"id": "dot-1", "display_name": "N"})),
        ):
            dot = require_dot_id("tok", "acct", "dot-1")
        self.assertEqual(dot["id"], "dot-1")

        with mock.patch("chatgpt_dot.api.get_json", return_value=(404, {"detail": {"code": "missing"}})):
            with self.assertRaises(ApiError) as ctx:
                require_dot_id("tok", "acct", "missing")
        self.assertIn("dot id was not found", str(ctx.exception))
        self.assertIn("chatgpt-dot-cli list", str(ctx.exception))

    def test_suffix_skips_list_messages_still_lists(self):
        def get_json(access, account, path, query=None):
            if path.endswith("/threads"):
                return 200, {"items": []}
            return 200, {"id": "dot-1", "display_name": "N"}

        err = io.StringIO()
        with (
            mock.patch("chatgpt_dot.cli.load_auth", return_value=("tok", "acct")),
            mock.patch("chatgpt_dot.api.get_json", side_effect=get_json),
            mock.patch("chatgpt_dot.cli.get_json", side_effect=get_json),
            mock.patch("chatgpt_dot.api.list_dots", side_effect=AssertionError("listed")),
            mock.patch("sys.stderr", err),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            code = main(["threads", "--dot-id", "dot-1"])
        self.assertEqual(code, 0)

        dot = {"id": "dot-1", "display_name": "", "messaging_room_id": None}
        out = io.StringIO()
        with (
            mock.patch("chatgpt_dot.cli.load_auth", return_value=("tok", "acct")),
            mock.patch("chatgpt_dot.api.list_dots", return_value=[dot]),
            mock.patch("chatgpt_dot.cli.require_dot_id", side_effect=AssertionError("direct")),
            mock.patch("sys.stdout", out),
        ):
            code = main(["messages", "--dot-id", "dot-1"])
        self.assertEqual(code, 0)
        self.assertIn("no messages yet", out.getvalue())


class ConcurrencyTests(unittest.TestCase):
    def test_get_many_preserves_order_and_caps_workers(self):
        import threading
        import time

        state = {"now": 0, "max": 0}
        lock = threading.Lock()
        seen = {}

        class Pool:
            def __init__(self, max_workers):
                seen["workers"] = max_workers
                self.pool = threading.Thread  # placeholder to satisfy the type checkers in spirit
                from concurrent.futures import ThreadPoolExecutor

                self._pool = ThreadPoolExecutor(max_workers=max_workers)

            def __enter__(self):
                self._pool.__enter__()
                return self

            def map(self, fn, calls):
                return self._pool.map(fn, calls)

            def __exit__(self, *args):
                return self._pool.__exit__(*args)

        def urlopen(req, timeout=0):
            with lock:
                state["now"] += 1
                state["max"] = max(state["max"], state["now"])
            time.sleep(0.05)
            with lock:
                state["now"] -= 1
            name = req.full_url.rstrip("/").rsplit("/", 1)[-1]
            return _response(200, json.dumps({"name": name}).encode())

        calls = [(f"/tbo/n{i}", None) for i in range(6)]
        with (
            mock.patch("chatgpt_dot.api.urllib.request.urlopen", urlopen),
            mock.patch("chatgpt_dot.api.ThreadPoolExecutor", Pool),
        ):
            results = get_many("tok", "acct", calls, max_workers=8)
        self.assertLessEqual(seen["workers"], 3)
        self.assertLessEqual(state["max"], 3)
        self.assertEqual([payload["name"] for _, payload in results], [f"n{i}" for i in range(6)])


class SummaryTests(unittest.TestCase):
    def test_non_200_exits_3_with_stderr(self):
        def urlopen(req, timeout=0):
            raw = b'{"detail":{"code":"unavailable"}}'
            return _response(500, raw)

        out = io.StringIO()
        err = io.StringIO()
        with (
            mock.patch("chatgpt_dot.cli.load_auth", return_value=("tok", "acct")),
            mock.patch("chatgpt_dot.api.urllib.request.urlopen", urlopen),
            mock.patch("sys.stdout", out),
            mock.patch("sys.stderr", err),
        ):
            code = main(["summary"])
        self.assertEqual(code, 3)
        text = err.getvalue()
        self.assertIn("GET /wham/usage", text)
        self.assertIn("500", text)
        self.assertIn("unavailable", text)
        self.assertNotIn("plan_type=", out.getvalue())
        self.assertNotIn("http", text.lower())

    def test_cloudflare_html_stops_summary(self):
        calls = {"n": 0}

        def urlopen(req, timeout=0):
            calls["n"] += 1
            raise urllib.error.HTTPError(
                req.full_url, 403, "no", hdrs=None, fp=io.BytesIO(b"<html>blocked</html>")
            )

        out = io.StringIO()
        err = io.StringIO()
        with (
            mock.patch("chatgpt_dot.cli.load_auth", return_value=("tok", "acct")),
            mock.patch("chatgpt_dot.api.urllib.request.urlopen", urlopen),
            mock.patch("chatgpt_dot.api.time.sleep"),
            mock.patch("sys.stdout", out),
            mock.patch("sys.stderr", err),
        ):
            code = main(["summary"])
        self.assertEqual(code, 3)
        self.assertIn("not JSON", err.getvalue())
        self.assertIn("Cloudflare", err.getvalue())
        self.assertNotIn("blocked", err.getvalue())
        self.assertNotIn("plan_type=", out.getvalue())
        self.assertEqual(calls["n"], 6)

    def test_no_activity_skips_activity(self):
        urls = []

        def urlopen(req, timeout=0):
            urls.append(req.full_url)
            if req.full_url.endswith("/wham/usage"):
                raw = b'{"plan_type":"plus"}'
            elif req.full_url.endswith("/tbo"):
                raw = (
                    b'{"items":[{"id":"dot-1","display_name":"N","status":"active","is_paused":false}]}'
                )
            elif "/activity" in req.full_url:
                raise AssertionError("activity")
            else:
                raw = b'{"items":[],"computers":[],"data":[],"status":"ready"}'
            return _response(200, raw)

        out = io.StringIO()
        with (
            mock.patch("chatgpt_dot.cli.load_auth", return_value=("tok", "acct")),
            mock.patch("chatgpt_dot.api.urllib.request.urlopen", urlopen),
            mock.patch("sys.stdout", out),
        ):
            code = main(["summary", "--no-activity", "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(urls)
        self.assertFalse(any("/activity" in url for url in urls))
        self.assertTrue(any(url.endswith("/threads") for url in urls))
        data = json.loads(out.getvalue())
        self.assertIn("primary_http", data)
        self.assertEqual(data["dots"][0]["id"], "dot-1")
        self.assertIsNone(data["dots"][0]["activity_http"])

    def test_activity_is_submitted_first(self):
        batches = []

        def fake_get_many(access, account, calls, max_workers=3):
            self.assertLessEqual(max_workers, 3)
            batches.append(calls)
            rows = []
            for path, query in calls:
                self.assertNotIn("cursor", query or {})
                if path == "/wham/usage":
                    rows.append((200, {"plan_type": "plus"}))
                elif path == "/tbo/primary":
                    rows.append((200, {}))
                elif path == "/tbo":
                    rows.append(
                        (
                            200,
                            {
                                "items": [
                                    {
                                        "id": "dot-1",
                                        "display_name": "N",
                                        "status": "active",
                                        "is_paused": False,
                                        "messaging_room_id": "room-1",
                                    }
                                ]
                            },
                        )
                    )
                elif path.endswith("/activity"):
                    rows.append((200, {"data": [1]}))
                elif path.endswith("/messages"):
                    self.assertEqual(query, {"limit": "5"})
                    rows.append((200, {"items": []}))
                elif path.endswith("/environment/status"):
                    rows.append((200, {"status": "ready"}))
                elif path.endswith("/computers"):
                    rows.append((200, {"computers": []}))
                elif path.endswith("/channels/email"):
                    rows.append((403, {"detail": {"code": "ineligible"}}))
                else:
                    rows.append((200, {"items": []}))
            return rows

        out = io.StringIO()
        err = io.StringIO()
        with (
            mock.patch("chatgpt_dot.cli.load_auth", return_value=("tok", "acct")),
            mock.patch("chatgpt_dot.cli.get_many", side_effect=fake_get_many),
            mock.patch("sys.stdout", out),
            mock.patch("sys.stderr", err),
        ):
            code = main(["summary", "--json"])
        self.assertEqual(code, 0, err.getvalue())
        self.assertTrue(batches[1][0][0].endswith("/activity"))
        self.assertTrue(batches[1][1][0].endswith("/threads"))
        data = json.loads(out.getvalue())
        self.assertEqual(data["dots"][0]["activity"], 1)
        self.assertEqual(data["primary_http"], 200)


class ProbeTests(unittest.TestCase):
    def test_probe_json(self):
        def urlopen(req, timeout=0):
            if req.full_url.endswith("/wham/usage"):
                raw = b'{"plan_type":"plus"}'
            elif req.full_url.endswith("/tbo"):
                raw = b'{"items":[]}'
            else:
                raw = b"{}"
            return _response(200, raw)

        out = io.StringIO()
        with (
            mock.patch("chatgpt_dot.cli.load_auth", return_value=("tok", "acct")),
            mock.patch("chatgpt_dot.api.urllib.request.urlopen", urlopen),
            mock.patch("sys.stdout", out),
        ):
            code = main(["probe", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["usage_http"], 200)
        self.assertEqual(data["plan_type"], "plus")
        self.assertIsInstance(data["dots"], list)
        self.assertIn("primary_http", data)


class SendAndArgsTests(unittest.TestCase):
    def test_send_text_has_no_role(self):
        dot = {"id": "dot-1", "display_name": "N"}
        out = io.StringIO()
        with (
            mock.patch("chatgpt_dot.cli.load_auth", return_value=("tok", "acct")),
            mock.patch("chatgpt_dot.cli.resolve_dot", return_value=dot),
            mock.patch("chatgpt_dot.cli.ensure_room", return_value="room1"),
            mock.patch("chatgpt_dot.cli.send_message", return_value={"id": "m1", "role": "user"}),
            mock.patch("sys.stdout", out),
        ):
            code = main(["send", "hello"])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().strip(), "sent to N")
        self.assertNotIn("role=", out.getvalue())

    def test_send_double_dash_json_is_literal_text(self):
        seen = {}

        def fake_send(access, account, room, text):
            seen["text"] = text
            return {"id": "m1", "role": "user"}

        out = io.StringIO()
        with (
            mock.patch("chatgpt_dot.cli.load_auth", return_value=("tok", "acct")),
            mock.patch("chatgpt_dot.cli.resolve_dot", return_value={"id": "dot-1", "display_name": "N"}),
            mock.patch("chatgpt_dot.cli.ensure_room", return_value="room1"),
            mock.patch("chatgpt_dot.cli.send_message", side_effect=fake_send),
            mock.patch("sys.stdout", out),
        ):
            code = main(["send", "--", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(seen["text"], "--json")
        self.assertNotIn("role=", out.getvalue())
        self.assertFalse(out.getvalue().lstrip().startswith("{"))

    def test_auth_without_value(self):
        err = io.StringIO()
        with (
            mock.patch("chatgpt_dot.cli.load_auth", side_effect=AssertionError("auth")),
            mock.patch("sys.stderr", err),
        ):
            with self.assertRaises(SystemExit) as ctx:
                main(["--auth"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("chatgpt-dot-cli: error: --auth requires a path", err.getvalue())

    def test_no_subcommand_exits_2_without_api(self):
        out = io.StringIO()
        with (
            mock.patch("chatgpt_dot.cli.load_auth", side_effect=AssertionError("auth")),
            mock.patch("chatgpt_dot.api.urllib.request.urlopen", side_effect=AssertionError("network")),
            mock.patch("sys.stdout", out),
        ):
            code = main([])
        self.assertEqual(code, 2)
        self.assertIn("command is required", out.getvalue())

    def test_version_matches_package(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            with self.assertRaises(SystemExit) as ctx:
                main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn(__version__, out.getvalue())
        self.assertIn("0.2.2", out.getvalue())

    def test_unicode_body_exits_3(self):
        def urlopen(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 500, "no", hdrs=None, fp=io.BytesIO(b"\xff\xfe"))

        err = io.StringIO()
        with (
            mock.patch("chatgpt_dot.cli.load_auth", return_value=("tok", "acct")),
            mock.patch("chatgpt_dot.api.urllib.request.urlopen", urlopen),
            mock.patch("sys.stderr", err),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            code = main(["usage"])
        self.assertEqual(code, 3)
        self.assertNotIn("Traceback", err.getvalue())
        self.assertIn("GET /wham/usage", err.getvalue())


class SpeakerLabelTests(unittest.TestCase):
    def test_empty_sender_set_is_unknown(self):
        said = {"role": "assistant", "account_user_id": "x", "content": {"text": "hi"}}
        self.assertEqual(message_line(said, dot_ids=set()), "unknown: hi")
        self.assertNotIn("assistant", message_line(said, dot_ids=set()))

        dot = {
            "id": "dot-1",
            "display_name": "N",
            "messaging_room_id": "room1",
            "messaging_room_preview": {"members": [{"account_user_id": "x", "aeon_id": None}]},
        }
        out = io.StringIO()
        err = io.StringIO()
        with (
            mock.patch("chatgpt_dot.cli.load_auth", return_value=("tok", "acct")),
            mock.patch("chatgpt_dot.cli.resolve_dot", return_value=dot),
            mock.patch("chatgpt_dot.cli.list_messages", return_value=[said, dict(said, content={"text": "again"})]),
            mock.patch("sys.stdout", out),
            mock.patch("sys.stderr", err),
        ):
            code = main(["messages"])
        self.assertEqual(code, 0)
        self.assertIn("unknown: hi", out.getvalue())
        self.assertEqual(err.getvalue().count("messaging_room_preview has no aeon member"), 1)
        self.assertNotIn("assistant:", out.getvalue())


class McpTests(unittest.TestCase):
    def test_tools_raise_api_error(self):
        from chatgpt_dot.mcp_server import clear_dots_cache, dot_list, dot_messages

        clear_dots_cache()
        with (
            mock.patch("chatgpt_dot.mcp_server.load_auth", return_value=("tok", "acct")),
            mock.patch("chatgpt_dot.mcp_server.list_dots", side_effect=ApiError("GET /tbo failed (500)", 500)),
        ):
            with self.assertRaises(ApiError):
                dot_list()
        with mock.patch("chatgpt_dot.mcp_server.list_messages", side_effect=AssertionError("network")):
            with self.assertRaises(ApiError):
                dot_messages(limit=33)
        clear_dots_cache()

    def test_missing_mcp_message(self):
        import pathlib

        text = (pathlib.Path(__file__).resolve().parents[1] / "chatgpt_dot" / "mcp_server.py").read_text()
        self.assertIn("[mcp]", text)
        self.assertIn("@v0.2.2", text)
        self.assertIn(
            'uv tool install --force "chatgpt-dot-cli[mcp] @ git+https://gitlab.com/aa22396584/chatgpt-dot-cli.git@v0.2.2"',
            text,
        )
        self.assertIn('uv pip install -e ".[mcp]"', text)
        self.assertIn("SystemExit(1)", text)

    def test_readonly_hints(self):
        from chatgpt_dot.mcp_server import mcp

        if mcp is None:
            self.skipTest("mcp not installed")
        tools = mcp._tool_manager.list_tools()
        self.assertEqual(len(tools), 15)
        hints = {}
        for tool in tools:
            ann = tool.annotations
            hints[tool.name] = ann["readOnlyHint"] if isinstance(ann, dict) else ann.readOnlyHint
        self.assertEqual(sum(1 for value in hints.values() if value is True), 14)
        self.assertIs(hints["dot_send"], False)

    def test_list_cache_cleared_after_send(self):
        from chatgpt_dot.mcp_server import clear_dots_cache, dot_list, dot_send

        clear_dots_cache()
        calls = {"n": 0}

        def fake_list(access, account):
            calls["n"] += 1
            return [{"id": "dot-1", "display_name": "N", "messaging_room_id": "room1"}]

        with (
            mock.patch("chatgpt_dot.mcp_server.load_auth", return_value=("tok", "acct")),
            mock.patch("chatgpt_dot.mcp_server.list_dots", side_effect=fake_list),
        ):
            dot_list()
            dot_list()
            self.assertEqual(calls["n"], 1)
            with (
                mock.patch("chatgpt_dot.mcp_server.ensure_room", return_value="room1"),
                mock.patch("chatgpt_dot.mcp_server.send_message", return_value={"id": "m1"}),
            ):
                dot_send("hi")
            dot_list()
        self.assertEqual(calls["n"], 2)
        clear_dots_cache()

    def test_empty_room_and_missing_thread_are_notes(self):
        from chatgpt_dot.mcp_server import clear_dots_cache, dot_by_thread, dot_messages

        clear_dots_cache()
        dot = {"id": "dot-1", "display_name": "N", "messaging_room_id": None, "active_root_thread_id": None}
        with (
            mock.patch("chatgpt_dot.mcp_server.load_auth", return_value=("tok", "acct")),
            mock.patch("chatgpt_dot.mcp_server.list_dots", return_value=[dot]),
        ):
            messages = json.loads(dot_messages())
            thread = json.loads(dot_by_thread())
        self.assertEqual(messages["messages"], [])
        self.assertIn("note", messages)
        self.assertEqual(thread["note"], "dot has no active root thread")
        clear_dots_cache()


class DocsDriftTests(unittest.TestCase):
    def test_every_subcommand_is_documented(self):
        from chatgpt_dot.cli import build_parser

        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        skill = (root / "skills" / "chatgpt-dot-cli" / "SKILL.md").read_text(encoding="utf-8")
        parser = build_parser()
        names = []
        for action in parser._actions:
            if not isinstance(action, argparse._SubParsersAction):
                continue
            for choice in action._choices_actions:
                self.assertTrue(choice.help and str(choice.help).strip(), choice.dest)
                names.append(choice.dest)
            self._assert_flag_help(action.choices.values())
        self.assertGreaterEqual(len(names), 16)
        for name in names:
            pattern = rf"(?<![\w-]){re.escape(name)}(?![\w-])"
            self.assertRegex(readme, pattern, name)
            self.assertRegex(skill, pattern, name)
        for url in (
            "https://gitlab.com/aa22396584/trinity-cli",
            "https://gitlab.com/aa22396584/chatgpt-dot-cli",
            "https://gitlab.com/aa22396584/grok-bot-cli",
            "https://gitlab.com/aa22396584/muse-web-cli",
        ):
            self.assertIn(url, readme)
        self.assertNotIn("github.com/ImL1s", readme)

    def _assert_flag_help(self, parsers) -> None:
        for parser in parsers:
            for action in parser._actions:
                if not action.option_strings and action.dest == "help":
                    continue
                if action.help is argparse.SUPPRESS:
                    continue
                self.assertTrue(action.help and str(action.help).strip(), action.dest)


if __name__ == "__main__":
    unittest.main()
