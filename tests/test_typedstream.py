"""Tests for typedstream — NSArchiver attributedBody decoder."""

from __future__ import annotations

import struct

from messages_blade_mcp.typedstream import (
    _looks_like_text,
    _try_decode_utf8,
    decode_attributed_body,
)

# ---------------------------------------------------------------------------
# Synthetic test fixtures
# ---------------------------------------------------------------------------


def _make_typedstream_blob(text: str, use_short_length: bool = True) -> bytes:
    """Create a synthetic typedstream-like blob containing the given text.

    This mimics the structure of NSArchiver-encoded NSMutableAttributedString
    as used by Messages.app.
    """
    # typedstream magic header
    header = b"streamtyped"

    # Version and arch bytes (simplified)
    version = b"\x81\x03\x01\x01"

    # Class hierarchy
    classes = (
        b"\x84\x84\x01"
        b"NSMutableAttributedString\x00"
        b"NSAttributedString\x00"
        b"NSObject\x00"
        b"\x85\x84\x01"
        b"NSMutableString\x00"
        b"NSString\x00"
    )

    # Encode the text with length prefix
    text_bytes = text.encode("utf-8")
    text_len = len(text_bytes)

    if use_short_length and text_len < 128:
        # Single-byte length
        length_prefix = bytes([text_len])
    else:
        # Multi-byte length (0x81 + 2-byte LE)
        length_prefix = b"\x81" + struct.pack("<H", text_len)

    # Some padding/attributes after the text
    suffix = b"\x86\x84\x00\x00"

    return header + version + classes + length_prefix + text_bytes + suffix


def _make_simple_blob(text: str) -> bytes:
    """Create a simpler blob with text after the NSString marker."""
    header = b"streamtyped\x81\x03\x01\x01"
    marker = b"NSString\x00"
    text_bytes = text.encode("utf-8")
    length = bytes([len(text_bytes)])
    return header + marker + b"\x84\x01" + length + text_bytes + b"\x86"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDecodeAttributedBody:
    def test_none_input(self) -> None:
        assert decode_attributed_body(None) is None  # type: ignore[arg-type]

    def test_empty_bytes(self) -> None:
        assert decode_attributed_body(b"") is None

    def test_random_bytes(self) -> None:
        """Random bytes should return None, not crash."""
        import os

        result = decode_attributed_body(os.urandom(256))
        # May return None or some garbage string — should not raise
        assert result is None or isinstance(result, str)

    def test_short_text(self) -> None:
        blob = _make_typedstream_blob("Hello!")
        result = decode_attributed_body(blob)
        assert result is not None
        assert "Hello!" in result

    def test_longer_text(self) -> None:
        text = "This is a longer message that spans multiple words and should be decoded correctly."
        blob = _make_typedstream_blob(text)
        result = decode_attributed_body(blob)
        assert result is not None
        assert "longer message" in result

    def test_unicode_text(self) -> None:
        text = "Hello from Australia! Here's an emoji test"
        blob = _make_typedstream_blob(text)
        result = decode_attributed_body(blob)
        # May or may not decode the emoji perfectly, but should get the text
        assert result is not None
        assert "Australia" in result

    def test_simple_blob(self) -> None:
        blob = _make_simple_blob("Quick test message")
        result = decode_attributed_body(blob)
        assert result is not None
        assert "Quick test" in result

    def test_multi_byte_length(self) -> None:
        """Test with text longer than 127 bytes (requires multi-byte length)."""
        text = "A" * 200
        blob = _make_typedstream_blob(text, use_short_length=False)
        result = decode_attributed_body(blob)
        assert result is not None
        assert "A" * 50 in result

    def test_non_typedstream_blob(self) -> None:
        """A blob without the typedstream header should still try fallback."""
        blob = b"\x00\x01\x02Hello world\x00\x03"
        result = decode_attributed_body(blob)
        # Fallback heuristic may or may not find text
        assert result is None or isinstance(result, str)


class TestLooksLikeText:
    def test_normal_text(self) -> None:
        assert _looks_like_text("Hello, how are you?") is True

    def test_class_name(self) -> None:
        assert _looks_like_text("NSMutableAttributedString") is False

    def test_empty_string(self) -> None:
        assert _looks_like_text("") is False

    def test_mostly_printable(self) -> None:
        assert _looks_like_text("Good morning!") is True

    def test_numbers_and_punctuation(self) -> None:
        assert _looks_like_text("Call me at 3pm. Thanks!") is True


class TestTryDecodeUtf8:
    def test_valid_utf8(self) -> None:
        assert _try_decode_utf8(b"Hello") == "Hello"

    def test_invalid_utf8(self) -> None:
        assert _try_decode_utf8(b"\xff\xfe\xfd") is None

    def test_with_null_bytes(self) -> None:
        result = _try_decode_utf8(b"Hello\x00World")
        assert result is not None
        assert "Hello" in result
        assert "World" in result

    def test_empty(self) -> None:
        assert _try_decode_utf8(b"") is None

    def test_whitespace_only(self) -> None:
        assert _try_decode_utf8(b"   ") is None
