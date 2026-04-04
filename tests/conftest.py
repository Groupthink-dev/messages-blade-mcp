"""Shared test fixtures for messages-blade-mcp."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from datetime import UTC
from typing import Any

import pytest


def _apple_ns_timestamp(year: int, month: int, day: int, hour: int = 0) -> int:
    """Create an Apple nanosecond timestamp for a given date.

    Apple epoch is 2001-01-01T00:00:00Z. Returns nanoseconds.
    """
    from datetime import datetime

    apple_epoch = datetime(2001, 1, 1, tzinfo=UTC)
    dt = datetime(year, month, day, hour, tzinfo=UTC)
    delta = dt - apple_epoch
    return int(delta.total_seconds() * 1_000_000_000)


@pytest.fixture
def test_db() -> Generator[sqlite3.Connection, None, None]:
    """Create an in-memory SQLite database mimicking chat.db schema with test data."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    # Create tables matching chat.db schema
    conn.executescript("""
        CREATE TABLE handle (
            ROWID INTEGER PRIMARY KEY,
            id TEXT,
            service TEXT,
            uncanonicalized_id TEXT
        );

        CREATE TABLE chat (
            ROWID INTEGER PRIMARY KEY,
            guid TEXT,
            chat_identifier TEXT,
            display_name TEXT,
            group_id TEXT,
            service_name TEXT
        );

        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY,
            guid TEXT,
            text TEXT,
            attributedBody BLOB,
            handle_id INTEGER,
            date INTEGER,
            is_from_me INTEGER DEFAULT 0,
            is_read INTEGER DEFAULT 0,
            cache_has_attachments INTEGER DEFAULT 0,
            associated_message_type INTEGER DEFAULT 0
        );

        CREATE TABLE chat_handle_join (
            chat_id INTEGER,
            handle_id INTEGER
        );

        CREATE TABLE chat_message_join (
            chat_id INTEGER,
            message_id INTEGER
        );

        CREATE TABLE attachment (
            ROWID INTEGER PRIMARY KEY,
            guid TEXT,
            filename TEXT,
            mime_type TEXT,
            total_bytes INTEGER,
            transfer_name TEXT,
            uti TEXT
        );

        CREATE TABLE message_attachment_join (
            message_id INTEGER,
            attachment_id INTEGER
        );
    """)

    # Insert test handles
    conn.executemany(
        "INSERT INTO handle (ROWID, id, service, uncanonicalized_id) VALUES (?, ?, ?, ?)",
        [
            (1, "+61412345678", "iMessage", "+61412345678"),
            (2, "jane@example.com", "iMessage", "jane@example.com"),
            (3, "+15551234567", "SMS", "+15551234567"),
        ],
    )

    # Insert test chats
    chat_sql = (
        "INSERT INTO chat (ROWID, guid, chat_identifier, display_name, group_id, service_name)"
        " VALUES (?, ?, ?, ?, ?, ?)"
    )
    conn.executemany(
        chat_sql,
        [
            (1, "iMessage;-;+61412345678", "+61412345678", None, None, "iMessage"),
            (2, "iMessage;-;jane@example.com", "jane@example.com", "Jane Smith", None, "iMessage"),
            (3, "SMS;-;+15551234567", "+15551234567", None, None, "SMS"),
            (4, "iMessage;+;chat123", "chat123", "Family Group", "group123", "iMessage"),
        ],
    )

    # Insert chat-handle joins
    conn.executemany(
        "INSERT INTO chat_handle_join (chat_id, handle_id) VALUES (?, ?)",
        [
            (1, 1),
            (2, 2),
            (3, 3),
            (4, 1),
            (4, 2),
        ],
    )

    # Timestamps
    ts1 = _apple_ns_timestamp(2026, 3, 15, 10)
    ts2 = _apple_ns_timestamp(2026, 3, 15, 11)
    ts3 = _apple_ns_timestamp(2026, 3, 15, 12)
    ts4 = _apple_ns_timestamp(2026, 3, 16, 9)
    ts5 = _apple_ns_timestamp(2026, 3, 16, 10)

    # Insert test messages
    conn.executemany(
        """INSERT INTO message (ROWID, guid, text, attributedBody, handle_id, date,
           is_from_me, is_read, cache_has_attachments, associated_message_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (1, "msg-001", "Hello there!", None, 1, ts1, 0, 1, 0, 0),
            (2, "msg-002", "Hi! How are you?", None, None, ts2, 1, 1, 0, 0),
            (3, "msg-003", "Good thanks", None, 1, ts3, 0, 1, 0, 0),
            (4, "msg-004", "Check out this photo", None, 2, ts4, 0, 0, 1, 0),
            (5, "msg-005", "Looks great!", None, None, ts5, 1, 1, 0, 0),
            (6, "msg-006", None, None, 1, ts3, 0, 1, 0, 2000),  # Tapback/reaction
            (7, "msg-007", "Meeting tomorrow at 3pm", None, 3, ts4, 0, 0, 0, 0),  # Unread SMS
        ],
    )

    # Chat-message joins
    conn.executemany(
        "INSERT INTO chat_message_join (chat_id, message_id) VALUES (?, ?)",
        [
            (1, 1),
            (1, 2),
            (1, 3),
            (1, 6),
            (2, 4),
            (2, 5),
            (3, 7),
        ],
    )

    # Insert test attachments
    att_sql = (
        "INSERT INTO attachment (ROWID, guid, filename, mime_type, total_bytes, transfer_name, uti)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)"
    )
    conn.executemany(
        att_sql,
        [
            (
                1,
                "att-001",
                "~/Library/Messages/Attachments/photo.jpg",
                "image/jpeg",
                2048576,
                "photo.jpg",
                "public.jpeg",
            ),
            (
                2,
                "att-002",
                "~/Library/Messages/Attachments/doc.pdf",
                "application/pdf",
                102400,
                "doc.pdf",
                "com.adobe.pdf",
            ),
        ],
    )

    # Message-attachment joins
    conn.executemany(
        "INSERT INTO message_attachment_join (message_id, attachment_id) VALUES (?, ?)",
        [(4, 1), (4, 2)],
    )

    yield conn
    conn.close()


@pytest.fixture
def sample_message() -> dict[str, Any]:
    """A sample message dict for formatter tests."""
    return {
        "message_id": 42,
        "text": "Hello world!",
        "date": "2026-03-15T10:00:00+00:00",
        "is_from_me": False,
        "is_read": True,
        "has_attachments": False,
        "handle_id": "+61412345678",
        "associated_message_type": 0,
    }


@pytest.fixture
def sample_chat() -> dict[str, Any]:
    """A sample chat dict for formatter tests."""
    return {
        "chat_id": 1,
        "guid": "iMessage;-;+61412345678",
        "chat_identifier": "+61412345678",
        "display_name": None,
        "service_name": "iMessage",
        "participants": "+61412345678",
        "last_message_date": "2026-03-15T12:00:00+00:00",
        "unread_count": 2,
    }


@pytest.fixture
def sample_contact() -> dict[str, Any]:
    """A sample contact dict for formatter tests."""
    return {
        "handle_rowid": 1,
        "handle_id": "+61412345678",
        "service": "iMessage",
        "uncanonicalized_id": "+61412345678",
        "message_count": 150,
        "last_message_date": "2026-03-16T10:00:00+00:00",
    }


@pytest.fixture
def sample_attachment() -> dict[str, Any]:
    """A sample attachment dict for formatter tests."""
    return {
        "attachment_id": 1,
        "guid": "att-001",
        "filename": "~/Library/Messages/Attachments/photo.jpg",
        "mime_type": "image/jpeg",
        "total_bytes": 2048576,
        "transfer_name": "photo.jpg",
        "uti": "public.jpeg",
        "date": "2026-03-16T09:00:00+00:00",
    }
