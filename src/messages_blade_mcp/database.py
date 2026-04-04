"""Read-only SQLite interface to Apple Messages chat.db.

Opens the database in read-only mode (``?mode=ro`` URI). All queries are
synchronous (sqlite3 does not support async); callers should use
``asyncio.to_thread()`` to avoid blocking the event loop.

Requires Full Disk Access (FDA) for the terminal emulator on macOS.
"""

from __future__ import annotations

import logging
import platform
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from messages_blade_mcp.models import DEFAULT_DB_PATH, DEFAULT_LIMIT, FDAError, MessagesError
from messages_blade_mcp.typedstream import decode_attributed_body

logger = logging.getLogger(__name__)

# Apple epoch: 2001-01-01T00:00:00Z — Messages stores dates as nanoseconds since this
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)


def apple_timestamp_to_iso(ns: int | None) -> str | None:
    """Convert Apple nanosecond timestamp to ISO 8601 string.

    Messages.app stores dates as nanoseconds since 2001-01-01T00:00:00Z.
    Returns None for NULL or zero timestamps.
    """
    if not ns:
        return None
    try:
        dt = APPLE_EPOCH + timedelta(seconds=ns / 1_000_000_000)
        return dt.isoformat()
    except (OverflowError, ValueError):
        return None


def _get_macos_version() -> tuple[int, int]:
    """Get the macOS major and minor version numbers."""
    try:
        version = platform.mac_ver()[0]
        parts = version.split(".")
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except (ValueError, IndexError):
        return (0, 0)


class MessagesDB:
    """Read-only interface to the Messages chat.db SQLite database."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._macos_version = _get_macos_version()

    def _connect(self) -> sqlite3.Connection:
        """Open a read-only connection to chat.db."""
        if self._conn is not None:
            return self._conn

        db_file = Path(self._db_path)
        if not db_file.exists():
            raise FDAError(self._db_path)

        try:
            # Use URI mode for read-only access
            uri = f"file:{self._db_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            self._conn = conn
            return conn
        except sqlite3.OperationalError as e:
            error_msg = str(e).lower()
            if "unable to open" in error_msg or "readonly" in error_msg or "permission" in error_msg:
                raise FDAError(self._db_path) from e
            raise MessagesError(f"Cannot open Messages database: {e}") from e

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _decode_message_text(self, row: sqlite3.Row) -> str:
        """Extract message text from a row, trying text column then attributedBody.

        On macOS Ventura+, Messages often stores the text in attributedBody
        (as NSArchiver typedstream) with the text column as NULL.
        """
        text: str | None = row["text"]
        if text:
            return text

        # Try attributedBody decode
        attributed_body = row["attributedBody"]
        if attributed_body:
            decoded = decode_attributed_body(attributed_body)
            if decoded:
                return decoded

        return ""

    # -------------------------------------------------------------------
    # Chat queries
    # -------------------------------------------------------------------

    def get_chats(self, limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
        """List all conversations with participant info and last message time.

        Returns chat_id, display_name, chat_identifier, service_name,
        participant handles, and the most recent message timestamp.
        """
        conn = self._connect()
        query = """
            SELECT
                c.ROWID as chat_id,
                c.guid,
                c.chat_identifier,
                c.display_name,
                c.service_name,
                (SELECT GROUP_CONCAT(h.id, ', ')
                 FROM chat_handle_join chj
                 JOIN handle h ON h.ROWID = chj.handle_id
                 WHERE chj.chat_id = c.ROWID) as participants,
                (SELECT MAX(m.date)
                 FROM chat_message_join cmj
                 JOIN message m ON m.ROWID = cmj.message_id
                 WHERE cmj.chat_id = c.ROWID) as last_message_date,
                (SELECT COUNT(*)
                 FROM chat_message_join cmj
                 JOIN message m ON m.ROWID = cmj.message_id
                 WHERE cmj.chat_id = c.ROWID AND m.is_read = 0 AND m.is_from_me = 0
                ) as unread_count
            FROM chat c
            ORDER BY last_message_date DESC NULLS LAST
            LIMIT ?
        """
        rows = conn.execute(query, (limit,)).fetchall()
        return [
            {
                "chat_id": row["chat_id"],
                "guid": row["guid"],
                "chat_identifier": row["chat_identifier"],
                "display_name": row["display_name"],
                "service_name": row["service_name"],
                "participants": row["participants"],
                "last_message_date": apple_timestamp_to_iso(row["last_message_date"]),
                "unread_count": row["unread_count"] or 0,
            }
            for row in rows
        ]

    def get_chat(self, chat_id: int | None = None, handle: str | None = None) -> dict[str, Any] | None:
        """Look up a specific conversation by chat ID or handle (phone/email).

        Args:
            chat_id: The chat's ROWID in the database.
            handle: A phone number or email address to search for.

        Returns:
            Chat details dict or None if not found.
        """
        conn = self._connect()

        if chat_id is not None:
            query = """
                SELECT
                    c.ROWID as chat_id, c.guid, c.chat_identifier,
                    c.display_name, c.service_name,
                    (SELECT GROUP_CONCAT(h.id, ', ')
                     FROM chat_handle_join chj
                     JOIN handle h ON h.ROWID = chj.handle_id
                     WHERE chj.chat_id = c.ROWID) as participants,
                    (SELECT COUNT(*) FROM chat_message_join cmj WHERE cmj.chat_id = c.ROWID) as message_count,
                    (SELECT MAX(m.date)
                     FROM chat_message_join cmj
                     JOIN message m ON m.ROWID = cmj.message_id
                     WHERE cmj.chat_id = c.ROWID) as last_message_date
                FROM chat c
                WHERE c.ROWID = ?
            """
            row = conn.execute(query, (chat_id,)).fetchone()
        elif handle is not None:
            query = """
                SELECT
                    c.ROWID as chat_id, c.guid, c.chat_identifier,
                    c.display_name, c.service_name,
                    (SELECT GROUP_CONCAT(h.id, ', ')
                     FROM chat_handle_join chj
                     JOIN handle h ON h.ROWID = chj.handle_id
                     WHERE chj.chat_id = c.ROWID) as participants,
                    (SELECT COUNT(*) FROM chat_message_join cmj WHERE cmj.chat_id = c.ROWID) as message_count,
                    (SELECT MAX(m.date)
                     FROM chat_message_join cmj
                     JOIN message m ON m.ROWID = cmj.message_id
                     WHERE cmj.chat_id = c.ROWID) as last_message_date
                FROM chat c
                WHERE c.chat_identifier LIKE ?
                   OR c.ROWID IN (
                       SELECT chj.chat_id FROM chat_handle_join chj
                       JOIN handle h ON h.ROWID = chj.handle_id
                       WHERE h.id LIKE ?
                   )
                LIMIT 1
            """
            like_handle = f"%{handle}%"
            row = conn.execute(query, (like_handle, like_handle)).fetchone()
        else:
            raise MessagesError("Provide either chat_id or handle")

        if not row:
            return None

        return {
            "chat_id": row["chat_id"],
            "guid": row["guid"],
            "chat_identifier": row["chat_identifier"],
            "display_name": row["display_name"],
            "service_name": row["service_name"],
            "participants": row["participants"],
            "message_count": row["message_count"],
            "last_message_date": apple_timestamp_to_iso(row["last_message_date"]),
        }

    # -------------------------------------------------------------------
    # Message queries
    # -------------------------------------------------------------------

    def get_messages(
        self, chat_id: int, limit: int = DEFAULT_LIMIT, before_rowid: int | None = None
    ) -> list[dict[str, Any]]:
        """Get messages from a conversation, newest first.

        Supports pagination via ``before_rowid``: pass the smallest ROWID
        from the previous page to get older messages.
        """
        conn = self._connect()
        params: list[Any] = [chat_id]

        before_clause = ""
        if before_rowid is not None:
            before_clause = "AND m.ROWID < ?"
            params.append(before_rowid)

        params.append(limit)

        query = f"""
            SELECT
                m.ROWID as message_id,
                m.guid,
                m.text,
                m.attributedBody,
                m.date,
                m.is_from_me,
                m.is_read,
                m.cache_has_attachments,
                m.associated_message_type,
                h.id as handle_id
            FROM message m
            JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            LEFT JOIN handle h ON h.ROWID = m.handle_id
            WHERE cmj.chat_id = ?
            {before_clause}
            ORDER BY m.date DESC
            LIMIT ?
        """
        rows = conn.execute(query, params).fetchall()
        return [self._format_message_row(row) for row in rows]

    def get_recent_messages(self, limit: int = 20, since: str | None = None) -> list[dict[str, Any]]:
        """Get recent messages across all conversations.

        Args:
            limit: Maximum number of messages to return.
            since: Optional ISO timestamp — only return messages after this time.
        """
        conn = self._connect()
        params: list[Any] = []

        since_clause = ""
        if since:
            since_ns = self._iso_to_apple_timestamp(since)
            if since_ns is not None:
                since_clause = "WHERE m.date > ?"
                params.append(since_ns)

        params.append(limit)

        query = f"""
            SELECT
                m.ROWID as message_id,
                m.guid,
                m.text,
                m.attributedBody,
                m.date,
                m.is_from_me,
                m.is_read,
                m.cache_has_attachments,
                m.associated_message_type,
                h.id as handle_id,
                c.ROWID as chat_id,
                c.display_name as chat_name,
                c.chat_identifier
            FROM message m
            LEFT JOIN handle h ON h.ROWID = m.handle_id
            LEFT JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            LEFT JOIN chat c ON c.ROWID = cmj.chat_id
            {since_clause}
            ORDER BY m.date DESC
            LIMIT ?
        """
        rows = conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            msg = self._format_message_row(row)
            msg["chat_id"] = row["chat_id"]
            msg["chat_name"] = row["chat_name"] or row["chat_identifier"]
            results.append(msg)
        return results

    def search_messages(self, query_text: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search messages by text content using LIKE (no FTS5 on chat.db).

        Returns messages with their chat context for identification.
        """
        conn = self._connect()
        like_pattern = f"%{query_text}%"

        query = """
            SELECT
                m.ROWID as message_id,
                m.text,
                m.attributedBody,
                m.date,
                m.is_from_me,
                h.id as handle_id,
                c.ROWID as chat_id,
                c.display_name as chat_name,
                c.chat_identifier
            FROM message m
            LEFT JOIN handle h ON h.ROWID = m.handle_id
            LEFT JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            LEFT JOIN chat c ON c.ROWID = cmj.chat_id
            WHERE m.text LIKE ?
            ORDER BY m.date DESC
            LIMIT ?
        """
        rows = conn.execute(query, (like_pattern, limit)).fetchall()
        results = []
        for row in rows:
            text = row["text"] or ""
            # If text is empty, try attributedBody
            if not text and row["attributedBody"]:
                decoded = decode_attributed_body(row["attributedBody"])
                text = decoded or ""

            results.append(
                {
                    "message_id": row["message_id"],
                    "text": text,
                    "date": apple_timestamp_to_iso(row["date"]),
                    "is_from_me": bool(row["is_from_me"]),
                    "handle_id": row["handle_id"],
                    "chat_id": row["chat_id"],
                    "chat_name": row["chat_name"] or row["chat_identifier"],
                }
            )
        return results

    # -------------------------------------------------------------------
    # Contact / handle queries
    # -------------------------------------------------------------------

    def get_contacts(self, limit: int = 100) -> list[dict[str, Any]]:
        """List all known handles (phone numbers, emails, iCloud accounts)."""
        conn = self._connect()
        query = """
            SELECT
                h.ROWID as handle_rowid,
                h.id as handle_id,
                h.service,
                h.uncanonicalized_id,
                (SELECT COUNT(*)
                 FROM message m
                 WHERE m.handle_id = h.ROWID) as message_count,
                (SELECT MAX(m.date)
                 FROM message m
                 WHERE m.handle_id = h.ROWID) as last_message_date
            FROM handle h
            ORDER BY last_message_date DESC NULLS LAST
            LIMIT ?
        """
        rows = conn.execute(query, (limit,)).fetchall()
        return [
            {
                "handle_rowid": row["handle_rowid"],
                "handle_id": row["handle_id"],
                "service": row["service"],
                "uncanonicalized_id": row["uncanonicalized_id"],
                "message_count": row["message_count"] or 0,
                "last_message_date": apple_timestamp_to_iso(row["last_message_date"]),
            }
            for row in rows
        ]

    def get_contact(self, handle_id: str) -> dict[str, Any] | None:
        """Get details for a specific handle including message stats."""
        conn = self._connect()
        query = """
            SELECT
                h.ROWID as handle_rowid,
                h.id as handle_id,
                h.service,
                h.uncanonicalized_id,
                (SELECT COUNT(*) FROM message m WHERE m.handle_id = h.ROWID) as message_count,
                (SELECT COUNT(*) FROM message m WHERE m.handle_id = h.ROWID AND m.is_from_me = 1) as sent_count,
                (SELECT COUNT(*) FROM message m WHERE m.handle_id = h.ROWID AND m.is_from_me = 0) as received_count,
                (SELECT MIN(m.date) FROM message m WHERE m.handle_id = h.ROWID) as first_message_date,
                (SELECT MAX(m.date) FROM message m WHERE m.handle_id = h.ROWID) as last_message_date
            FROM handle h
            WHERE h.id LIKE ?
            LIMIT 1
        """
        row = conn.execute(query, (f"%{handle_id}%",)).fetchone()
        if not row:
            return None

        return {
            "handle_rowid": row["handle_rowid"],
            "handle_id": row["handle_id"],
            "service": row["service"],
            "uncanonicalized_id": row["uncanonicalized_id"],
            "message_count": row["message_count"] or 0,
            "sent_count": row["sent_count"] or 0,
            "received_count": row["received_count"] or 0,
            "first_message_date": apple_timestamp_to_iso(row["first_message_date"]),
            "last_message_date": apple_timestamp_to_iso(row["last_message_date"]),
        }

    # -------------------------------------------------------------------
    # Attachment queries
    # -------------------------------------------------------------------

    def get_attachments(self, chat_id: int, limit: int = 20) -> list[dict[str, Any]]:
        """List attachments from a conversation (metadata only, never file content)."""
        conn = self._connect()
        query = """
            SELECT
                a.ROWID as attachment_id,
                a.guid,
                a.filename,
                a.mime_type,
                a.total_bytes,
                a.transfer_name,
                a.uti,
                m.date as message_date,
                m.is_from_me
            FROM attachment a
            JOIN message_attachment_join maj ON maj.attachment_id = a.ROWID
            JOIN message m ON m.ROWID = maj.message_id
            JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            WHERE cmj.chat_id = ?
            ORDER BY m.date DESC
            LIMIT ?
        """
        rows = conn.execute(query, (chat_id, limit)).fetchall()
        return [
            {
                "attachment_id": row["attachment_id"],
                "guid": row["guid"],
                "filename": row["filename"],
                "mime_type": row["mime_type"],
                "total_bytes": row["total_bytes"],
                "transfer_name": row["transfer_name"],
                "uti": row["uti"],
                "date": apple_timestamp_to_iso(row["message_date"]),
                "is_from_me": bool(row["is_from_me"]),
            }
            for row in rows
        ]

    def get_attachment_info(self, attachment_id: int) -> dict[str, Any] | None:
        """Get detailed metadata for a single attachment. Never reads file content."""
        conn = self._connect()
        query = """
            SELECT
                a.ROWID as attachment_id,
                a.guid,
                a.filename,
                a.mime_type,
                a.total_bytes,
                a.transfer_name,
                a.uti
            FROM attachment a
            WHERE a.ROWID = ?
        """
        row = conn.execute(query, (attachment_id,)).fetchone()
        if not row:
            return None

        return {
            "attachment_id": row["attachment_id"],
            "guid": row["guid"],
            "filename": row["filename"],
            "mime_type": row["mime_type"],
            "total_bytes": row["total_bytes"],
            "transfer_name": row["transfer_name"],
            "uti": row["uti"],
        }

    # -------------------------------------------------------------------
    # Aggregate queries
    # -------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Aggregate statistics: total chats, messages, date range, top contacts."""
        conn = self._connect()

        chat_count = conn.execute("SELECT COUNT(*) FROM chat").fetchone()[0]
        message_count = conn.execute("SELECT COUNT(*) FROM message").fetchone()[0]

        date_range = conn.execute("SELECT MIN(date), MAX(date) FROM message WHERE date > 0").fetchone()
        first_date = apple_timestamp_to_iso(date_range[0]) if date_range[0] else None
        last_date = apple_timestamp_to_iso(date_range[1]) if date_range[1] else None

        # Top 5 contacts by message count
        top_contacts_rows = conn.execute("""
            SELECT h.id as handle_id, COUNT(*) as msg_count
            FROM message m
            JOIN handle h ON h.ROWID = m.handle_id
            GROUP BY h.ROWID
            ORDER BY msg_count DESC
            LIMIT 5
        """).fetchall()
        top_contacts = [{"handle_id": row["handle_id"], "message_count": row["msg_count"]} for row in top_contacts_rows]

        handle_count = conn.execute("SELECT COUNT(*) FROM handle").fetchone()[0]
        attachment_count = conn.execute("SELECT COUNT(*) FROM attachment").fetchone()[0]

        return {
            "chat_count": chat_count,
            "message_count": message_count,
            "handle_count": handle_count,
            "attachment_count": attachment_count,
            "first_message_date": first_date,
            "last_message_date": last_date,
            "top_contacts": top_contacts,
        }

    def get_unread(self) -> list[dict[str, Any]]:
        """Get unread message counts per conversation."""
        conn = self._connect()
        query = """
            SELECT
                c.ROWID as chat_id,
                c.display_name,
                c.chat_identifier,
                COUNT(*) as unread_count,
                MAX(m.date) as last_unread_date
            FROM message m
            JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            JOIN chat c ON c.ROWID = cmj.chat_id
            WHERE m.is_read = 0 AND m.is_from_me = 0
            GROUP BY c.ROWID
            HAVING unread_count > 0
            ORDER BY last_unread_date DESC
        """
        rows = conn.execute(query).fetchall()
        return [
            {
                "chat_id": row["chat_id"],
                "display_name": row["display_name"] or row["chat_identifier"],
                "unread_count": row["unread_count"],
                "last_unread_date": apple_timestamp_to_iso(row["last_unread_date"]),
            }
            for row in rows
        ]

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    def _format_message_row(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a message row to a dict with decoded text and timestamps."""
        text = self._decode_message_text(row)
        return {
            "message_id": row["message_id"],
            "text": text,
            "date": apple_timestamp_to_iso(row["date"]),
            "is_from_me": bool(row["is_from_me"]),
            "is_read": bool(row["is_read"]),
            "has_attachments": bool(row["cache_has_attachments"]),
            "handle_id": row["handle_id"],
            "associated_message_type": row["associated_message_type"],
        }

    @staticmethod
    def _iso_to_apple_timestamp(iso_str: str) -> int | None:
        """Convert an ISO 8601 timestamp to Apple nanosecond format."""
        try:
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            delta = dt - APPLE_EPOCH
            return int(delta.total_seconds() * 1_000_000_000)
        except (ValueError, OverflowError):
            return None
