"""Shared models, configuration, write/confirm gates, and PII scrubbing for Messages Blade MCP."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Default chat.db path on macOS
DEFAULT_DB_PATH = str(Path.home() / "Library" / "Messages" / "chat.db")

# Default limits for list operations (token efficiency)
DEFAULT_LIMIT = 50


@dataclass
class MessagesConfig:
    """Configuration for the Messages MCP server."""

    db_path: str = field(default_factory=lambda: DEFAULT_DB_PATH)
    write_enabled: bool = False


def resolve_config() -> MessagesConfig:
    """Resolve configuration from environment variables."""
    db_path = os.environ.get("MESSAGES_DB_PATH", DEFAULT_DB_PATH)
    write_enabled = os.environ.get("MESSAGES_WRITE_ENABLED", "").lower() == "true"
    return MessagesConfig(db_path=db_path, write_enabled=write_enabled)


def is_write_enabled() -> bool:
    """Check if write operations are enabled via env var."""
    return os.environ.get("MESSAGES_WRITE_ENABLED", "").lower() == "true"


def check_write_gate(config: MessagesConfig) -> str | None:
    """Return an error message if writes are disabled, else None."""
    if not config.write_enabled:
        return "Error: Write operations are disabled. Set MESSAGES_WRITE_ENABLED=true to enable sending messages."
    return None


def check_confirm_gate(confirm: bool, action: str) -> str | None:
    """Return an error message if confirm is not set, else None.

    ALL write operations require explicit confirm=true.
    """
    if not confirm:
        return (
            f"Error: {action} requires explicit confirmation. "
            "Set confirm=true to proceed. This is a safety gate — "
            "messages cannot be unsent."
        )
    return None


# ---------------------------------------------------------------------------
# PII scrubbing
# ---------------------------------------------------------------------------

# Phone number patterns (international, US, AU, etc.)
_PHONE_PATTERNS = [
    re.compile(r"\+\d{10,15}"),  # International: +61412345678
    re.compile(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"),  # US: 555-123-4567
    re.compile(r"\b\d{4}[-.\s]\d{3}[-.\s]\d{3}\b"),  # AU: 0412 345 678
    re.compile(r"\b\d{10,11}\b"),  # Unformatted: 0412345678 or 15551234567
]

# Email pattern
_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")


def scrub_pii(text: str) -> str:
    """Replace phone numbers and email addresses with [REDACTED].

    Used in error messages only — normal tool output intentionally includes
    phone numbers and emails for usability.
    """
    for pattern in _PHONE_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    text = _EMAIL_PATTERN.sub("[REDACTED]", text)
    return text


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MessagesError(Exception):
    """Base exception for Messages MCP errors. PII is scrubbed from string representation."""

    def __str__(self) -> str:
        return scrub_pii(super().__str__())


class FDAError(MessagesError):
    """Raised when Full Disk Access is not granted.

    macOS requires FDA for the terminal emulator to read ~/Library/Messages/chat.db.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        super().__init__(
            f"Cannot open Messages database at {db_path}. "
            "Full Disk Access (FDA) is required. "
            "Grant it in System Settings > Privacy & Security > Full Disk Access "
            "for your terminal emulator (Terminal.app, iTerm2, etc.)."
        )


class SendError(MessagesError):
    """Raised when a message send operation fails via AppleScript."""

    pass
