"""Optional AddressBook/Contacts integration for resolving handle IDs to display names.

Reads from the macOS AddressBook SQLite database to resolve phone numbers
and email addresses to human-readable names. Falls back gracefully if the
database is inaccessible (TCC, missing, or schema change).

This module is optional — all core functionality works without it.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# Common paths for the AddressBook database on macOS
_ADDRESSBOOK_PATHS = [
    Path.home() / "Library" / "Application Support" / "AddressBook" / "AddressBook-v22.abcddb",
]


def _find_addressbook_db() -> Path | None:
    """Locate the AddressBook database file."""
    for path in _ADDRESSBOOK_PATHS:
        if path.exists():
            return path

    # Search in Sources directories
    sources_dir = Path.home() / "Library" / "Application Support" / "AddressBook" / "Sources"
    if sources_dir.exists():
        for source_dir in sources_dir.iterdir():
            db_path = source_dir / "AddressBook-v22.abcddb"
            if db_path.exists():
                return db_path

    return None


def resolve_contact_name(handle: str) -> str | None:
    """Resolve a phone number or email to a display name from the AddressBook.

    Args:
        handle: Phone number (e.g. +61412345678) or email address.

    Returns:
        The contact's display name, or None if not found or DB inaccessible.
    """
    db_path = _find_addressbook_db()
    if db_path is None:
        logger.debug("AddressBook database not found")
        return None

    try:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row

        # Normalize the handle for searching
        normalized = _normalize_handle(handle)

        # Search by phone number
        if "@" not in handle:
            name = _search_by_phone(conn, normalized)
            if name:
                conn.close()
                return name

        # Search by email
        name = _search_by_email(conn, handle)
        conn.close()
        return name

    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
        logger.debug("Cannot read AddressBook: %s", e)
        return None


def _normalize_handle(handle: str) -> str:
    """Strip formatting from a phone number for comparison."""
    return "".join(c for c in handle if c.isdigit() or c == "+")


def _search_by_phone(conn: sqlite3.Connection, phone: str) -> str | None:
    """Search AddressBook for a contact by phone number."""
    try:
        # Try to match against the ZABCDPHONENUMBER table
        # The phone number is stored in ZFULLNUMBER
        query = """
            SELECT
                r.ZFIRSTNAME, r.ZLASTNAME, r.ZORGANIZATION
            FROM ZABCDRECORD r
            JOIN ZABCDPHONENUMBER p ON p.ZOWNER = r.Z_PK
            WHERE REPLACE(REPLACE(REPLACE(REPLACE(p.ZFULLNUMBER, ' ', ''), '-', ''), '(', ''), ')', '') LIKE ?
        """
        # Try with and without the + prefix
        for search in [f"%{phone}", f"%{phone.lstrip('+')}"]:
            row = conn.execute(query, (search,)).fetchone()
            if row:
                return _format_name(row)
    except sqlite3.OperationalError:
        # Schema may differ across macOS versions
        logger.debug("Phone search query failed — schema may differ")

    return None


def _search_by_email(conn: sqlite3.Connection, email: str) -> str | None:
    """Search AddressBook for a contact by email address."""
    try:
        query = """
            SELECT
                r.ZFIRSTNAME, r.ZLASTNAME, r.ZORGANIZATION
            FROM ZABCDRECORD r
            JOIN ZABCDEMAILADDRESS e ON e.ZOWNER = r.Z_PK
            WHERE LOWER(e.ZADDRESS) = LOWER(?)
        """
        row = conn.execute(query, (email,)).fetchone()
        if row:
            return _format_name(row)
    except sqlite3.OperationalError:
        logger.debug("Email search query failed — schema may differ")

    return None


def _format_name(row: sqlite3.Row) -> str | None:
    """Format a contact name from first/last/organization fields."""
    first = row["ZFIRSTNAME"] or ""
    last = row["ZLASTNAME"] or ""
    org = row["ZORGANIZATION"] or ""

    name = f"{first} {last}".strip()
    if name:
        return name
    if org:
        return org
    return None
