"""Tests for database — queries against in-memory chat.db clone."""

from __future__ import annotations

import sqlite3
from datetime import UTC

import pytest

from messages_blade_mcp.database import MessagesDB, apple_timestamp_to_iso

# ---------------------------------------------------------------------------
# Timestamp conversion
# ---------------------------------------------------------------------------


class TestAppleTimestamp:
    def test_known_date(self) -> None:
        """2026-01-01T00:00:00Z = 25 years after Apple epoch (2001-01-01)."""
        # 25 years * 365.25 days * 86400 seconds * 1e9 nanoseconds (approx)
        # Use a more precise calculation
        from datetime import datetime

        apple_epoch = datetime(2001, 1, 1, tzinfo=UTC)
        target = datetime(2026, 1, 1, tzinfo=UTC)
        ns = int((target - apple_epoch).total_seconds() * 1_000_000_000)
        result = apple_timestamp_to_iso(ns)
        assert result is not None
        assert result.startswith("2026-01-01")

    def test_none_returns_none(self) -> None:
        assert apple_timestamp_to_iso(None) is None

    def test_zero_returns_none(self) -> None:
        assert apple_timestamp_to_iso(0) is None

    def test_negative_handled(self) -> None:
        # Negative timestamps (before 2001) should still convert
        result = apple_timestamp_to_iso(-1_000_000_000)
        assert result is not None
        assert "2000" in result


# ---------------------------------------------------------------------------
# MessagesDB with in-memory test database
# ---------------------------------------------------------------------------


class TestMessagesDB:
    """Test MessagesDB methods using the conftest in-memory database."""

    @pytest.fixture(autouse=True)
    def setup_db(self, test_db: sqlite3.Connection) -> None:
        """Inject the test database connection into a MessagesDB instance."""
        self.db = MessagesDB.__new__(MessagesDB)
        self.db._db_path = ":memory:"
        self.db._conn = test_db
        self.db._macos_version = (15, 0)

    def test_get_chats(self) -> None:
        chats = self.db.get_chats()
        assert len(chats) >= 3
        # Should be ordered by last_message_date desc
        assert all(isinstance(c["chat_id"], int) for c in chats)

    def test_get_chats_limit(self) -> None:
        chats = self.db.get_chats(limit=2)
        assert len(chats) == 2

    def test_get_chat_by_id(self) -> None:
        chat = self.db.get_chat(chat_id=1)
        assert chat is not None
        assert chat["chat_id"] == 1
        assert chat["chat_identifier"] == "+61412345678"

    def test_get_chat_by_handle(self) -> None:
        chat = self.db.get_chat(handle="jane@example.com")
        assert chat is not None
        assert chat["display_name"] == "Jane Smith"

    def test_get_chat_not_found(self) -> None:
        chat = self.db.get_chat(chat_id=999)
        assert chat is None

    def test_get_chat_by_partial_handle(self) -> None:
        chat = self.db.get_chat(handle="412345678")
        assert chat is not None

    def test_get_messages(self) -> None:
        messages = self.db.get_messages(chat_id=1)
        assert len(messages) >= 3
        # Should include text content
        texts = [m["text"] for m in messages if m["text"]]
        assert "Hello there!" in texts

    def test_get_messages_limit(self) -> None:
        messages = self.db.get_messages(chat_id=1, limit=2)
        assert len(messages) == 2

    def test_get_messages_pagination(self) -> None:
        all_msgs = self.db.get_messages(chat_id=1, limit=100)
        if len(all_msgs) >= 2:
            # Get messages before the second one
            second_id = all_msgs[1]["message_id"]
            older = self.db.get_messages(chat_id=1, before_rowid=second_id)
            assert all(m["message_id"] < second_id for m in older)

    def test_get_recent_messages(self) -> None:
        recent = self.db.get_recent_messages(limit=5)
        assert len(recent) >= 1
        # Should include chat context
        assert "chat_id" in recent[0]

    def test_get_recent_messages_since(self) -> None:
        recent = self.db.get_recent_messages(since="2026-03-16T00:00:00+00:00")
        # Should only get messages from March 16
        assert len(recent) >= 1

    def test_search_messages(self) -> None:
        results = self.db.search_messages("Hello")
        assert len(results) >= 1
        assert any("Hello" in r["text"] for r in results)

    def test_search_messages_no_results(self) -> None:
        results = self.db.search_messages("xyznonexistent")
        assert len(results) == 0

    def test_search_messages_case_insensitive(self) -> None:
        # SQLite LIKE is case-insensitive for ASCII
        results = self.db.search_messages("hello")
        assert len(results) >= 1

    def test_get_contacts(self) -> None:
        contacts = self.db.get_contacts()
        assert len(contacts) == 3
        # Should include handle IDs
        handle_ids = [c["handle_id"] for c in contacts]
        assert "+61412345678" in handle_ids

    def test_get_contacts_limit(self) -> None:
        contacts = self.db.get_contacts(limit=1)
        assert len(contacts) == 1

    def test_get_contact(self) -> None:
        contact = self.db.get_contact("+61412345678")
        assert contact is not None
        assert contact["handle_id"] == "+61412345678"
        assert contact["message_count"] > 0

    def test_get_contact_with_stats(self) -> None:
        contact = self.db.get_contact("+61412345678")
        assert contact is not None
        assert "sent_count" in contact
        assert "received_count" in contact
        assert "first_message_date" in contact
        assert "last_message_date" in contact

    def test_get_contact_not_found(self) -> None:
        contact = self.db.get_contact("nonexistent")
        assert contact is None

    def test_get_attachments(self) -> None:
        attachments = self.db.get_attachments(chat_id=2)
        assert len(attachments) == 2
        assert attachments[0]["mime_type"] in ["image/jpeg", "application/pdf"]

    def test_get_attachments_empty(self) -> None:
        attachments = self.db.get_attachments(chat_id=3)
        assert len(attachments) == 0

    def test_get_attachment_info(self) -> None:
        info = self.db.get_attachment_info(1)
        assert info is not None
        assert info["mime_type"] == "image/jpeg"
        assert info["total_bytes"] == 2048576

    def test_get_attachment_info_not_found(self) -> None:
        info = self.db.get_attachment_info(999)
        assert info is None

    def test_get_stats(self) -> None:
        stats = self.db.get_stats()
        assert stats["chat_count"] == 4
        assert stats["message_count"] == 7
        assert stats["handle_count"] == 3
        assert stats["attachment_count"] == 2
        assert stats["top_contacts"] is not None
        assert len(stats["top_contacts"]) >= 1

    def test_get_unread(self) -> None:
        unread = self.db.get_unread()
        # Messages 4 and 7 are unread (is_read=0, is_from_me=0)
        assert len(unread) >= 1
        total_unread = sum(u["unread_count"] for u in unread)
        assert total_unread >= 2


# ---------------------------------------------------------------------------
# FDA error handling
# ---------------------------------------------------------------------------


class TestFDAHandling:
    def test_missing_db_raises_fda_error(self) -> None:
        db = MessagesDB(db_path="/nonexistent/path/chat.db")
        with pytest.raises(Exception):
            db._connect()

    def test_message_text_fallback_to_empty(self, test_db: sqlite3.Connection) -> None:
        """Message with no text and no attributedBody returns empty string."""
        db = MessagesDB.__new__(MessagesDB)
        db._db_path = ":memory:"
        db._conn = test_db
        db._macos_version = (15, 0)

        # Message 6 has NULL text and no attributedBody
        messages = db.get_messages(chat_id=1)
        tapback = [m for m in messages if m["associated_message_type"] == 2000]
        assert len(tapback) >= 1
        assert tapback[0]["text"] == ""
