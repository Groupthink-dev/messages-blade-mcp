"""Decode Apple's NSArchiver typedstream binary format to extract plain text.

Messages.app on macOS Ventura+ stores message text in the ``attributedBody``
column as an ``NSMutableAttributedString`` encoded via NSArchiver's typedstream
format. When the ``text`` column is NULL, this decoder extracts the plain text
content.

The typedstream format is complex and underdocumented. Rather than implementing
a full parser, we use a series of heuristics that reliably extract text from
the specific encoding used by Messages.app.
"""

from __future__ import annotations

import logging
import struct

logger = logging.getLogger(__name__)

# typedstream magic header
_TYPEDSTREAM_MAGIC = b"streamtyped"

# Known markers that appear before the text content in Messages attributedBody blobs
_TEXT_MARKERS = [
    b"NSString",
    b"NSMutableString",
    b"NSMutableAttributedString",
    b"NSAttributedString",
]


def decode_attributed_body(blob: bytes) -> str | None:
    """Extract plain text from an NSArchiver-encoded attributedBody blob.

    Args:
        blob: Raw bytes from the ``attributedBody`` column in chat.db.

    Returns:
        The decoded plain text string, or None if decoding fails.
    """
    if not blob:
        return None

    try:
        return _decode_typedstream(blob)
    except Exception:
        logger.debug("typedstream decode failed, trying fallback heuristics")

    try:
        return _decode_fallback(blob)
    except Exception:
        logger.debug("fallback decode also failed")

    return None


def _decode_typedstream(blob: bytes) -> str | None:
    """Primary decoder: parse the typedstream structure.

    The typedstream format for Messages attributedBody typically contains:
    1. A magic header ("streamtyped" or "typedstream")
    2. Version and endianness bytes
    3. Class hierarchy descriptions (NSMutableAttributedString, etc.)
    4. The actual text content as a length-prefixed UTF-8 string

    The text content appears after the class descriptions. It is preceded by
    a length indicator:
    - For strings < 128 bytes: single byte length
    - For strings >= 128 bytes: 0x81 followed by a 2-byte little-endian length
    - For strings >= 32768 bytes: 0x82 followed by a 4-byte little-endian length (rare)
    """
    # Verify this looks like a typedstream
    if _TYPEDSTREAM_MAGIC not in blob[:20] and b"streamtyped" not in blob[:20]:
        return None

    # Strategy 1: Look for the NSString/NSMutableString class reference,
    # then find the length-prefixed string that follows
    for marker in _TEXT_MARKERS:
        idx = blob.find(marker)
        if idx == -1:
            continue

        # Scan forward from the marker looking for the text content.
        # The text typically appears within ~50 bytes after the last class marker.
        search_start = idx + len(marker)
        result = _extract_length_prefixed_string(blob, search_start, search_start + 200)
        if result:
            return result

    # Strategy 2: Look for a length-prefixed UTF-8 string after common byte patterns
    # In Messages blobs, the text often follows the byte sequence \x84\x01
    for pattern in [b"\x84\x01", b"\x84\x84", b"\x69\x01"]:
        idx = blob.find(pattern)
        if idx != -1:
            result = _extract_length_prefixed_string(blob, idx + len(pattern), idx + len(pattern) + 200)
            if result:
                return result

    return None


def _extract_length_prefixed_string(blob: bytes, start: int, end: int) -> str | None:
    """Scan a byte range for a length-prefixed UTF-8 string.

    Tries multiple length-encoding formats used by typedstream.
    """
    end = min(end, len(blob))
    pos = start

    while pos < end - 1:
        byte = blob[pos]

        # Skip zero bytes and small control bytes
        if byte == 0:
            pos += 1
            continue

        # Multi-byte length: 0x81 + 2-byte LE length
        if byte == 0x81 and pos + 3 <= len(blob):
            length = struct.unpack_from("<H", blob, pos + 1)[0]
            str_start = pos + 3
            if 1 <= length <= 100000 and str_start + length <= len(blob):
                candidate = _try_decode_utf8(blob[str_start : str_start + length])
                if candidate and _looks_like_text(candidate):
                    return candidate
            pos += 1
            continue

        # Multi-byte length: 0x82 + 4-byte LE length
        if byte == 0x82 and pos + 5 <= len(blob):
            length = struct.unpack_from("<I", blob, pos + 1)[0]
            str_start = pos + 5
            if 1 <= length <= 1000000 and str_start + length <= len(blob):
                candidate = _try_decode_utf8(blob[str_start : str_start + length])
                if candidate and _looks_like_text(candidate):
                    return candidate
            pos += 1
            continue

        # Single-byte length (1-127)
        if 1 <= byte <= 127:
            str_start = pos + 1
            if str_start + byte <= len(blob):
                candidate = _try_decode_utf8(blob[str_start : str_start + byte])
                if candidate and _looks_like_text(candidate) and len(candidate) >= 1:
                    return candidate

        pos += 1

    return None


def _decode_fallback(blob: bytes) -> str | None:
    """Fallback heuristic: split on known delimiters.

    Some Messages blobs encode text between specific byte patterns.
    Common patterns observed:
    - Text between \\x01+\\x00 markers
    - Text terminated by \\x86 or \\x84 bytes
    """
    # Try splitting on common terminators
    for terminator in [b"\x86\x84", b"\x86\x86", b"\x00\x86"]:
        parts = blob.split(terminator)
        for part in parts:
            # Look at the last ~500 bytes of each part
            tail = part[-500:] if len(part) > 500 else part
            candidate = _try_extract_readable_tail(tail)
            if candidate and len(candidate) >= 2:
                return candidate

    # Last resort: find the longest run of printable UTF-8 in the blob
    return _find_longest_text_run(blob)


def _find_longest_text_run(blob: bytes) -> str | None:
    """Find the longest contiguous run of printable text in the blob.

    Used as a last resort when structured decoding fails.
    """
    best = ""
    current_start = 0
    i = 0

    while i < len(blob):
        # Try to decode from this position
        for end in range(min(i + 5000, len(blob)), i, -1):
            candidate = _try_decode_utf8(blob[i:end])
            if candidate and _looks_like_text(candidate) and len(candidate) > len(best):
                best = candidate
                current_start = end
                break
        i = max(i + 1, current_start)

    return best if len(best) >= 2 else None


def _try_extract_readable_tail(data: bytes) -> str | None:
    """Try to extract readable text from the tail of a byte sequence."""
    # Work backward from the end to find where readable text starts
    text_bytes = bytearray()
    for b in reversed(data):
        if 32 <= b <= 126 or b in (0x0A, 0x0D, 0xC0, 0xC1):  # printable ASCII + newlines
            text_bytes.append(b)
        elif text_bytes:
            break

    if not text_bytes:
        return None

    text_bytes.reverse()
    candidate = _try_decode_utf8(bytes(text_bytes))
    return candidate if candidate and _looks_like_text(candidate) else None


def _try_decode_utf8(data: bytes) -> str | None:
    """Attempt UTF-8 decode, return None on failure."""
    try:
        text = data.decode("utf-8")
        # Strip null bytes and control characters (except newline, tab)
        text = "".join(c for c in text if c == "\n" or c == "\t" or (ord(c) >= 32 and ord(c) != 127))
        return text.strip() if text.strip() else None
    except (UnicodeDecodeError, ValueError):
        return None


def _looks_like_text(s: str) -> bool:
    """Heuristic: does this string look like actual message text?

    Rejects strings that are mostly non-printable, class names, or binary garbage.
    """
    if not s or len(s) < 1:
        return False

    # Reject known class name fragments
    class_names = {"NSMutableAttributedString", "NSAttributedString", "NSString", "NSMutableString", "NSObject"}
    if s in class_names:
        return False

    # Count printable characters (letters, digits, common punctuation, spaces)
    printable = sum(1 for c in s if c.isalnum() or c in " .,!?;:'-\"()\n\t@#$%&*+=/")
    ratio = printable / len(s) if s else 0

    # Require at least 60% printable content
    return ratio >= 0.6
