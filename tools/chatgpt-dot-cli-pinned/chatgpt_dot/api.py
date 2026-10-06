"""The only HTTP client. GET for status, POST only to talk to a dot."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from chatgpt_dot.platform import codex_auth_path, posix_mode

BASE = "https://chatgpt.com/backend-api"
MESSAGE_LIMIT_MAX = 32
_ID = r"[A-Za-z0-9][A-Za-z0-9._~-]{0,199}"
_DOT_SUFFIXES = (
    "threads",
    "activity",
    "root-thread",
    "computers",
    "environment/status",
    "automations",
    "channels/email",
)

GET_PATTERNS = (
    re.compile(r"^/wham/usage$"),
    re.compile(r"^/tbo$"),
    re.compile(r"^/tbo/primary$"),
    re.compile(rf"^/tbo/{_ID}$"),
    re.compile(rf"^/tbo/{_ID}/(?:{'|'.join(_DOT_SUFFIXES)})$"),
    re.compile(rf"^/tbo/by-thread/{_ID}$"),
    re.compile(rf"^/messaging/rooms/{_ID}/messages$"),
)
POST_PATTERNS = (
    re.compile(rf"^/messaging/rooms/{_ID}/messages$"),
    re.compile(rf"^/tbo/{_ID}/messaging-room$"),
)
SECRET_KEY = re.compile(
    r"token|secret|key|cookie|authorization|password|session",
    re.IGNORECASE,
)
# Exact names. account_user_id stays visible; it is not account_id or user_id.
EXACT_SECRET_KEYS = frozenset(
    {
        "email",
        "account_id",
        "user_id",
        "signaling_url",
        "magic_link_url",
        "magic_link_share_text",
        "inspector_url",
    }
)


class AuthError(Exception):
    pass


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def load_auth(path: str | Path | None = None) -> tuple[str, str]:
    target = codex_auth_path() if path is None else Path(path).expanduser()
    posix_mode(target)
    try:
        with target.open(encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except OSError as exc:
        if path is not None:
            where = "the --auth file"
        elif os.environ.get("CODEX_HOME"):
            where = "auth.json in CODEX_HOME"
        else:
            where = "~/.codex/auth.json"
        raise AuthError(
            f"cannot read auth file: {exc.strerror} ({where}). "
            "Run `codex login` with a ChatGPT account, or pass --auth PATH."
        ) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AuthError("auth file is not valid json") from exc
    if not isinstance(data, dict) or data.get("auth_mode") != "chatgpt":
        raise AuthError("auth file is not a chatgpt login")
    tokens = data.get("tokens") or {}
    access = tokens.get("access_token")
    account = tokens.get("account_id")
    if not isinstance(access, str) or not access:
        raise AuthError("auth file has no access token")
    if not isinstance(account, str) or not account:
        raise AuthError("auth file has no account id")
    return access, account


def assert_allowed(method: str, path: str) -> None:
    if method == "GET":
        patterns = GET_PATTERNS
    elif method == "POST":
        patterns = POST_PATTERNS
    else:
        raise ApiError(f"method not allowed: {method}")
    if not any(pattern.fullmatch(path) for pattern in patterns):
        raise ApiError(f"path not allowed: {method} {path}")


def redact(value: object) -> object:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            name = str(key)
            if name in EXACT_SECRET_KEYS or SECRET_KEY.search(name):
                cleaned[key] = "***"
            else:
                cleaned[key] = redact(item)
        return cleaned
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def detail_summary(payload: object) -> str:
    """Short API detail. Dict contributes `code`; a list contributes `loc` and `msg` only."""
    if not isinstance(payload, dict):
        return ""
    detail = payload.get("detail")
    if isinstance(detail, dict):
        code = detail.get("code")
        return code if isinstance(code, str) else ""
    if isinstance(detail, list):
        parts: list[str] = []
        for item in detail:
            if not isinstance(item, dict):
                continue
            loc = item.get("loc")
            msg = item.get("msg")
            loc_text = ".".join(str(part) for part in loc) if isinstance(loc, list) else ""
            msg_text = msg if isinstance(msg, str) else ""
            text = " ".join(piece for piece in (loc_text, msg_text) if piece)
            if text:
                parts.append(text)
        return "; ".join(parts)
    return ""


def _error(prefix: str, status: int, payload: object) -> ApiError:
    extra = detail_summary(payload)
    message = f"{prefix} ({status})"
    if extra:
        message = f"{message}: {extra}"
    return ApiError(message, status)


def request_json(
    access: str,
    account: str,
    path: str,
    method: str = "GET",
    body: dict | None = None,
    query: dict | None = None,
) -> tuple[int, object | None]:
    assert_allowed(method, path)
    url = BASE + path
    if query:
        url = url + "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
    payload = None if body is None else json.dumps(body).encode("utf-8")
    last: tuple[int, object | None] = (0, None)
    for attempt in range(2):
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bearer {access}",
                "ChatGPT-Account-Id": account,
                "Accept": "application/json",
                "User-Agent": "Codex Desktop",
                "originator": "Codex Desktop",
                "OAI-Product-Sku": "CODEX",
                **({"Content-Type": "application/json"} if payload is not None else {}),
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status = resp.status
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ApiError(f"network error: {getattr(exc, 'reason', exc)}") from exc
        if not raw:
            last = (status, None)
        else:
            try:
                last = (status, json.loads(raw.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                last = (status, None)
        if status == 401:
            raise ApiError(
                "ChatGPT login expired (401). Open Codex or run `codex login`, then retry.",
                401,
            )
        if status in (403, 429, 503) and last[1] is None and attempt == 0:
            time.sleep(1)
            continue
        return last
    return last


def get_json(access: str, account: str, path: str, query: dict | None = None) -> tuple[int, object | None]:
    return request_json(access, account, path, "GET", query=query)


def get_many(
    access: str,
    account: str,
    calls: list[tuple[str, dict | None]],
    *,
    max_workers: int = 3,
) -> list[tuple[int, object | None]]:
    """Run GETs concurrently. Results stay in call order. At most 3 workers.

    Each call still retries at most once inside request_json. Callers that want
    a slow read to start first should put that call first; this function does
    not reorder.
    """
    if not calls:
        return []
    if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
        raise ApiError("max_workers must be a positive integer")
    workers = min(3, max_workers, len(calls))

    def one(call: tuple[str, dict | None]) -> tuple[int, object | None]:
        path, query = call
        return get_json(access, account, path, query)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, calls))


def post_json(access: str, account: str, path: str, body: dict) -> tuple[int, object | None]:
    return request_json(access, account, path, "POST", body=body)


def list_dots(access: str, account: str) -> list[dict]:
    status, payload = get_json(access, account, "/tbo")
    if status != 200 or not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise _error("GET /tbo failed", status, payload)
    return [item for item in payload["items"] if isinstance(item, dict) and item.get("id")]


def resolve_dot(access: str, account: str, dot_id: str | None) -> dict:
    dots = list_dots(access, account)
    if dot_id:
        for item in dots:
            if item.get("id") == dot_id:
                return item
        raise ApiError("dot id was not found; run `chatgpt-dot-cli list` and pass --dot-id")
    if len(dots) == 1:
        return dots[0]
    if not dots:
        raise ApiError("no dot on this account")
    raise ApiError("more than one dot; run `chatgpt-dot-cli list` and pass --dot-id <id>")


def require_dot_id(access: str, account: str, dot_id: str | None) -> dict:
    """Resolve a dot. A given id is fetched directly and does not call list_dots."""
    if not dot_id:
        return resolve_dot(access, account, None)
    status, payload = get_json(access, account, f"/tbo/{dot_id}")
    if status == 404:
        raise ApiError("dot id was not found; run `chatgpt-dot-cli list` and pass --dot-id")
    if status != 200 or not isinstance(payload, dict) or not payload.get("id"):
        raise _error("GET /tbo/{id} failed", status, payload)
    return payload


def ensure_room(access: str, account: str, dot: dict) -> str:
    room = dot.get("messaging_room_id")
    if isinstance(room, str) and room:
        return room
    status, payload = post_json(access, account, f"/tbo/{dot['id']}/messaging-room", {})
    if not isinstance(payload, dict):
        raise ApiError(f"could not open messaging room ({status})", status)
    room = payload.get("messaging_room_id")
    if not isinstance(room, str) or not room:
        raise ApiError(f"messaging room missing ({status})", status)
    return room


def list_messages(
    access: str,
    account: str,
    room_id: str,
    limit: int = 20,
    before: str | None = None,
    after: str | None = None,
) -> list[dict]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MESSAGE_LIMIT_MAX:
        raise ApiError(f"limit must be from 1 to {MESSAGE_LIMIT_MAX}")
    query: dict[str, str] = {"limit": str(limit)}
    if before is not None:
        query["before"] = before
    if after is not None:
        query["after"] = after
    status, payload = get_json(
        access,
        account,
        f"/messaging/rooms/{room_id}/messages",
        query=query,
    )
    if status != 200 or not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise _error("GET messages failed", status, payload)
    return [item for item in payload["items"] if isinstance(item, dict)]


def send_message(access: str, account: str, room_id: str, text: str) -> dict:
    if not text.strip():
        raise ApiError("message text is empty")
    request_id = str(uuid.uuid4())
    status, payload = post_json(
        access,
        account,
        f"/messaging/rooms/{room_id}/messages",
        {
            "content": {"text": text, "attachments": []},
            "request_id": request_id,
            "idempotency_token": request_id,
        },
    )
    if status not in (200, 201) or not isinstance(payload, dict):
        raise _error("send failed", status, payload)
    return payload
