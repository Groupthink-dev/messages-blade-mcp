"""Tests for models — config resolution, write/confirm gates, PII scrubbing."""

from __future__ import annotations

import os
from unittest.mock import patch

from messages_blade_mcp.models import (
    DEFAULT_DB_PATH,
    FDAError,
    MessagesConfig,
    MessagesError,
    check_confirm_gate,
    check_write_gate,
    resolve_config,
    scrub_pii,
)

# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------


class TestResolveConfig:
    def test_default_config(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = resolve_config()
        assert config.db_path == DEFAULT_DB_PATH
        assert config.write_enabled is False

    def test_custom_db_path(self) -> None:
        with patch.dict(os.environ, {"MESSAGES_DB_PATH": "/tmp/test.db"}, clear=True):
            config = resolve_config()
        assert config.db_path == "/tmp/test.db"

    def test_write_enabled_true(self) -> None:
        with patch.dict(os.environ, {"MESSAGES_WRITE_ENABLED": "true"}, clear=True):
            config = resolve_config()
        assert config.write_enabled is True

    def test_write_enabled_false(self) -> None:
        with patch.dict(os.environ, {"MESSAGES_WRITE_ENABLED": "false"}, clear=True):
            config = resolve_config()
        assert config.write_enabled is False

    def test_write_enabled_case_insensitive(self) -> None:
        with patch.dict(os.environ, {"MESSAGES_WRITE_ENABLED": "True"}, clear=True):
            config = resolve_config()
        assert config.write_enabled is True

    def test_write_enabled_empty(self) -> None:
        with patch.dict(os.environ, {"MESSAGES_WRITE_ENABLED": ""}, clear=True):
            config = resolve_config()
        assert config.write_enabled is False


# ---------------------------------------------------------------------------
# Write gate
# ---------------------------------------------------------------------------


class TestWriteGate:
    def test_write_disabled(self) -> None:
        config = MessagesConfig(write_enabled=False)
        result = check_write_gate(config)
        assert result is not None
        assert "disabled" in result.lower()

    def test_write_enabled(self) -> None:
        config = MessagesConfig(write_enabled=True)
        result = check_write_gate(config)
        assert result is None


# ---------------------------------------------------------------------------
# Confirm gate
# ---------------------------------------------------------------------------


class TestConfirmGate:
    def test_confirm_false(self) -> None:
        result = check_confirm_gate(False, "test action")
        assert result is not None
        assert "confirm=true" in result

    def test_confirm_true(self) -> None:
        result = check_confirm_gate(True, "test action")
        assert result is None

    def test_confirm_includes_action(self) -> None:
        result = check_confirm_gate(False, "Sending a message")
        assert result is not None
        assert "Sending a message" in result


# ---------------------------------------------------------------------------
# PII scrubbing
# ---------------------------------------------------------------------------


class TestScrubPii:
    def test_international_phone(self) -> None:
        assert "[REDACTED]" in scrub_pii("Call +61412345678 now")

    def test_us_phone_dashes(self) -> None:
        assert "[REDACTED]" in scrub_pii("Call 555-123-4567")

    def test_au_phone_spaces(self) -> None:
        assert "[REDACTED]" in scrub_pii("Call 0412 345 678")

    def test_unformatted_phone(self) -> None:
        assert "[REDACTED]" in scrub_pii("Number: 0412345678")

    def test_email_address(self) -> None:
        assert "[REDACTED]" in scrub_pii("Email john@example.com for info")

    def test_no_pii(self) -> None:
        text = "Just a normal message with no PII"
        assert scrub_pii(text) == text

    def test_multiple_pii(self) -> None:
        text = "Contact +61412345678 or jane@example.com"
        result = scrub_pii(text)
        assert "+61412345678" not in result
        assert "jane@example.com" not in result

    def test_preserves_non_pii(self) -> None:
        text = "Error at line 42 in module foo"
        assert scrub_pii(text) == text


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TestExceptions:
    def test_messages_error_scrubs_pii(self) -> None:
        err = MessagesError("Failed for +61412345678")
        assert "+61412345678" not in str(err)
        assert "[REDACTED]" in str(err)

    def test_fda_error_message(self) -> None:
        err = FDAError()
        msg = str(err)
        assert "Full Disk Access" in msg
        assert "System Settings" in msg

    def test_fda_error_custom_path(self) -> None:
        err = FDAError("/custom/path/chat.db")
        msg = str(err)
        assert "/custom/path/chat.db" in msg
