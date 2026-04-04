# Messages Blade MCP

A security-first, token-efficient MCP server for Apple Messages (iMessage). 15 tools for conversations, search, contacts, attachments, and message delivery.

## Why another iMessage MCP?

| | wyattjoh/imessage-mcp | carterlasalle/mac_messages_mcp | hannesrudolph/imessage-query | steipete/imsg | **This** |
|---|---|---|---|---|---|
| **Tools** | ~4 (read-only) | ~5 (basic) | ~3 (query) | CLI, not MCP | 15 (comprehensive) |
| **attributedBody** | No | No | No | No | Yes (typedstream decoder) |
| **Write safety** | Read-only | None | Read-only | N/A | Write gate + confirm gate |
| **Token cost** | JSON dumps | JSON dumps | JSON dumps | N/A | Pipe-delimited, truncated |
| **Contact resolution** | No | No | No | No | AddressBook integration |
| **PII safety** | None | None | None | None | Scrubbed from all errors |
| **Tests** | Minimal | None | None | Yes | 100+ unit tests |
| **Contract** | None | None | None | None | messages-v1 |

**This MCP** is designed for agentic platforms that need:
- **Complete reads** -- conversations, messages, search, contacts, attachments, stats, and unread counts from chat.db
- **Safe writes** -- two-tier gating (env var + per-call confirm) for all send operations
- **attributedBody decoding** -- extracts text from NSArchiver typedstream blobs (macOS Ventura+)
- **Token efficiency** -- pipe-delimited output, text truncation, null-field omission
- **Contact resolution** -- optional AddressBook integration to resolve handles to display names
- **PII safety** -- phone numbers and emails scrubbed from all error messages

## Platform Requirements

- **macOS 13 (Ventura) or later** -- Messages database schema varies by version
- **Full Disk Access (FDA)** -- required for the terminal emulator to read `~/Library/Messages/chat.db`
- **TCC Automation** -- required for send operations (macOS prompts on first use)

### Granting Full Disk Access

1. Open **System Settings > Privacy & Security > Full Disk Access**
2. Click **+** and add your terminal emulator (Terminal.app, iTerm2, Ghostty, etc.)
3. Restart your terminal

Without FDA, all read tools will return an error explaining how to grant access.

## Quick Start

### Install

```bash
# With uv (recommended)
uv tool install messages-blade-mcp

# Or from source
git clone https://github.com/piersdd/messages-blade-mcp.git
cd messages-blade-mcp
make install
```

### Configure

```bash
# Read-only mode (default -- no env vars needed)
messages-blade-mcp

# Enable sending
export MESSAGES_WRITE_ENABLED="true"
messages-blade-mcp
```

### Claude Code Integration

```json
{
  "mcpServers": {
    "messages": {
      "command": "uvx",
      "args": ["messages-blade-mcp"],
      "env": {
        "MESSAGES_WRITE_ENABLED": "true"
      }
    }
  }
}
```

### Claude Desktop Integration

```json
{
  "mcpServers": {
    "messages": {
      "command": "uvx",
      "args": ["messages-blade-mcp"]
    }
  }
}
```

## Tools (15)

### Read (12 tools)

| Tool | Description | Token Cost |
|------|-------------|-----------|
| `messages_info` | System info: macOS version, FDA status, write gate, db stats | Low |
| `messages_chats` | List conversations with participants, service, unread count | Medium |
| `messages_chat` | Look up a conversation by ID or phone/email | Low |
| `messages_messages` | Get messages from a conversation (paginated) | Medium |
| `messages_recent` | Recent messages across all conversations | Medium |
| `messages_search` | Full-text search across all messages | Medium |
| `messages_contacts` | List known handles (phone, email, iCloud) | Medium |
| `messages_contact` | Handle detail with message count, send/receive stats | Low |
| `messages_attachments` | List attachment metadata from a conversation | Medium |
| `messages_attachment_info` | Single attachment detail (never reads content) | Low |
| `messages_stats` | Aggregate stats: totals, date range, top contacts | Low |
| `messages_unread` | Unread count per conversation | Low |

### Write (3 tools -- require `MESSAGES_WRITE_ENABLED=true` AND `confirm=true`)

| Tool | Description |
|------|-------------|
| `messages_send` | Send a text message to a phone number or email |
| `messages_send_file` | Send a file attachment |
| `messages_start_group` | Start a new group conversation |

All write operations require **both** the environment variable gate (`MESSAGES_WRITE_ENABLED=true`) and a per-call confirmation parameter (`confirm=true`). Messages cannot be unsent.

## Output Format

All output is pipe-delimited for token efficiency:

```
# Conversations
1 | +61412345678 | iMessage | last=2026-03-16T10:00:00+00:00 | unread=2
2 | Jane Smith | iMessage | participants=jane@example.com | last=2026-03-16T09:00:00+00:00

# Messages
42 | 2026-03-16T10:00:00+00:00 | +61412345678 | Hello, are you free tomorrow?
43 | 2026-03-16T10:05:00+00:00 | me | Yes, what time works?

# Search results
1 | Family Group | +61412345678 | 2026-03-15T10:00:00+00:00 | ...meeting at 3pm tomorrow...

# Statistics
chats=42 | messages=12345 | handles=67 | attachments=890 | first=2020-01-01 | last=2026-03-16 | top=+61412345678(500), jane@example.com(300)

# Contacts
+61412345678 | iMessage | messages=150 | last=2026-03-16T10:00:00+00:00

# Attachments
1 | photo.jpg | image/jpeg | 2.0MB | 2026-03-16T09:00:00+00:00
```

## Security Model

| Layer | Mechanism |
|-------|-----------|
| **Full Disk Access** | macOS TCC gate -- terminal must have FDA to read chat.db |
| **Read-only SQLite** | Database opened with `?mode=ro` URI + `PRAGMA query_only = ON` |
| **Write gate** | `MESSAGES_WRITE_ENABLED=true` env var required for any send operation |
| **Confirm gate** | `confirm=true` parameter required on every send (no defaults to true) |
| **PII scrubbing** | Phone numbers and emails redacted from all error messages |
| **No attachment content** | Attachment tools return metadata only -- never reads file bytes |
| **Input escaping** | All AppleScript inputs escaped to prevent injection |
| **System osascript** | Uses `/usr/bin/osascript` to avoid TCC churn with Nix binaries |

## Platform Constraints

| Constraint | Impact | Mitigation |
|------------|--------|-----------|
| macOS only | No Linux/Windows support | Clear error message on non-macOS |
| FDA required | Cannot read chat.db without it | Descriptive error with grant instructions |
| No FTS5 on chat.db | Search uses LIKE (slower) | Limit parameter, ordered by date |
| attributedBody format | Text column NULL on Ventura+ | Typedstream decoder with graceful fallback |
| AppleScript for sends | Requires TCC Automation grant | macOS prompts on first use |
| Group chat creation | Less reliable via AppleScript | Documented limitation |
| Read-only database | Cannot mark messages as read | By design -- no mutation of chat.db |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MESSAGES_WRITE_ENABLED` | Enable send operations | `false` |
| `MESSAGES_DB_PATH` | Override chat.db path | `~/Library/Messages/chat.db` |

## Development

```bash
# Install with dev deps
make install-dev

# Run tests
make test

# Coverage report
make test-cov

# Lint + format + type check
make check

# Run the server
make run
```

## Architecture

```
src/messages_blade_mcp/
├── server.py        -- FastMCP 2.0 server, 15 tool definitions
├── database.py      -- SQLite chat.db reader (read-only, async via to_thread)
├── typedstream.py   -- NSArchiver attributedBody decoder (Ventura+)
├── applescript.py   -- AppleScript send bridge (/usr/bin/osascript)
├── contacts.py      -- Optional AddressBook/Contacts integration
├── models.py        -- Config, write/confirm gates, PII scrubbing, exceptions
├── formatters.py    -- Token-efficient pipe-delimited output
└── __main__.py      -- Entry point
```

**Dependencies:** `fastmcp`, `pydantic`. No network dependencies -- everything is local (SQLite + AppleScript).

## Sidereal Marketplace

This MCP conforms to the `messages-v1` service contract (10/10 operations):
- **Required (3/3):** chats, messages, search
- **Recommended (3/3):** chat, contacts, attachments
- **Optional (2/2):** stats, unread
- **Gated (2/2):** send, send_file

See `sidereal-plugin.yaml` for the full plugin manifest.

## License

MIT
