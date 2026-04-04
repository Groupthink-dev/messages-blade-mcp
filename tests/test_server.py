"""Tests for server — tool registration and integration."""

from __future__ import annotations

from messages_blade_mcp.server import mcp

# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Verify all 15 tools are registered with the FastMCP server."""

    @staticmethod
    async def _get_tool_names() -> list[str]:
        """Extract registered tool names from the MCP server via async API."""
        tools = await mcp.list_tools()
        return [t.name for t in tools]

    async def test_read_tools_registered(self) -> None:
        """All 12 read tools should be registered."""
        tool_names = await self._get_tool_names()
        expected_read_tools = [
            "messages_info",
            "messages_chats",
            "messages_chat",
            "messages_messages",
            "messages_recent",
            "messages_search",
            "messages_contacts",
            "messages_contact",
            "messages_attachments",
            "messages_attachment_info",
            "messages_stats",
            "messages_unread",
        ]
        for tool in expected_read_tools:
            assert tool in tool_names, f"Read tool '{tool}' not registered"

    async def test_write_tools_registered(self) -> None:
        """All 3 write tools should be registered."""
        tool_names = await self._get_tool_names()
        expected_write_tools = [
            "messages_send",
            "messages_send_file",
            "messages_start_group",
        ]
        for tool in expected_write_tools:
            assert tool in tool_names, f"Write tool '{tool}' not registered"

    async def test_total_tool_count(self) -> None:
        """Exactly 15 tools should be registered."""
        tool_names = await self._get_tool_names()
        assert len(tool_names) == 15, f"Expected 15 tools, got {len(tool_names)}: {tool_names}"

    def test_server_name(self) -> None:
        """Server should be named MessagesBlade."""
        assert mcp.name == "MessagesBlade"

    def test_server_has_instructions(self) -> None:
        """Server should have instructions set."""
        assert mcp.instructions is not None
        assert "Messages" in mcp.instructions
