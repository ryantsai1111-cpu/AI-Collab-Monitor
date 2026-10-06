"""Short text views. These never include auth material."""

from __future__ import annotations

from chatgpt_dot.api import redact


def dot_name(item: dict) -> str:
    name = item.get("display_name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return "Your dot"


def field_lines(value: object, prefix: str = "", depth: int = 0) -> list[str]:
    if depth > 2:
        return []
    lines: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(item, dict):
                lines.append(f"{path}: object")
                lines.extend(field_lines(item, path, depth + 1))
            elif isinstance(item, list):
                lines.append(f"{path}: list[{len(item)}]")
                if item and isinstance(item[0], dict):
                    lines.extend(field_lines(item[0], path + "[]", depth + 1))
            else:
                lines.append(f"{path}: {type(item).__name__}")
    return lines


def dot_sender_ids(dot: dict) -> set[str]:
    preview = dot.get("messaging_room_preview")
    members = preview.get("members") if isinstance(preview, dict) else None
    return {
        m["account_user_id"]
        for m in members or []
        if isinstance(m, dict) and m.get("aeon_id") and isinstance(m.get("account_user_id"), str)
    }


def oldest_first(items: list[dict]) -> list[dict]:
    """Raw message objects, oldest to newest. Items without a timestamp stay in API order."""

    def sort_key(pair: tuple[int, dict]) -> tuple:
        index, item = pair
        stamp = item.get("created_at")
        if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
            return (0, float(stamp), index)
        if isinstance(stamp, str):
            return (0, stamp, index)
        return (1, index, index)

    return [item for _, item in sorted(enumerate(items), key=sort_key)]


def message_line(item: dict, limit: int = 240, dot_ids: set[str] | None = None) -> str:
    if dot_ids is None:
        role = item.get("role") or "?"
    elif len(dot_ids) == 0:
        role = "unknown"
    else:
        role = "dot" if item.get("account_user_id") in dot_ids else "you"
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    text = content.get("text") if isinstance(content, dict) else ""
    if not isinstance(text, str):
        text = ""
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return f"{role}: {text}"


def aeon_member_note(dot_ids: set[str] | None, count: int) -> str | None:
    if count and dot_ids is not None and len(dot_ids) == 0:
        return "messaging_room_preview has no aeon member"
    return None


def dumps(value: object) -> str:
    import json

    return json.dumps(redact(value), ensure_ascii=False, indent=2)
