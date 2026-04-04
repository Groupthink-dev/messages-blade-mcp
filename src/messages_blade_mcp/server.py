"""Apple Messages (iMessage) Blade MCP Server — conversations, search, contacts, attachments, send.

Reads the Messages chat.db SQLite database (read-only) for message history,
conversations, contacts, and attachments. Sends messages via AppleScript bridge.
Token-efficient pipe-delimited output. Write operations gated by
MESSAGES_WRITE_ENABLED. All sends require explicit confirm=true.
"""

from __future__ import annotations

import asyncio
import logging
import platform
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from messages_blade_mcp.applescript import send_file as applescript_send_file
from messages_blade_mcp.applescript import send_message as applescript_send_message
from messages_blade_mcp.applescript import start_group as applescript_start_group
from messages_blade_mcp.contacts import resolve_contact_name
from messages_blade_mcp.database import MessagesDB
from messages_blade_mcp.formatters import (
    format_attachments,
    format_chats,
    format_contact_detail,
    format_contacts,
    format_error,
    format_info,
    format_messages,
    format_recent_messages,
    format_search_results,
    format_stats,
    format_unread,
)
from messages_blade_mcp.models import (
    FDAError,
    MessagesError,
    check_confirm_gate,
    check_write_gate,
    is_write_enabled,
    resolve_config,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "MessagesBlade",
    instructions=(
        "Apple Messages (iMessage/SMS) operations on macOS. "
        "Read conversations, search message history, list contacts/attachments, "
        "and send messages. Requires Full Disk Access for reads. "
        "Write operations require MESSAGES_WRITE_ENABLED=true AND confirm=true."
    ),
)

# Lazy-initialized database
_db: MessagesDB | None = None
_config_cache: dict[str, object] | None = None


def _get_db() -> MessagesDB:
    """Get or create the MessagesDB singleton."""
    global _db  # noqa: PLW0603
    if _db is None:
        config = resolve_config()
        _db = MessagesDB(db_path=config.db_path)
    return _db


def _get_config_dict() -> dict[str, object]:
    """Get resolved config as a dict for reuse."""
    global _config_cache  # noqa: PLW0603
    if _config_cache is None:
        config = resolve_config()
        _config_cache = {
            "db_path": config.db_path,
            "write_enabled": config.write_enabled,
        }
    return _config_cache


# ===========================================================================
# READ TOOLS (12)
# ===========================================================================


@mcp.tool()
async def messages_info() -> str:
    """System info: macOS version, FDA status, write gate, Messages.app status, chat.db path."""
    config = resolve_config()
    info: dict[str, object] = {}

    # macOS version
    mac_ver = platform.mac_ver()[0]
    info["macos"] = mac_ver or "unknown"

    # Platform check
    if platform.system() != "Darwin":
        info["error"] = "This MCP requires macOS"
        return format_info(info)

    # chat.db path and FDA status
    info["db_path"] = config.db_path
    db_exists = Path(config.db_path).exists()
    info["db_exists"] = db_exists

    if db_exists:
        try:
            db = _get_db()
            stats = await asyncio.to_thread(db.get_stats)
            info["fda"] = "granted"
            info["messages"] = stats.get("message_count", 0)
            info["chats"] = stats.get("chat_count", 0)
        except FDAError:
            info["fda"] = "NOT_GRANTED"
            info["error"] = "Full Disk Access required"
        except MessagesError as e:
            info["fda"] = "error"
            info["error"] = str(e)
    else:
        info["fda"] = "unknown"
        info["error"] = "chat.db not found at expected path"

    # Write gate status
    info["write_gate"] = "enabled" if is_write_enabled() else "disabled"

    return format_info(info)


@mcp.tool()
async def messages_chats(
    limit: Annotated[int, Field(description="Max conversations to return")] = 50,
) -> str:
    """List all conversations (1:1 and group). Shows handle, service, type, last message time, unread count."""
    try:
        db = _get_db()
        chats = await asyncio.to_thread(db.get_chats, limit)
        return format_chats(chats)
    except (FDAError, MessagesError) as e:
        return format_error(e)


@mcp.tool()
async def messages_chat(
    chat_id: Annotated[int | None, Field(description="Chat ROWID")] = None,
    handle: Annotated[str | None, Field(description="Phone number or email to find")] = None,
) -> str:
    """Get a specific conversation by chat ID or contact identifier (phone/email)."""
    if chat_id is None and handle is None:
        return "Error: Provide either chat_id or handle"
    try:
        db = _get_db()
        chat = await asyncio.to_thread(db.get_chat, chat_id, handle)
        if not chat:
            return "(conversation not found)"

        # Try to resolve contact name
        if handle:
            name = await asyncio.to_thread(resolve_contact_name, handle)
            if name:
                chat["contact_name"] = name

        from messages_blade_mcp.formatters import format_chat

        return format_chat(chat)
    except (FDAError, MessagesError) as e:
        return format_error(e)


@mcp.tool()
async def messages_messages(
    chat_id: Annotated[int, Field(description="Chat ROWID")],
    limit: Annotated[int, Field(description="Max messages to return")] = 50,
    before: Annotated[int | None, Field(description="Paginate: messages before this ROWID")] = None,
) -> str:
    """Get messages from a conversation. Paginate with before=ROWID for older messages."""
    try:
        db = _get_db()
        messages = await asyncio.to_thread(db.get_messages, chat_id, limit, before)
        return format_messages(messages)
    except (FDAError, MessagesError) as e:
        return format_error(e)


@mcp.tool()
async def messages_recent(
    limit: Annotated[int, Field(description="Max messages to return")] = 20,
    since: Annotated[str | None, Field(description="ISO timestamp — only messages after this time")] = None,
) -> str:
    """Recent messages across all conversations. Optional since=ISO-timestamp filter."""
    try:
        db = _get_db()
        messages = await asyncio.to_thread(db.get_recent_messages, limit, since)
        return format_recent_messages(messages)
    except (FDAError, MessagesError) as e:
        return format_error(e)


@mcp.tool()
async def messages_search(
    query: Annotated[str, Field(description="Text to search for in messages")],
    limit: Annotated[int, Field(description="Max results")] = 20,
) -> str:
    """Full-text search across all messages. Returns excerpts with chat context."""
    if not query or not query.strip():
        return "Error: Search query cannot be empty"
    try:
        db = _get_db()
        results = await asyncio.to_thread(db.search_messages, query, limit)
        return format_search_results(results)
    except (FDAError, MessagesError) as e:
        return format_error(e)


@mcp.tool()
async def messages_contacts(
    limit: Annotated[int, Field(description="Max contacts to return")] = 100,
) -> str:
    """List known contacts/handles (phone numbers, emails, iCloud accounts)."""
    try:
        db = _get_db()
        contacts = await asyncio.to_thread(db.get_contacts, limit)
        return format_contacts(contacts)
    except (FDAError, MessagesError) as e:
        return format_error(e)


@mcp.tool()
async def messages_contact(
    handle: Annotated[str, Field(description="Phone number or email to look up")],
) -> str:
    """Get details for a specific handle including message count and last interaction."""
    try:
        db = _get_db()
        contact = await asyncio.to_thread(db.get_contact, handle)
        if not contact:
            return "(contact not found)"

        # Try to resolve display name
        name = await asyncio.to_thread(resolve_contact_name, handle)
        if name:
            contact["display_name"] = name

        return format_contact_detail(contact)
    except (FDAError, MessagesError) as e:
        return format_error(e)


@mcp.tool()
async def messages_attachments(
    chat_id: Annotated[int, Field(description="Chat ROWID")],
    limit: Annotated[int, Field(description="Max attachments to return")] = 20,
) -> str:
    """List attachments from a conversation. Returns metadata only (path, MIME, size). Never reads file content."""
    try:
        db = _get_db()
        attachments = await asyncio.to_thread(db.get_attachments, chat_id, limit)
        return format_attachments(attachments)
    except (FDAError, MessagesError) as e:
        return format_error(e)


@mcp.tool()
async def messages_attachment_info(
    attachment_id: Annotated[int, Field(description="Attachment ROWID")],
) -> str:
    """Get detailed metadata for a specific attachment. Never reads file content."""
    try:
        db = _get_db()
        from messages_blade_mcp.formatters import format_attachment

        info = await asyncio.to_thread(db.get_attachment_info, attachment_id)
        if not info:
            return "(attachment not found)"
        return format_attachment(info)
    except (FDAError, MessagesError) as e:
        return format_error(e)


@mcp.tool()
async def messages_stats() -> str:
    """Aggregate statistics: total chats, messages, date range, top contacts."""
    try:
        db = _get_db()
        stats = await asyncio.to_thread(db.get_stats)
        return format_stats(stats)
    except (FDAError, MessagesError) as e:
        return format_error(e)


@mcp.tool()
async def messages_unread() -> str:
    """Unread message count per conversation."""
    try:
        db = _get_db()
        unread = await asyncio.to_thread(db.get_unread)
        return format_unread(unread)
    except (FDAError, MessagesError) as e:
        return format_error(e)


# ===========================================================================
# WRITE TOOLS (3) — ALL require write gate AND confirm gate
# ===========================================================================


@mcp.tool()
async def messages_send(
    recipient: Annotated[str, Field(description="Phone number or email address")],
    text: Annotated[str, Field(description="Message text to send")],
    service: Annotated[str, Field(description="iMessage or SMS")] = "iMessage",
    confirm: Annotated[bool, Field(description="Must be true — messages cannot be unsent")] = False,
) -> str:
    """Send a text message. Requires MESSAGES_WRITE_ENABLED=true AND confirm=true."""
    config = resolve_config()
    gate = check_write_gate(config)
    if gate:
        return gate
    conf = check_confirm_gate(confirm, "Sending a message")
    if conf:
        return conf

    try:
        success = await asyncio.to_thread(applescript_send_message, recipient, text, service)
        if success:
            return f"Sent to {recipient} via {service}"
        return "Error: Message send returned false"
    except (MessagesError, Exception) as e:
        return format_error(e)


@mcp.tool()
async def messages_send_file(
    recipient: Annotated[str, Field(description="Phone number or email address")],
    file_path: Annotated[str, Field(description="Absolute path to file to send")],
    service: Annotated[str, Field(description="iMessage or SMS")] = "iMessage",
    confirm: Annotated[bool, Field(description="Must be true — files cannot be unsent")] = False,
) -> str:
    """Send a file attachment. Requires MESSAGES_WRITE_ENABLED=true AND confirm=true."""
    config = resolve_config()
    gate = check_write_gate(config)
    if gate:
        return gate
    conf = check_confirm_gate(confirm, "Sending a file")
    if conf:
        return conf

    try:
        success = await asyncio.to_thread(applescript_send_file, recipient, file_path, service)
        if success:
            return f"Sent file to {recipient} via {service}"
        return "Error: File send returned false"
    except (MessagesError, Exception) as e:
        return format_error(e)


@mcp.tool()
async def messages_start_group(
    recipients: Annotated[list[str], Field(description="List of phone numbers or emails (minimum 2)")],
    text: Annotated[str, Field(description="Initial message text")],
    confirm: Annotated[bool, Field(description="Must be true — group creation cannot be undone")] = False,
) -> str:
    """Start a new group conversation. Requires MESSAGES_WRITE_ENABLED=true AND confirm=true."""
    config = resolve_config()
    gate = check_write_gate(config)
    if gate:
        return gate
    conf = check_confirm_gate(confirm, "Starting a group conversation")
    if conf:
        return conf

    try:
        success = await asyncio.to_thread(applescript_start_group, recipients, text)
        if success:
            return f"Group started with {len(recipients)} recipients"
        return "Error: Group creation returned false"
    except (MessagesError, Exception) as e:
        return format_error(e)


# ===========================================================================
# Entry point
# ===========================================================================


def main() -> None:
    """Run the MCP server."""
    import os

    transport = os.environ.get("MESSAGES_MCP_TRANSPORT", "stdio")
    if transport == "http":
        host = os.environ.get("MESSAGES_MCP_HOST", "127.0.0.1")
        port = int(os.environ.get("MESSAGES_MCP_PORT", "8770"))
        mcp.run(transport="http", host=host, port=port)
    else:
        mcp.run(transport="stdio")
