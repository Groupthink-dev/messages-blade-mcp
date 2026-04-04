"""Token-efficient output formatters for Messages Blade MCP server.

All formatters return compact strings optimised for LLM consumption:
- One line per message/chat/contact
- Pipe-delimited fields
- Null-field omission
- Truncation for long message text
"""

from __future__ import annotations

from typing import Any

from messages_blade_mcp.models import scrub_pii

# Maximum text length in formatted output
_MAX_TEXT_LEN = 200


def truncate(text: str, max_len: int = _MAX_TEXT_LEN) -> str:
    """Truncate text with ellipsis if it exceeds max_len."""
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _safe(value: Any) -> str:
    """Convert a value to string, returning empty string for None."""
    if value is None:
        return ""
    return str(value)


# ---------------------------------------------------------------------------
# Chat formatters
# ---------------------------------------------------------------------------


def format_chat(chat: dict[str, Any]) -> str:
    """Format a single chat as a pipe-delimited line.

    Format: chat_id | handle_or_name | service | participants | last=timestamp | unread=N
    """
    parts = [str(chat.get("chat_id", "?"))]

    name = chat.get("display_name") or chat.get("chat_identifier") or "unknown"
    parts.append(name)

    service = chat.get("service_name", "")
    if service:
        parts.append(service)

    participants = chat.get("participants", "")
    if participants:
        parts.append(f"participants={participants}")

    last_date = chat.get("last_message_date")
    if last_date:
        parts.append(f"last={last_date}")

    unread = chat.get("unread_count", 0)
    if unread and unread > 0:
        parts.append(f"unread={unread}")

    return " | ".join(parts)


def format_chats(chats: list[dict[str, Any]]) -> str:
    """Format a list of chats."""
    if not chats:
        return "(no conversations found)"
    return "\n".join(format_chat(c) for c in chats)


# ---------------------------------------------------------------------------
# Message formatters
# ---------------------------------------------------------------------------


def format_message(msg: dict[str, Any]) -> str:
    """Format a single message as a pipe-delimited line.

    Format: message_id | timestamp | sender | text_content
    """
    parts = [str(msg.get("message_id", "?"))]

    date = msg.get("date", "")
    if date:
        parts.append(date)

    is_from_me = msg.get("is_from_me", False)
    sender = "me" if is_from_me else _safe(msg.get("handle_id", "unknown"))
    parts.append(sender)

    text = truncate(msg.get("text", ""))
    if text:
        parts.append(text)
    elif msg.get("has_attachments"):
        parts.append("[attachment]")
    elif msg.get("associated_message_type") and msg["associated_message_type"] != 0:
        parts.append("[reaction/tapback]")
    else:
        parts.append("[empty]")

    return " | ".join(parts)


def format_messages(messages: list[dict[str, Any]]) -> str:
    """Format a list of messages."""
    if not messages:
        return "(no messages found)"
    return "\n".join(format_message(m) for m in messages)


def format_recent_message(msg: dict[str, Any]) -> str:
    """Format a recent message with chat context.

    Format: chat_id | chat_name | timestamp | sender | text
    """
    parts = [str(msg.get("chat_id", "?"))]

    chat_name = msg.get("chat_name", "")
    if chat_name:
        parts.append(chat_name)

    date = msg.get("date", "")
    if date:
        parts.append(date)

    is_from_me = msg.get("is_from_me", False)
    sender = "me" if is_from_me else _safe(msg.get("handle_id", "unknown"))
    parts.append(sender)

    text = truncate(msg.get("text", ""))
    if text:
        parts.append(text)
    else:
        parts.append("[empty]")

    return " | ".join(parts)


def format_recent_messages(messages: list[dict[str, Any]]) -> str:
    """Format a list of recent messages with chat context."""
    if not messages:
        return "(no recent messages)"
    return "\n".join(format_recent_message(m) for m in messages)


# ---------------------------------------------------------------------------
# Search result formatters
# ---------------------------------------------------------------------------


def format_search_result(result: dict[str, Any]) -> str:
    """Format a search result with excerpt.

    Format: chat_id | handle | date | ...excerpt...
    """
    parts = [str(result.get("chat_id", "?"))]

    chat_name = result.get("chat_name", "")
    if chat_name:
        parts.append(chat_name)

    handle = result.get("handle_id", "")
    if handle:
        parts.append(handle)

    date = result.get("date", "")
    if date:
        parts.append(date)

    text = truncate(result.get("text", ""), 150)
    if text:
        parts.append(text)

    return " | ".join(parts)


def format_search_results(results: list[dict[str, Any]]) -> str:
    """Format search results."""
    if not results:
        return "(no matches found)"
    return "\n".join(format_search_result(r) for r in results)


# ---------------------------------------------------------------------------
# Contact formatters
# ---------------------------------------------------------------------------


def format_contact(handle: dict[str, Any]) -> str:
    """Format a contact/handle as a pipe-delimited line.

    Format: handle_id | service | messages=N | last=timestamp
    """
    parts = [_safe(handle.get("handle_id", "?"))]

    service = handle.get("service", "")
    if service:
        parts.append(service)

    msg_count = handle.get("message_count", 0)
    parts.append(f"messages={msg_count}")

    last_date = handle.get("last_message_date")
    if last_date:
        parts.append(f"last={last_date}")

    return " | ".join(parts)


def format_contacts(contacts: list[dict[str, Any]]) -> str:
    """Format a list of contacts/handles."""
    if not contacts:
        return "(no contacts found)"
    return "\n".join(format_contact(c) for c in contacts)


def format_contact_detail(contact: dict[str, Any]) -> str:
    """Format a contact detail view with send/receive counts."""
    parts = [_safe(contact.get("handle_id", "?"))]

    service = contact.get("service", "")
    if service:
        parts.append(service)

    parts.append(f"total={contact.get('message_count', 0)}")
    parts.append(f"sent={contact.get('sent_count', 0)}")
    parts.append(f"received={contact.get('received_count', 0)}")

    first = contact.get("first_message_date")
    if first:
        parts.append(f"first={first}")

    last = contact.get("last_message_date")
    if last:
        parts.append(f"last={last}")

    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Attachment formatters
# ---------------------------------------------------------------------------


def format_attachment(att: dict[str, Any]) -> str:
    """Format an attachment as a pipe-delimited line.

    Format: attachment_id | filename | mime_type | size
    """
    parts = [str(att.get("attachment_id", "?"))]

    filename = att.get("transfer_name") or att.get("filename") or "unknown"
    parts.append(filename)

    mime = att.get("mime_type", "")
    if mime:
        parts.append(mime)

    size = att.get("total_bytes")
    if size is not None:
        parts.append(_format_size(size))

    date = att.get("date")
    if date:
        parts.append(date)

    return " | ".join(parts)


def format_attachments(attachments: list[dict[str, Any]]) -> str:
    """Format a list of attachments."""
    if not attachments:
        return "(no attachments found)"
    return "\n".join(format_attachment(a) for a in attachments)


def _format_size(size_bytes: int) -> str:
    """Format a byte count as human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f}GB"


# ---------------------------------------------------------------------------
# Stats formatter
# ---------------------------------------------------------------------------


def format_stats(stats: dict[str, Any]) -> str:
    """Format aggregate statistics.

    Format: chats=N | messages=N | handles=N | attachments=N | first=date | last=date | top=handle(count)
    """
    parts = [
        f"chats={stats.get('chat_count', 0)}",
        f"messages={stats.get('message_count', 0)}",
        f"handles={stats.get('handle_count', 0)}",
        f"attachments={stats.get('attachment_count', 0)}",
    ]

    first = stats.get("first_message_date")
    if first:
        parts.append(f"first={first}")

    last = stats.get("last_message_date")
    if last:
        parts.append(f"last={last}")

    top = stats.get("top_contacts", [])
    if top:
        top_strs = [f"{t['handle_id']}({t['message_count']})" for t in top[:3]]
        parts.append(f"top={', '.join(top_strs)}")

    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Unread formatter
# ---------------------------------------------------------------------------


def format_unread(unread_list: list[dict[str, Any]]) -> str:
    """Format unread message counts per chat."""
    if not unread_list:
        return "(no unread messages)"
    lines = []
    for item in unread_list:
        name = item.get("display_name", "unknown")
        count = item.get("unread_count", 0)
        last = item.get("last_unread_date", "")
        line = f"{name} | unread={count}"
        if last:
            line += f" | last={last}"
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Info formatter
# ---------------------------------------------------------------------------


def format_info(info: dict[str, Any]) -> str:
    """Format system info output."""
    parts = []
    for key, value in info.items():
        if value is not None:
            parts.append(f"{key}={value}")
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Error formatter (PII-safe)
# ---------------------------------------------------------------------------


def format_error(error: Exception) -> str:
    """Format an error message with PII scrubbing."""
    return f"Error: {scrub_pii(str(error))}"
