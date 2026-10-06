"""Command line for reading and messaging Your dot."""

from __future__ import annotations

import argparse
import sys

from chatgpt_dot import __version__
from chatgpt_dot.api import (
    MESSAGE_LIMIT_MAX,
    ApiError,
    AuthError,
    detail_summary,
    ensure_room,
    get_json,
    get_many,
    list_dots,
    list_messages,
    load_auth,
    require_dot_id,
    resolve_dot,
    send_message,
)
from chatgpt_dot.platform import configure_stdio
from chatgpt_dot.summaries import aeon_member_note, dot_name, dot_sender_ids, dumps, field_lines, message_line, oldest_first

# Re-export the suffix tuple the probe prints. Defined here to avoid a cycle.
READS_PER_DOT = (
    "/threads",
    "/activity",
    "/root-thread",
    "/computers",
    "/environment/status",
    "/automations",
    "/channels/email",
)

_CLOUDFLARE = "response body was not JSON (likely Cloudflare)"
_SUMMARY_READS = (
    ("threads", "/threads"),
    ("activity", "/activity"),
    ("computers", "/computers"),
    ("automations", "/automations"),
    ("environment", "/environment/status"),
    ("email", "/channels/email"),
)


def _detail_code(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    detail = payload.get("detail")
    if isinstance(detail, dict) and isinstance(detail.get("code"), str):
        return detail["code"]
    return None


def _html_block(status: int, payload: object) -> bool:
    return status in (403, 429, 503) and payload is None


def _failure_line(label: str, status: int, payload: object) -> str:
    extra = detail_summary(payload)
    if extra:
        return f"{label} {status} {extra}"
    return f"{label} {status}"


def _finish(label: str, status: int, payload: object, *, ok: bool = False) -> int:
    if ok or status == 200:
        return 0
    if _html_block(status, payload):
        print(_CLOUDFLARE, file=sys.stderr)
        return 3
    print(_failure_line(label, status, payload), file=sys.stderr)
    return 3


def _limit_arg(value: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(
            f"limit must be an integer from 1 to {MESSAGE_LIMIT_MAX}"
        ) from None
    if isinstance(number, bool) or not 1 <= number <= MESSAGE_LIMIT_MAX:
        raise argparse.ArgumentTypeError(f"limit must be an integer from 1 to {MESSAGE_LIMIT_MAX}")
    return number


def _note_speakers(dot_ids: set[str] | None, count: int, noted: list[bool]) -> None:
    note = aeon_member_note(dot_ids, count)
    if note and not noted[0]:
        print(note, file=sys.stderr)
        noted[0] = True


def cmd_usage(access: str, account: str, as_json: bool) -> int:
    status, payload = get_json(access, account, "/wham/usage")
    if as_json:
        print(dumps({"status": status, "body": payload}))
    else:
        plan = payload.get("plan_type") if isinstance(payload, dict) else None
        print(f"{status} GET /wham/usage plan_type={plan}")
    return _finish("GET /wham/usage", status, payload)


def cmd_primary(access: str, account: str, as_json: bool) -> int:
    status, payload = get_json(access, account, "/tbo/primary")
    if as_json:
        print(dumps({"status": status, "body": payload}))
    else:
        print(f"{status} GET /tbo/primary")
        for line in field_lines(payload)[:24]:
            print(f"  {line}")
    return _finish("GET /tbo/primary", status, payload)


def cmd_list(access: str, account: str, as_json: bool) -> int:
    dots = list_dots(access, account)
    if as_json:
        print(dumps(dots))
        return 0
    for item in dots:
        print(
            f"id={item.get('id')} {dot_name(item)} status={item.get('status')} "
            f"paused={item.get('is_paused')} kind={item.get('aeon_kind')}"
        )
    print(f"{len(dots)} dot(s)")
    return 0


def cmd_show(access: str, account: str, dot_id: str | None, as_json: bool) -> int:
    dot = resolve_dot(access, account, dot_id)
    status, payload = get_json(access, account, f"/tbo/{dot['id']}")
    if as_json:
        print(dumps({"status": status, "body": payload}))
    else:
        print(f"{status} {dot_name(dot)}")
        for line in field_lines(payload)[:24]:
            print(f"  {line}")
    return _finish("GET /tbo/{id}", status, payload)


def _suffix(access: str, account: str, dot_id: str | None, suffix: str, as_json: bool) -> int:
    dot = require_dot_id(access, account, dot_id)
    status, payload = get_json(access, account, f"/tbo/{dot['id']}{suffix}")
    info = status == 403 and suffix == "/channels/email" and _detail_code(payload) == "ineligible"
    if as_json:
        print(dumps({"status": status, "body": payload, "info": info}))
    else:
        print(f"{status} GET /tbo/{{id}}{suffix}")
        if info:
            print("  email channel ineligible")
        for line in field_lines(payload)[:24]:
            print(f"  {line}")
    return _finish(f"GET /tbo/{{id}}{suffix}", status, payload, ok=info)


def cmd_messages(
    access: str,
    account: str,
    dot_id: str | None,
    limit: int,
    as_json: bool,
    before: str | None = None,
    after: str | None = None,
) -> int:
    dot = resolve_dot(access, account, dot_id)
    name = dot_name(dot)
    room = dot.get("messaging_room_id")
    if not isinstance(room, str) or not room:
        if as_json:
            print(
                dumps(
                    {
                        "name": name,
                        "lines": [],
                        "messages": [],
                        "note": "no messages yet (send creates the room)",
                    }
                )
            )
        else:
            print("no messages yet (send creates the room)")
        return 0
    items = list_messages(access, account, room, limit, before=before, after=after)
    ordered = oldest_first(items)
    sender_ids = dot_sender_ids(dot)
    _note_speakers(sender_ids, len(ordered), [False])
    lines = [message_line(item, dot_ids=sender_ids) for item in reversed(ordered)]
    if as_json:
        print(dumps({"name": name, "lines": lines, "messages": ordered}))
        return 0
    print(f"{name} messages={len(ordered)}")
    for line in lines:
        print(line)
    return 0


def cmd_send(access: str, account: str, dot_id: str | None, text: str, as_json: bool) -> int:
    dot = resolve_dot(access, account, dot_id)
    room = ensure_room(access, account, dot)
    payload = send_message(access, account, room, text)
    if as_json:
        print(dumps(payload))
    else:
        print(f"sent to {dot_name(dot)}")
    return 0


def cmd_by_thread(access: str, account: str, thread_id: str | None, dot_id: str | None, as_json: bool) -> int:
    if not thread_id:
        dot = resolve_dot(access, account, dot_id)
        thread_id = dot.get("active_root_thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            raise ApiError("dot has no active root thread")
    status, payload = get_json(access, account, f"/tbo/by-thread/{thread_id}")
    if as_json:
        print(dumps({"status": status, "body": payload}))
    else:
        print(f"{status} GET /tbo/by-thread/{{thread_id}}")
        for line in field_lines(payload)[:24]:
            print(f"  {line}")
    return _finish("GET /tbo/by-thread/{thread_id}", status, payload)


def _activity_first(jobs: list, marker: str) -> list:
    ordered = sorted(enumerate(jobs), key=lambda pair: (pair[1][1] != marker, pair[0]))
    return [job for _, job in ordered]


def _message_items(payload: object) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return []
    return [item for item in payload["items"] if isinstance(item, dict)]


def _count_list(payload: object, key: str) -> int | None:
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return len(payload[key])
    return None


def cmd_summary(access: str, account: str, as_json: bool, include_activity: bool = True) -> int:
    top_calls = [("/wham/usage", None), ("/tbo/primary", None), ("/tbo", None)]
    top = get_many(access, account, top_calls)
    if any(_html_block(status, payload) for status, payload in top):
        print(_CLOUDFLARE, file=sys.stderr)
        return 3

    problems: list[str] = []
    for label, (status, payload) in zip(("GET /wham/usage", "GET /tbo/primary", "GET /tbo"), top):
        if status != 200:
            problems.append(_failure_line(label, status, payload))
    usage_status, usage = top[0]
    primary_status, primary = top[1]
    tbo_status, tbo = top[2]
    dots: list[dict] = []
    if tbo_status == 200 and isinstance(tbo, dict) and isinstance(tbo.get("items"), list):
        dots = [item for item in tbo["items"] if isinstance(item, dict) and item.get("id")]

    reads = [item for item in _SUMMARY_READS if include_activity or item[0] != "activity"]
    jobs: list[tuple[int, str, str, dict | None, str]] = []
    if not problems:
        for index, item in enumerate(dots):
            for kind, suffix in reads:
                jobs.append((index, kind, f"/tbo/{item['id']}{suffix}", None, f"GET /tbo/{{id}}{suffix}"))
            room = item.get("messaging_room_id")
            if isinstance(room, str) and room:
                jobs.append(
                    (
                        index,
                        "messages",
                        f"/messaging/rooms/{room}/messages",
                        {"limit": "5"},
                        "GET /messaging/rooms/{id}/messages",
                    )
                )
        jobs = _activity_first(jobs, "activity")
        fetched = get_many(access, account, [(job[2], job[3]) for job in jobs]) if jobs else []
        if any(_html_block(status, payload) for status, payload in fetched):
            print(_CLOUDFLARE, file=sys.stderr)
            return 3
    else:
        fetched = []

    by_dot: dict[int, dict[str, tuple[int, object | None]]] = {}
    for job, result in zip(jobs, fetched):
        by_dot.setdefault(job[0], {})[job[1]] = result
        status, payload = result
        if job[1] == "email" and status == 403 and _detail_code(payload) == "ineligible":
            continue
        if status != 200:
            problems.append(_failure_line(job[4], status, payload))

    plan = usage.get("plan_type") if isinstance(usage, dict) else None
    rows = []
    noted = [False]
    for index, item in enumerate(dots):
        got = by_dot.get(index, {})

        def take(kind: str, got: dict = got) -> tuple[int | None, object | None]:
            return got.get(kind, (None, None))

        threads_status, threads = take("threads")
        activity_status, activity = take("activity")
        computers_status, computers = take("computers")
        auto_status, automations = take("automations")
        env_status, environment = take("environment")
        email_status, email = take("email")
        _, msg_payload = take("messages")
        recent = _message_items(msg_payload) if "messages" in got else []
        ordered = oldest_first(recent)
        sender_ids = dot_sender_ids(item)
        _note_speakers(sender_ids, len(ordered), noted)
        rows.append(
            {
                "id": item.get("id"),
                "name": dot_name(item),
                "status": item.get("status"),
                "paused": item.get("is_paused"),
                "kind": item.get("aeon_kind"),
                "threads": _count_list(threads, "items"),
                "threads_http": threads_status,
                "activity": _count_list(activity, "data"),
                "activity_http": activity_status,
                "computers": _count_list(computers, "computers"),
                "computers_http": computers_status,
                "automations": _count_list(automations, "items"),
                "automations_http": auto_status,
                "environment": environment.get("status") if isinstance(environment, dict) else None,
                "environment_http": env_status,
                "email": _detail_code(email) or email_status,
                "recent": [message_line(message, 120, sender_ids) for message in reversed(ordered)],
            }
        )

    body = {
        "plan_type": plan,
        "usage_http": usage_status,
        "primary_http": primary_status,
        "primary": primary,
        "dots": rows,
    }
    if problems:
        for line in problems:
            print(line, file=sys.stderr)
        if as_json:
            print(dumps(body))
        return 3
    if as_json:
        print(dumps(body))
        return 0
    print(f"plan_type={plan}")
    selection = primary.get("selection") if isinstance(primary, dict) else None
    available = selection.get("available") if isinstance(selection, dict) else None
    print(f"primary available={available}")
    for row in rows:
        activity = "skipped" if not include_activity else row["activity"]
        print(
            f"{row['name']} status={row['status']} paused={row['paused']} kind={row['kind']} "
            f"threads={row['threads']} activity={activity} computers={row['computers']} "
            f"automations={row['automations']} environment={row['environment']} email={row['email']}"
        )
        for line in row["recent"]:
            print(f"  {line}")
    return 0


def cmd_probe(access: str, account: str, as_json: bool) -> int:
    top = get_many(access, account, [("/wham/usage", None), ("/tbo/primary", None), ("/tbo", None)])
    usage_status, usage = top[0]
    primary_status, primary = top[1]
    tbo_status, tbo = top[2]
    plan = usage.get("plan_type") if isinstance(usage, dict) else None
    dots: list[dict] = []
    if tbo_status == 200 and isinstance(tbo, dict) and isinstance(tbo.get("items"), list):
        dots = [item for item in tbo["items"] if isinstance(item, dict) and item.get("id")]

    jobs: list[tuple[int, str, str, dict | None]] = []
    for index, item in enumerate(dots):
        jobs.append((index, "detail", f"/tbo/{item['id']}", None))
        for suffix in READS_PER_DOT:
            jobs.append((index, suffix, f"/tbo/{item['id']}{suffix}", None))
        thread_id = item.get("active_root_thread_id")
        if isinstance(thread_id, str) and thread_id:
            jobs.append((index, "by-thread", f"/tbo/by-thread/{thread_id}", None))
        room = item.get("messaging_room_id")
        if isinstance(room, str) and room:
            jobs.append((index, "messages", f"/messaging/rooms/{room}/messages", {"limit": "5"}))
    jobs = _activity_first(jobs, "/activity")
    fetched = get_many(access, account, [(job[2], job[3]) for job in jobs]) if jobs else []
    by_dot: dict[int, dict[str, tuple[int, object | None]]] = {}
    for job, result in zip(jobs, fetched):
        by_dot.setdefault(job[0], {})[job[1]] = result

    lines = [
        f"{usage_status} GET /wham/usage plan_type={plan}",
        f"{primary_status} GET /tbo/primary",
    ]
    lines.extend(f"  {line}" for line in field_lines(primary)[:24])
    lines.append(f"{tbo_status} GET /tbo items={len(dots)}")
    dot_rows = []
    for index, item in enumerate(dots):
        got = by_dot.get(index, {})
        lines.append(
            "dot"
            f" name={dot_name(item)!r}"
            f" status={item.get('status')}"
            f" paused={item.get('is_paused')}"
            f" kind={item.get('aeon_kind')}"
        )
        reads = []
        detail_status, detail = got.get("detail", (0, None))
        lines.append(f"{detail_status} GET /tbo/{{id}}")
        lines.extend(f"  {line}" for line in field_lines(detail)[:24])
        reads.append({"path": "GET /tbo/{id}", "status": detail_status})
        for suffix in READS_PER_DOT:
            code, payload = got.get(suffix, (0, None))
            lines.append(f"{code} GET /tbo/{{id}}{suffix}")
            lines.extend(f"  {line}" for line in field_lines(payload)[:24])
            reads.append({"path": f"GET /tbo/{{id}}{suffix}", "status": code})
        if "by-thread" in got:
            code, payload = got["by-thread"]
            lines.append(f"{code} GET /tbo/by-thread/{{thread_id}}")
            lines.extend(f"  {line}" for line in field_lines(payload)[:24])
            reads.append({"path": "GET /tbo/by-thread/{thread_id}", "status": code})
        if "messages" in got:
            code, payload = got["messages"]
            count = len(payload.get("items", [])) if isinstance(payload, dict) and isinstance(payload.get("items"), list) else 0
            lines.append(f"{code} GET /messaging/rooms/{{id}}/messages items={count}")
            reads.append({"path": "GET /messaging/rooms/{id}/messages", "status": code, "items": count})
        dot_rows.append(
            {
                "name": dot_name(item),
                "status": item.get("status"),
                "paused": item.get("is_paused"),
                "kind": item.get("aeon_kind"),
                "reads": reads,
            }
        )
    if as_json:
        print(
            dumps(
                {
                    "usage_http": usage_status,
                    "plan_type": plan,
                    "primary_http": primary_status,
                    "list_http": tbo_status,
                    "dots": dot_rows,
                }
            )
        )
    else:
        print("\n".join(lines))
    return 0


def _parser(sub: argparse._SubParsersAction, name: str, text: str, example: str) -> argparse.ArgumentParser:
    return sub.add_parser(
        name,
        help=text,
        epilog=f"example: {example}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def _add_dot_id(parser: argparse.ArgumentParser, positional: bool = True) -> None:
    parser.add_argument(
        "--dot-id",
        dest="dot_id_opt",
        default=None,
        help="dot id from `list` (preferred). Default: the only dot on the account",
    )
    if positional:
        parser.add_argument(
            "dot_id",
            nargs="?",
            default=None,
            help="dot id. Default: the only dot. Prefer --dot-id",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read and message your ChatGPT dot. MCP is optional; this CLI is enough.",
        epilog=(
            "examples:\n"
            "  chatgpt-dot-cli --version\n"
            "  chatgpt-dot-cli list\n"
            "  chatgpt-dot-cli messages --limit 10\n"
            "  chatgpt-dot-cli messages --before MESSAGE_ID --limit 5\n"
            "  chatgpt-dot-cli summary --no-activity\n"
            "  chatgpt-dot-cli send -- \"-text starting with a dash\"\n"
            "  chatgpt-dot-cli threads --dot-id ID\n"
            "A command is required. With no command the CLI prints this help and exits 2.\n"
            "--json may appear before or after the command, but not after a standalone --.\n"
            "--json defaults to off. --auth defaults to .codex/auth.json in the home directory.\n"
            "--limit defaults to 20 and must be from 1 to 32.\n"
            "--before and --after each take one message id and return a single page.\n"
            "The CLI does not send cursor and does not follow further pages."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--auth",
        default=None,
        help="path to the Codex auth file. Default: .codex/auth.json in the home directory",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print redacted JSON (default: off). Before or after the command, not after a standalone --",
    )
    sub = parser.add_subparsers(dest="command")

    summary = _parser(sub, "summary", "plan type, dot status, and recent messages", "chatgpt-dot-cli summary --no-activity")
    summary.add_argument(
        "--no-activity",
        action="store_true",
        help="skip the activity read (default: activity is fetched)",
    )
    _parser(sub, "usage", "ChatGPT plan usage", "chatgpt-dot-cli usage")
    _parser(sub, "primary", "which dot is currently selected", "chatgpt-dot-cli primary")
    _parser(sub, "list", "list dots with ids", "chatgpt-dot-cli list")
    _parser(sub, "probe", "status codes and field names for every read", "chatgpt-dot-cli probe")

    show = _parser(sub, "show", "one dot's profile", "chatgpt-dot-cli show")
    _add_dot_id(show)

    helps = {
        "threads": "threads on the dot",
        "activity": "recent activity",
        "root-thread": "root thread id",
        "computers": "computers the dot can use",
        "env": "cloud environment status",
        "automations": "automations on the dot",
        "email-status": "email channel; ineligible is normal",
    }
    for name, text in helps.items():
        cmd = _parser(sub, name, text, f"chatgpt-dot-cli {name}")
        _add_dot_id(cmd)

    by_thread = _parser(sub, "by-thread", "find the dot for a thread id", "chatgpt-dot-cli by-thread")
    by_thread.add_argument(
        "thread_id",
        nargs="?",
        default=None,
        help="thread id. Default: the dot's active root thread",
    )
    by_thread.add_argument(
        "--dot-id",
        dest="dot_id_opt",
        default=None,
        help="dot id, used only when the thread id is omitted. Default: the only dot",
    )

    messages = _parser(sub, "messages", "recent messages; does not create a room", "chatgpt-dot-cli messages --limit 10")
    messages.add_argument(
        "--dot-id",
        dest="dot_id_opt",
        default=None,
        help="dot id from `list` (preferred). Default: the only dot on the account",
    )
    messages.add_argument(
        "--limit",
        type=_limit_arg,
        default=20,
        help=f"how many messages to fetch (default: 20, range 1..{MESSAGE_LIMIT_MAX})",
    )
    messages.add_argument(
        "--before",
        default=None,
        help="one message id; return that older page and stop (default: none)",
    )
    messages.add_argument(
        "--after",
        default=None,
        help="one message id; return that newer page and stop (default: none)",
    )

    send = _parser(sub, "send", "send a text message to the dot", 'chatgpt-dot-cli send -- "hello"')
    send.add_argument("text", help="message text. Put -- before text that starts with a dash")
    send.add_argument(
        "--dot-id",
        dest="dot_id_opt",
        default=None,
        help="dot id from `list`. Default: the only dot on the account",
    )
    return parser


def _picked_dot(args: argparse.Namespace) -> str | None:
    return getattr(args, "dot_id_opt", None) or getattr(args, "dot_id", None)


_SUFFIX = {
    "threads": "/threads",
    "activity": "/activity",
    "root-thread": "/root-thread",
    "computers": "/computers",
    "env": "/environment/status",
    "automations": "/automations",
    "email-status": "/channels/email",
}


def _split_globals(argv: list[str]) -> tuple[list[str], str | None, bool]:
    cleaned: list[str] = []
    auth_path = None
    as_json = False
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == "--":
            cleaned.extend(argv[index:])
            break
        if item == "--json":
            as_json = True
            index += 1
            continue
        if item == "--auth" or item.startswith("--auth="):
            if item.startswith("--auth="):
                auth_path = item.split("=", 1)[1]
                index += 1
                continue
            if index + 1 >= len(argv):
                print("chatgpt-dot-cli: error: --auth requires a path", file=sys.stderr)
                raise SystemExit(2)
            auth_path = argv[index + 1]
            index += 2
            continue
        cleaned.append(item)
        index += 1
    return cleaned, auth_path, as_json


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    parser = build_parser()
    raw = list(sys.argv[1:] if argv is None else argv)
    cleaned, auth_path, as_json = _split_globals(raw)
    args = parser.parse_args(cleaned)
    if not args.command:
        parser.print_help()
        return 2
    try:
        access, account = load_auth(auth_path)
    except AuthError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    dot_id = _picked_dot(args)
    try:
        if args.command == "summary":
            return cmd_summary(access, account, as_json, include_activity=not args.no_activity)
        if args.command == "usage":
            return cmd_usage(access, account, as_json)
        if args.command == "primary":
            return cmd_primary(access, account, as_json)
        if args.command == "list":
            return cmd_list(access, account, as_json)
        if args.command == "show":
            return cmd_show(access, account, dot_id, as_json)
        if args.command == "probe":
            return cmd_probe(access, account, as_json)
        if args.command == "by-thread":
            return cmd_by_thread(access, account, args.thread_id, dot_id, as_json)
        if args.command == "messages":
            return cmd_messages(
                access,
                account,
                dot_id,
                args.limit,
                as_json,
                before=args.before,
                after=args.after,
            )
        if args.command == "send":
            return cmd_send(access, account, dot_id, args.text, as_json)
        if args.command in _SUFFIX:
            return _suffix(access, account, dot_id, _SUFFIX[args.command], as_json)
    except ApiError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    parser.error(f"unknown command {args.command}")
    return 2
