"""Local stdio MCP server. Optional. Read tools plus send, nothing else."""

from __future__ import annotations

import sys
import threading
import time

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None  # type: ignore[misc, assignment]

from chatgpt_dot.api import (
    MESSAGE_LIMIT_MAX,
    ApiError,
    detail_summary,
    ensure_room,
    get_json,
    get_many,
    list_dots,
    list_messages,
    load_auth,
    require_dot_id,
    send_message,
)
from chatgpt_dot.platform import configure_stdio
from chatgpt_dot.summaries import aeon_member_note, dot_name, dot_sender_ids, dumps, message_line, oldest_first

MCP_INSTALL = 'uv tool install --force "chatgpt-dot-cli[mcp] @ git+https://gitlab.com/aa22396584/chatgpt-dot-cli.git@v0.2.2"'
MCP_EDITABLE = 'uv pip install -e ".[mcp]"'
MISSING_MCP = (
    "MCP is optional. Install it with:\n"
    f"  {MCP_INSTALL}\n"
    "From a checkout:\n"
    f"  {MCP_EDITABLE}\n"
)

mcp = FastMCP("chatgpt-dot-cli") if FastMCP is not None else None
_READ = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
_SEND = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}
_CACHE_TTL = 15.0
_cache_lock = threading.Lock()
_dots_cache: tuple[float, str, list[dict]] | None = None


def clear_dots_cache() -> None:
    global _dots_cache
    with _cache_lock:
        _dots_cache = None


def _remember_dots(account: str, dots: list[dict]) -> None:
    global _dots_cache
    with _cache_lock:
        _dots_cache = (time.monotonic(), account, dots)


def _cached_list_dots(access: str, account: str) -> list[dict]:
    now = time.monotonic()
    with _cache_lock:
        cached = _dots_cache
    if cached is not None and cached[1] == account and now - cached[0] < _CACHE_TTL:
        return cached[2]
    dots = list_dots(access, account)
    _remember_dots(account, dots)
    return dots


def _listed_dot(access: str, account: str, dot_id: str | None) -> dict:
    dots = _cached_list_dots(access, account)
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


def _tool(annotations: dict):
    def wrap(fn):
        if mcp is None:
            return fn
        return mcp.tool(annotations=annotations)(fn)

    return wrap


def _dots_from_tbo(status: int, payload: object) -> list[dict]:
    if status in (403, 429, 503) and payload is None:
        raise ApiError("response body was not JSON (likely Cloudflare)", status)
    if status != 200 or not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        extra = detail_summary(payload)
        message = f"GET /tbo failed ({status})"
        if extra:
            message = f"{message}: {extra}"
        raise ApiError(message, status)
    return [item for item in payload["items"] if isinstance(item, dict) and item.get("id")]


def _message_page(status: int, payload: object) -> list[dict]:
    if status in (403, 429, 503) and payload is None:
        raise ApiError("response body was not JSON (likely Cloudflare)", status)
    if status != 200 or not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        extra = detail_summary(payload)
        message = f"GET messages failed ({status})"
        if extra:
            message = f"{message}: {extra}"
        raise ApiError(message, status)
    return [item for item in payload["items"] if isinstance(item, dict)]


@_tool(_READ)
def dot_summary() -> str:
    """Plan type, each dot's status, and the latest messages."""
    access, account = load_auth()
    usage_pair, primary_pair, tbo_pair = get_many(
        access,
        account,
        [("/wham/usage", None), ("/tbo/primary", None), ("/tbo", None)],
    )
    for status, payload in (usage_pair, primary_pair, tbo_pair):
        if status in (403, 429, 503) and payload is None:
            raise ApiError("response body was not JSON (likely Cloudflare)", status)
    status, usage = usage_pair
    _, primary = primary_pair
    dots = _dots_from_tbo(*tbo_pair)
    _remember_dots(account, dots)
    msg_jobs = []
    for index, item in enumerate(dots):
        room = item.get("messaging_room_id")
        if isinstance(room, str) and room:
            msg_jobs.append((index, f"/messaging/rooms/{room}/messages", {"limit": "5"}))
    msg_results = get_many(access, account, [(path, query) for _, path, query in msg_jobs]) if msg_jobs else []
    by_index = {job[0]: result for job, result in zip(msg_jobs, msg_results)}
    rows = []
    noted = False
    for index, item in enumerate(dots):
        recent = _message_page(*by_index[index]) if index in by_index else []
        ordered = oldest_first(recent)
        sender_ids = dot_sender_ids(item)
        note = aeon_member_note(sender_ids, len(ordered))
        if note and not noted:
            print(note, file=sys.stderr)
            noted = True
        rows.append(
            {
                "name": dot_name(item),
                "status": item.get("status"),
                "paused": item.get("is_paused"),
                "kind": item.get("aeon_kind"),
                "id": item.get("id"),
                "recent": [message_line(message, 160, sender_ids) for message in reversed(ordered)],
            }
        )
    plan = usage.get("plan_type") if isinstance(usage, dict) else None
    return dumps({"usage_http": status, "plan_type": plan, "primary": primary, "dots": rows})


@_tool(_READ)
def dot_usage() -> str:
    """ChatGPT plan usage from GET /wham/usage."""
    access, account = load_auth()
    status, payload = get_json(access, account, "/wham/usage")
    return dumps({"status": status, "body": payload})


@_tool(_READ)
def dot_primary() -> str:
    """Current dot selection from GET /tbo/primary."""
    access, account = load_auth()
    status, payload = get_json(access, account, "/tbo/primary")
    return dumps({"status": status, "body": payload})


@_tool(_READ)
def dot_list() -> str:
    """List dots. The id field is the dot id; aeon_id is not."""
    access, account = load_auth()
    return dumps(_cached_list_dots(access, account))


def _one(path_suffix: str, dot_id: str | None) -> str:
    access, account = load_auth()
    if dot_id:
        dot = require_dot_id(access, account, dot_id)
    else:
        dot = _listed_dot(access, account, None)
    status, payload = get_json(access, account, f"/tbo/{dot['id']}{path_suffix}")
    return dumps({"status": status, "name": dot_name(dot), "body": payload})


@_tool(_READ)
def dot_get(dot_id: str | None = None) -> str:
    """Fetch one dot. Omit dot_id when the account has a single dot."""
    return _one("", dot_id)


@_tool(_READ)
def dot_threads(dot_id: str | None = None) -> str:
    """List the dot's threads."""
    return _one("/threads", dot_id)


@_tool(_READ)
def dot_activity(dot_id: str | None = None) -> str:
    """Recent activity for the dot."""
    return _one("/activity", dot_id)


@_tool(_READ)
def dot_root_thread(dot_id: str | None = None) -> str:
    """The dot's root thread id."""
    return _one("/root-thread", dot_id)


@_tool(_READ)
def dot_computers(dot_id: str | None = None) -> str:
    """Computers attached to the dot."""
    return _one("/computers", dot_id)


@_tool(_READ)
def dot_environment_status(dot_id: str | None = None) -> str:
    """Cloud environment status for the dot."""
    return _one("/environment/status", dot_id)


@_tool(_READ)
def dot_automations(dot_id: str | None = None) -> str:
    """Automations on the dot."""
    return _one("/automations", dot_id)


@_tool(_READ)
def dot_email_channel_status(dot_id: str | None = None) -> str:
    """Email channel status. 403 ineligible means the account cannot use email."""
    return _one("/channels/email", dot_id)


@_tool(_READ)
def dot_by_thread(thread_id: str | None = None, dot_id: str | None = None) -> str:
    """Resolve a dot from a thread id. Defaults to the dot's active root thread."""
    access, account = load_auth()
    if not thread_id:
        dot = require_dot_id(access, account, dot_id) if dot_id else _listed_dot(access, account, None)
        thread_id = dot.get("active_root_thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            return dumps({"note": "dot has no active root thread"})
    status, payload = get_json(access, account, f"/tbo/by-thread/{thread_id}")
    return dumps({"status": status, "body": payload})


@_tool(_READ)
def dot_messages(
    dot_id: str | None = None,
    limit: int = 20,
    before: str | None = None,
    after: str | None = None,
) -> str:
    """Recent messages. limit is 1..32 (default 20).

    before and after take a message id and return one page. cursor is not sent.
    messages are oldest to newest; lines are newest first.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MESSAGE_LIMIT_MAX:
        raise ApiError(f"limit must be from 1 to {MESSAGE_LIMIT_MAX}")
    access, account = load_auth()
    dot = _listed_dot(access, account, dot_id or None)
    name = dot_name(dot)
    room = dot.get("messaging_room_id")
    if not isinstance(room, str) or not room:
        return dumps(
            {
                "name": name,
                "lines": [],
                "messages": [],
                "note": "no messages yet (send creates the room)",
            }
        )
    items = list_messages(access, account, room, limit, before=before or None, after=after or None)
    ordered = oldest_first(items)
    sender_ids = dot_sender_ids(dot)
    note = aeon_member_note(sender_ids, len(ordered))
    if note:
        print(note, file=sys.stderr)
    return dumps(
        {
            "name": name,
            "lines": [message_line(item, dot_ids=sender_ids) for item in reversed(ordered)],
            "messages": ordered,
        }
    )


@_tool(_SEND)
def dot_send(text: str, dot_id: str | None = None) -> str:
    """Send a text message to the dot and return the created message."""
    access, account = load_auth()
    try:
        dot = _listed_dot(access, account, dot_id or None)
        room = ensure_room(access, account, dot)
        payload = send_message(access, account, room, text)
        return dumps({"name": dot_name(dot), "message": payload})
    finally:
        clear_dots_cache()


def main() -> None:
    configure_stdio()
    if mcp is None:
        sys.stderr.write(MISSING_MCP)
        raise SystemExit(1)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
