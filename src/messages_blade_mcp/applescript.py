"""AppleScript bridge for sending messages via Messages.app.

Uses /usr/bin/osascript to interact with Messages.app. All inputs are
escaped to prevent AppleScript injection. All error messages have PII
scrubbed before being raised.

Requires TCC Automation permission for the terminal emulator to control
Messages.app. macOS will prompt on first use.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from messages_blade_mcp.models import MessagesError, SendError, scrub_pii

logger = logging.getLogger(__name__)

# Timeout for osascript execution (seconds)
_OSASCRIPT_TIMEOUT = 30


def _escape_applescript(text: str) -> str:
    """Escape a string for safe inclusion in AppleScript double-quoted strings.

    Handles backslashes, double quotes, and other special characters.
    """
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    text = text.replace("\n", "\\n")
    text = text.replace("\r", "\\r")
    text = text.replace("\t", "\\t")
    return text


def _validate_recipient(recipient: str) -> None:
    """Validate that a recipient looks like a phone number or email address."""
    if not recipient or not recipient.strip():
        raise MessagesError("Recipient cannot be empty")

    stripped = recipient.strip()
    # Phone number: starts with + or digit, contains only digits/spaces/dashes/parens
    is_phone = stripped[0] in "+0123456789" and all(c in "0123456789+-() " for c in stripped)
    # Email: contains @
    is_email = "@" in stripped and "." in stripped.split("@")[-1]

    if not is_phone and not is_email:
        raise MessagesError("Recipient must be a phone number (e.g. +61412345678) or email address")


def _run_osascript(script: str) -> subprocess.CompletedProcess[str]:
    """Execute an AppleScript via /usr/bin/osascript.

    Uses the system osascript binary to avoid TCC churn with Nix-built binaries.
    """
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=_OSASCRIPT_TIMEOUT,
        )
        return result
    except subprocess.TimeoutExpired as e:
        raise SendError("Messages.app did not respond within timeout") from e
    except FileNotFoundError as e:
        raise SendError("osascript not found — this MCP requires macOS") from e


def send_message(recipient: str, text: str, service: str = "iMessage") -> bool:
    """Send a text message to a recipient via Messages.app.

    Args:
        recipient: Phone number (e.g. +61412345678) or email address.
        text: Message text to send.
        service: Service type — "iMessage" or "SMS". Defaults to "iMessage".

    Returns:
        True if the message was sent successfully.

    Raises:
        SendError: If the message could not be sent.
        MessagesError: If inputs are invalid.
    """
    _validate_recipient(recipient)
    if not text or not text.strip():
        raise MessagesError("Message text cannot be empty")

    escaped_text = _escape_applescript(text)
    escaped_recipient = _escape_applescript(recipient.strip())

    script = f'''
    tell application "Messages"
        set targetService to 1st service whose service type = {service}
        set targetBuddy to buddy "{escaped_recipient}" of targetService
        send "{escaped_text}" to targetBuddy
    end tell
    '''

    result = _run_osascript(script)

    if result.returncode != 0:
        error_detail = scrub_pii(result.stderr.strip()) if result.stderr else "Unknown error"
        raise SendError(f"Failed to send message: {error_detail}")

    return True


def send_file(recipient: str, file_path: str, service: str = "iMessage") -> bool:
    """Send a file attachment to a recipient via Messages.app.

    Args:
        recipient: Phone number or email address.
        file_path: Absolute path to the file to send.
        service: Service type — "iMessage" or "SMS".

    Returns:
        True if the file was sent successfully.

    Raises:
        SendError: If the file could not be sent.
        MessagesError: If inputs are invalid or file doesn't exist.
    """
    _validate_recipient(recipient)

    path = Path(file_path)
    if not path.exists():
        raise MessagesError(f"File does not exist: {file_path}")
    if not path.is_file():
        raise MessagesError(f"Path is not a file: {file_path}")

    escaped_recipient = _escape_applescript(recipient.strip())
    escaped_path = _escape_applescript(str(path.resolve()))

    script = f'''
    tell application "Messages"
        set targetService to 1st service whose service type = {service}
        set targetBuddy to buddy "{escaped_recipient}" of targetService
        send POSIX file "{escaped_path}" to targetBuddy
    end tell
    '''

    result = _run_osascript(script)

    if result.returncode != 0:
        error_detail = scrub_pii(result.stderr.strip()) if result.stderr else "Unknown error"
        raise SendError(f"Failed to send file: {error_detail}")

    return True


def start_group(recipients: list[str], text: str) -> bool:
    """Start a new group conversation.

    Note: Group creation via AppleScript is less reliable than direct messages.
    Messages.app may not always create a new group conversation correctly.

    Args:
        recipients: List of phone numbers or email addresses (minimum 2).
        text: Initial message text.

    Returns:
        True if the group was created and message sent.

    Raises:
        SendError: If the group could not be created.
        MessagesError: If inputs are invalid.
    """
    if len(recipients) < 2:
        raise MessagesError("Group conversations require at least 2 recipients")

    for r in recipients:
        _validate_recipient(r)

    if not text or not text.strip():
        raise MessagesError("Initial message text cannot be empty")

    escaped_text = _escape_applescript(text)

    # Build AppleScript to create a new group conversation
    buddy_lines = []
    for r in recipients:
        escaped_r = _escape_applescript(r.strip())
        buddy_lines.append(f'        set end of theBuddies to buddy "{escaped_r}" of targetService')

    buddies_script = "\n".join(buddy_lines)

    script = f'''
    tell application "Messages"
        set targetService to 1st service whose service type = iMessage
        set theBuddies to {{}}
{buddies_script}
        set theChat to make new text chat with properties {{participants:theBuddies}}
        send "{escaped_text}" to theChat
    end tell
    '''

    result = _run_osascript(script)

    if result.returncode != 0:
        error_detail = scrub_pii(result.stderr.strip()) if result.stderr else "Unknown error"
        raise SendError(f"Failed to start group conversation: {error_detail}")

    return True
