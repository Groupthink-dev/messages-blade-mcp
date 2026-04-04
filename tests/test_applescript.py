"""Tests for applescript — command construction, input escaping, PII scrubbing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from messages_blade_mcp.applescript import (
    _escape_applescript,
    _validate_recipient,
    send_file,
    send_message,
    start_group,
)
from messages_blade_mcp.models import MessagesError, SendError

# ---------------------------------------------------------------------------
# Input escaping
# ---------------------------------------------------------------------------


class TestEscapeApplescript:
    def test_plain_text(self) -> None:
        assert _escape_applescript("Hello") == "Hello"

    def test_double_quotes(self) -> None:
        assert _escape_applescript('Say "hello"') == 'Say \\"hello\\"'

    def test_backslash(self) -> None:
        assert _escape_applescript("path\\to\\file") == "path\\\\to\\\\file"

    def test_newlines(self) -> None:
        assert _escape_applescript("line1\nline2") == "line1\\nline2"

    def test_tabs(self) -> None:
        assert _escape_applescript("col1\tcol2") == "col1\\tcol2"

    def test_combined(self) -> None:
        result = _escape_applescript('He said "hi"\nBye\\')
        assert '\\"' in result
        assert "\\n" in result
        assert "\\\\" in result


# ---------------------------------------------------------------------------
# Recipient validation
# ---------------------------------------------------------------------------


class TestValidateRecipient:
    def test_valid_phone_international(self) -> None:
        _validate_recipient("+61412345678")  # Should not raise

    def test_valid_phone_us(self) -> None:
        _validate_recipient("+15551234567")

    def test_valid_email(self) -> None:
        _validate_recipient("jane@example.com")

    def test_empty_string(self) -> None:
        with pytest.raises(MessagesError, match="empty"):
            _validate_recipient("")

    def test_whitespace_only(self) -> None:
        with pytest.raises(MessagesError, match="empty"):
            _validate_recipient("   ")

    def test_invalid_format(self) -> None:
        with pytest.raises(MessagesError, match="phone number"):
            _validate_recipient("not a phone or email")

    def test_phone_with_spaces(self) -> None:
        _validate_recipient("+61 412 345 678")  # Should not raise

    def test_phone_with_dashes(self) -> None:
        _validate_recipient("+1-555-123-4567")  # Should not raise


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------


class TestSendMessage:
    @patch("messages_blade_mcp.applescript._run_osascript")
    def test_successful_send(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        result = send_message("+61412345678", "Hello!")
        assert result is True
        mock_run.assert_called_once()

    @patch("messages_blade_mcp.applescript._run_osascript")
    def test_send_failure(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1, stderr="some error")
        with pytest.raises(SendError):
            send_message("+61412345678", "Hello!")

    @patch("messages_blade_mcp.applescript._run_osascript")
    def test_send_constructs_correct_script(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        send_message("+61412345678", "Test message")
        script = mock_run.call_args[0][0]
        assert "Messages" in script
        assert "+61412345678" in script
        assert "Test message" in script
        assert "iMessage" in script

    @patch("messages_blade_mcp.applescript._run_osascript")
    def test_send_sms_service(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        send_message("+61412345678", "Test", service="SMS")
        script = mock_run.call_args[0][0]
        assert "SMS" in script

    def test_send_empty_text(self) -> None:
        with pytest.raises(MessagesError, match="empty"):
            send_message("+61412345678", "")

    def test_send_invalid_recipient(self) -> None:
        with pytest.raises(MessagesError):
            send_message("invalid", "Hello!")

    @patch("messages_blade_mcp.applescript._run_osascript")
    def test_send_escapes_quotes(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        send_message("+61412345678", 'Say "hello"')
        script = mock_run.call_args[0][0]
        assert '\\"hello\\"' in script

    @patch("messages_blade_mcp.applescript._run_osascript")
    def test_error_scrubs_pii(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1, stderr="Error sending to +61412345678")
        with pytest.raises(SendError) as exc_info:
            send_message("+61412345678", "Hello!")
        assert "+61412345678" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# send_file
# ---------------------------------------------------------------------------


class TestSendFile:
    @patch("messages_blade_mcp.applescript._run_osascript")
    def test_send_file_success(self, mock_run: MagicMock, tmp_path: object) -> None:
        import pathlib

        # Create a temp file
        assert isinstance(tmp_path, pathlib.Path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        mock_run.return_value = MagicMock(returncode=0)
        result = send_file("+61412345678", str(test_file))
        assert result is True

    def test_send_file_nonexistent(self) -> None:
        with pytest.raises(MessagesError, match="does not exist"):
            send_file("+61412345678", "/nonexistent/file.txt")

    @patch("messages_blade_mcp.applescript._run_osascript")
    def test_send_file_constructs_posix(self, mock_run: MagicMock, tmp_path: object) -> None:
        import pathlib

        assert isinstance(tmp_path, pathlib.Path)
        test_file = tmp_path / "photo.jpg"
        test_file.write_text("fake image")

        mock_run.return_value = MagicMock(returncode=0)
        send_file("+61412345678", str(test_file))
        script = mock_run.call_args[0][0]
        assert "POSIX file" in script


# ---------------------------------------------------------------------------
# start_group
# ---------------------------------------------------------------------------


class TestStartGroup:
    @patch("messages_blade_mcp.applescript._run_osascript")
    def test_start_group_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        result = start_group(["+61412345678", "jane@example.com"], "Hello group!")
        assert result is True

    def test_start_group_single_recipient(self) -> None:
        with pytest.raises(MessagesError, match="at least 2"):
            start_group(["+61412345678"], "Hello!")

    def test_start_group_empty_text(self) -> None:
        with pytest.raises(MessagesError, match="empty"):
            start_group(["+61412345678", "jane@example.com"], "")

    @patch("messages_blade_mcp.applescript._run_osascript")
    def test_start_group_includes_all_recipients(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        start_group(["+61412345678", "jane@example.com", "+15551234567"], "Hey all!")
        script = mock_run.call_args[0][0]
        assert "+61412345678" in script
        assert "jane@example.com" in script
        assert "+15551234567" in script
