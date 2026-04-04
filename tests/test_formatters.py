"""Tests for formatters — pipe-delimited output, truncation, null handling."""

from __future__ import annotations

from typing import Any

from messages_blade_mcp.formatters import (
    format_attachment,
    format_attachments,
    format_chat,
    format_chats,
    format_contact,
    format_contact_detail,
    format_contacts,
    format_error,
    format_info,
    format_message,
    format_messages,
    format_recent_message,
    format_recent_messages,
    format_search_result,
    format_search_results,
    format_stats,
    format_unread,
    truncate,
)

# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_short_text(self) -> None:
        assert truncate("Hello") == "Hello"

    def test_exact_limit(self) -> None:
        text = "A" * 200
        assert truncate(text) == text

    def test_over_limit(self) -> None:
        text = "A" * 250
        result = truncate(text)
        assert len(result) == 200
        assert result.endswith("...")

    def test_custom_limit(self) -> None:
        text = "A" * 20
        result = truncate(text, 10)
        assert len(result) == 10
        assert result.endswith("...")

    def test_empty(self) -> None:
        assert truncate("") == ""

    def test_none_like(self) -> None:
        assert truncate("") == ""


# ---------------------------------------------------------------------------
# Chat formatting
# ---------------------------------------------------------------------------


class TestFormatChat:
    def test_basic_chat(self, sample_chat: dict[str, Any]) -> None:
        result = format_chat(sample_chat)
        assert "1" in result  # chat_id
        assert "iMessage" in result
        assert "unread=2" in result

    def test_chat_with_display_name(self) -> None:
        chat = {"chat_id": 2, "display_name": "Jane", "service_name": "iMessage"}
        result = format_chat(chat)
        assert "Jane" in result

    def test_chat_without_name_uses_identifier(self) -> None:
        chat = {"chat_id": 1, "display_name": None, "chat_identifier": "+61412345678"}
        result = format_chat(chat)
        assert "+61412345678" in result

    def test_chat_no_unread(self) -> None:
        chat = {"chat_id": 1, "display_name": "Test", "unread_count": 0}
        result = format_chat(chat)
        assert "unread" not in result

    def test_format_chats_empty(self) -> None:
        assert "no conversations" in format_chats([])


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------


class TestFormatMessage:
    def test_basic_message(self, sample_message: dict[str, Any]) -> None:
        result = format_message(sample_message)
        assert "42" in result  # message_id
        assert "Hello world!" in result
        assert "+61412345678" in result

    def test_from_me(self) -> None:
        msg = {"message_id": 1, "text": "Hi", "is_from_me": True, "date": "2026-01-01"}
        result = format_message(msg)
        assert "me" in result

    def test_attachment_message(self) -> None:
        msg = {"message_id": 1, "text": "", "is_from_me": False, "has_attachments": True, "handle_id": "test"}
        result = format_message(msg)
        assert "[attachment]" in result

    def test_tapback_message(self) -> None:
        msg = {
            "message_id": 1,
            "text": "",
            "is_from_me": False,
            "has_attachments": False,
            "associated_message_type": 2000,
            "handle_id": "test",
        }
        result = format_message(msg)
        assert "[reaction/tapback]" in result

    def test_empty_message(self) -> None:
        msg = {
            "message_id": 1,
            "text": "",
            "is_from_me": False,
            "has_attachments": False,
            "associated_message_type": 0,
            "handle_id": "test",
        }
        result = format_message(msg)
        assert "[empty]" in result

    def test_format_messages_empty(self) -> None:
        assert "no messages" in format_messages([])


# ---------------------------------------------------------------------------
# Recent message formatting
# ---------------------------------------------------------------------------


class TestFormatRecentMessage:
    def test_with_chat_context(self) -> None:
        msg = {
            "message_id": 1,
            "text": "Hello",
            "date": "2026-01-01",
            "is_from_me": False,
            "handle_id": "+61412345678",
            "chat_id": 5,
            "chat_name": "Family Group",
        }
        result = format_recent_message(msg)
        assert "5" in result
        assert "Family Group" in result
        assert "Hello" in result

    def test_format_recent_empty(self) -> None:
        assert "no recent" in format_recent_messages([])


# ---------------------------------------------------------------------------
# Search result formatting
# ---------------------------------------------------------------------------


class TestFormatSearchResult:
    def test_basic_result(self) -> None:
        result_data = {
            "chat_id": 1,
            "chat_name": "Jane Smith",
            "handle_id": "jane@example.com",
            "date": "2026-03-15T10:00:00",
            "text": "Found this message",
        }
        result = format_search_result(result_data)
        assert "Jane Smith" in result
        assert "Found this" in result

    def test_format_search_empty(self) -> None:
        assert "no matches" in format_search_results([])


# ---------------------------------------------------------------------------
# Contact formatting
# ---------------------------------------------------------------------------


class TestFormatContact:
    def test_basic_contact(self, sample_contact: dict[str, Any]) -> None:
        result = format_contact(sample_contact)
        assert "+61412345678" in result
        assert "messages=150" in result
        assert "iMessage" in result

    def test_format_contacts_empty(self) -> None:
        assert "no contacts" in format_contacts([])

    def test_contact_detail(self) -> None:
        contact = {
            "handle_id": "+61412345678",
            "service": "iMessage",
            "message_count": 100,
            "sent_count": 40,
            "received_count": 60,
            "first_message_date": "2025-01-01",
            "last_message_date": "2026-03-16",
        }
        result = format_contact_detail(contact)
        assert "total=100" in result
        assert "sent=40" in result
        assert "received=60" in result


# ---------------------------------------------------------------------------
# Attachment formatting
# ---------------------------------------------------------------------------


class TestFormatAttachment:
    def test_basic_attachment(self, sample_attachment: dict[str, Any]) -> None:
        result = format_attachment(sample_attachment)
        assert "1" in result
        assert "photo.jpg" in result
        assert "image/jpeg" in result
        assert "2.0MB" in result

    def test_format_attachments_empty(self) -> None:
        assert "no attachments" in format_attachments([])


# ---------------------------------------------------------------------------
# Stats formatting
# ---------------------------------------------------------------------------


class TestFormatStats:
    def test_basic_stats(self) -> None:
        stats = {
            "chat_count": 42,
            "message_count": 12345,
            "handle_count": 67,
            "attachment_count": 890,
            "first_message_date": "2020-01-01",
            "last_message_date": "2026-03-16",
            "top_contacts": [
                {"handle_id": "+61412345678", "message_count": 500},
                {"handle_id": "jane@example.com", "message_count": 300},
            ],
        }
        result = format_stats(stats)
        assert "chats=42" in result
        assert "messages=12345" in result
        assert "handles=67" in result
        assert "top=" in result

    def test_empty_stats(self) -> None:
        stats = {
            "chat_count": 0,
            "message_count": 0,
            "handle_count": 0,
            "attachment_count": 0,
        }
        result = format_stats(stats)
        assert "chats=0" in result


# ---------------------------------------------------------------------------
# Unread formatting
# ---------------------------------------------------------------------------


class TestFormatUnread:
    def test_unread_messages(self) -> None:
        unread = [
            {"display_name": "Jane Smith", "unread_count": 3, "last_unread_date": "2026-03-16"},
            {"display_name": "Family Group", "unread_count": 1, "last_unread_date": "2026-03-15"},
        ]
        result = format_unread(unread)
        assert "Jane Smith" in result
        assert "unread=3" in result

    def test_no_unread(self) -> None:
        assert "no unread" in format_unread([])


# ---------------------------------------------------------------------------
# Info formatting
# ---------------------------------------------------------------------------


class TestFormatInfo:
    def test_basic_info(self) -> None:
        info = {"macos": "15.4", "fda": "granted", "write_gate": "disabled"}
        result = format_info(info)
        assert "macos=15.4" in result
        assert "fda=granted" in result

    def test_none_values_omitted(self) -> None:
        info = {"macos": "15.4", "fda": None}
        result = format_info(info)
        assert "fda" not in result


# ---------------------------------------------------------------------------
# Error formatting
# ---------------------------------------------------------------------------


class TestFormatError:
    def test_basic_error(self) -> None:
        result = format_error(Exception("Something failed"))
        assert result.startswith("Error:")
        assert "Something failed" in result

    def test_error_with_pii(self) -> None:
        result = format_error(Exception("Failed for +61412345678"))
        assert "+61412345678" not in result
        assert "[REDACTED]" in result
