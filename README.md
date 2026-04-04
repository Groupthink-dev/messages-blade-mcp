# Messages Blade MCP

A security-first, token-efficient MCP server for Apple Messages (iMessage) on macOS. 15 tools for conversations, search, contacts, attachments, and message delivery.

> **This MCP accesses your private message history.** Read the [Platform Fragility](#platform-fragility--risks), [Security Model](#security-model), and [Privacy](#privacy--pii-handling) sections before deploying.

## Why another iMessage MCP?

| | wyattjoh/imessage-mcp | mac_messages_mcp | imessage-query | steipete/imsg | **This** |
|---|---|---|---|---|---|
| **Tools** | ~4 (read-only) | ~5 (basic) | ~3 (query) | CLI (not MCP) | 15 (read + send) |
| **attributedBody** | No | No | No | Yes (Swift native) | Yes (typedstream decoder) |
| **Write safety** | Read-only | None | Read-only | N/A | Write gate + confirm gate |
| **Token cost** | JSON dumps | JSON dumps | JSON dumps | JSON (CLI) | Pipe-delimited, truncated |
| **Contact resolution** | No | No | No | Yes | Optional AddressBook |
| **Error PII handling** | None | None | None | None | Phone/email scrubbed from errors |
| **Tests** | Minimal | None | None | Yes | 140 unit tests |
| **Contract** | None | None | None | None | messages-v1 (10/10) |

`steipete/imsg` is the most capable tool in this space — it's a well-engineered Swift CLI with JSON output, watch mode, and E.164 normalisation. We recommend it for CLI use. This MCP builds on similar techniques (SQLite read + AppleScript send) but packages them as an MCP server with write gates, token efficiency, and contract conformance for agentic platforms.

## Platform Fragility & Risks

**Apple provides no official API for iMessage.** This MCP relies on two undocumented interfaces that Apple can break at any macOS update:

| Interface | What can break | Historical precedent |
|-----------|---------------|---------------------|
| `~/Library/Messages/chat.db` SQLite schema | Table structure, column names, date encoding | macOS Ventura moved message text from `text` column to `attributedBody` BLOB without notice |
| `tell application "Messages"` AppleScript | Dictionary changes, service type handling | Group chat handling varies between macOS versions |

**What this means in practice:**

- A macOS update could silently break message decoding — you'd get empty or garbled text until the typedstream parser is updated
- A macOS update could break the send bridge — AppleScript send could fail silently or target the wrong service
- The `attributedBody` binary format (NSArchiver typedstream) is a proprietary Apple encoding with no public specification — our decoder is based on community reverse-engineering
- There is no way to receive notifications of new messages programmatically (no event subscription, no webhook) — only polling via `messages_recent`

**Our mitigations:**

- Version-aware query paths detect macOS version and adjust SQL accordingly
- The typedstream decoder uses multiple fallback strategies (structural parsing → byte pattern → longest text run)
- All database access is read-only (`?mode=ro` + `PRAGMA query_only`) — we cannot corrupt chat.db even if our code has bugs
- Graceful degradation: if `attributedBody` decoding fails, the tool returns the message with a `[decode failed]` marker rather than crashing
- Test fixtures include known `attributedBody` blobs to catch regressions

**Bottom line:** This MCP will occasionally break on macOS updates. When it does, the failure mode is benign (unreadable messages, failed sends) rather than dangerous (data loss, corruption, silent mis-delivery). Pin to a tested macOS version in production and update the MCP after verifying each macOS upgrade.

## Platform Requirements

- **macOS 13 (Ventura) or later**
- **Full Disk Access (FDA)** — required to read `~/Library/Messages/chat.db`
- **TCC Automation** — required for send operations (macOS prompts on first use)

### Full Disk Access and Attack Surface Isolation

Full Disk Access is a broad macOS permission — it grants read access to Mail, Safari history, Photos, and other protected directories, not just Messages. How you grant FDA determines your attack surface:

**Option A: FDA on terminal emulator (simple, broad surface)**

Grant FDA to your terminal (Ghostty, iTerm2, Terminal.app). Every child process inherits it — all MCP servers, all shell commands, everything running in that terminal can read protected files. This is the simplest setup but the broadest grant.

**Option B: FDA on standalone process (recommended, isolated surface)**

Run messages-blade-mcp as a standalone HTTP server with its own FDA grant. Only the messages-blade-mcp binary can read protected files. Claude Code / the Sidereal daemon connects via HTTP transport — they never touch chat.db directly.

```bash
# Run as isolated HTTP server (only this process needs FDA)
MESSAGES_MCP_TRANSPORT=http MESSAGES_MCP_PORT=8770 messages-blade-mcp

# Claude Code connects via HTTP — no FDA needed on the terminal
{
  "mcpServers": {
    "messages": {
      "url": "http://127.0.0.1:8770/mcp"
    }
  }
}
```

Grant FDA to the `messages-blade-mcp` binary (or the Python interpreter running it) in System Settings > Privacy & Security > Full Disk Access. If using a Developer ID signed binary, the TCC grant persists across updates. Ad-hoc signed binaries (including Nix store paths) lose their grant on every rebuild.

**Option C: FDA on Sidereal daemon (if using daemon-routed MCP)**

If messages-blade-mcp is routed through the Sidereal daemon (`:9847/mcp`), the daemon process needs FDA. This also grants FDA to all other daemon-hosted MCPs (sidereal-blade, etc.). Acceptable if you trust all daemon-hosted MCPs, but broader than Option B.

**Recommendation:** Use Option B for production. The HTTP transport adds negligible latency for a local-only tool, and the FDA grant is scoped to exactly one binary.

## Privacy & PII Handling

This MCP reads your private messages and exposes them to an LLM. Understand what that means:

### What the LLM sees

- **Message content** — full text of messages returned by read tools. This is the tool's purpose; there is no way to make it useful without exposing content.
- **Phone numbers and emails** — contact identifiers in normal tool output. Required for the tool to be usable (you need to know who sent what).
- **Attachment metadata** — file names, MIME types, sizes. Never file content.

### What "PII scrubbing" does

PII scrubbing applies to **error messages only**, not normal tool output. When a tool call fails, the error response might contain input parameters or partial results. PII scrubbing uses regex patterns to replace phone numbers and email addresses in these error strings with `[REDACTED]` before they reach the LLM context.

This prevents accidental PII leakage in:
- Error responses forwarded to the LLM
- Log files written by the MCP transport layer
- Crash reports or stack traces

### What PII scrubbing does NOT do

- It does not anonymize normal tool output — phone numbers and message content are returned as-is
- It does not prevent the LLM from including message content in its responses to you
- It does not prevent the LLM provider from processing message content under their data retention policy
- It does not encrypt data in transit (MCP stdio/HTTP is localhost-only, not TLS)

### Recommendations

- **Read-only by default.** Leave `MESSAGES_WRITE_ENABLED` at `false` unless you specifically need send capability.
- **Audit LLM data policies.** Message content enters the LLM context window. If using a cloud LLM (Claude API, OpenAI), review their data retention and training policies.
- **Local inference for sensitive use.** If message privacy is paramount, route through a local model (LM Studio, Ollama) where content never leaves your machine.
- **Scope your queries.** Use `messages_chat` with a specific contact rather than `messages_recent` across all conversations. Smaller context = less exposure.

## Quick Start

### Install

```bash
# With uv (recommended)
uv tool install messages-blade-mcp

# Or from source
git clone https://github.com/groupthink-dev/messages-blade-mcp.git
cd messages-blade-mcp
make install
```

### Configure

```bash
# Read-only mode (default — no env vars needed, but FDA required)
messages-blade-mcp

# Enable sending (requires both env var AND per-call confirm=true)
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
      "env": {}
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
| `messages_attachment_info` | Single attachment detail (never reads file content) | Low |
| `messages_stats` | Aggregate stats: totals, date range, top contacts | Low |
| `messages_unread` | Unread count per conversation | Low |

### Write (3 tools — double-gated)

| Tool | Description |
|------|-------------|
| `messages_send` | Send a text message to a phone number or email |
| `messages_send_file` | Send a file attachment |
| `messages_start_group` | Start a new group conversation |

All write operations require **both** the environment variable gate (`MESSAGES_WRITE_ENABLED=true`) **and** a per-call confirmation parameter (`confirm=true`). Sending a message is irreversible — there is no unsend via this interface.

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
chats=42 | messages=12345 | handles=67 | attachments=890 | first=2020-01-01 | last=2026-03-16

# Contacts
+61412345678 | iMessage | messages=150 | last=2026-03-16T10:00:00+00:00

# Attachments
1 | photo.jpg | image/jpeg | 2.0MB | 2026-03-16T09:00:00+00:00
```

## Security Model

| Layer | Mechanism | What it protects against |
|-------|-----------|------------------------|
| **Full Disk Access** | macOS TCC gate | Unauthorised processes reading chat.db |
| **Read-only SQLite** | `?mode=ro` URI + `PRAGMA query_only` | Accidental or malicious writes to chat.db |
| **Write gate** | `MESSAGES_WRITE_ENABLED=true` env var | Unintentional message sends (default off) |
| **Confirm gate** | `confirm=true` per-call parameter | LLM sending messages without explicit request |
| **PII scrubbing** | Regex redaction on error paths | Phone/email leaking into logs and error context |
| **No attachment content** | Metadata only, never file bytes | Accidental exposure of photos/documents |
| **Input escaping** | AppleScript string escaping | Injection attacks via crafted recipient/message |
| **System osascript** | Uses `/usr/bin/osascript` | TCC churn with ad-hoc signed Nix binaries |
| **FDA isolation** | HTTP transport mode (Option B) | Over-granting FDA to entire terminal/daemon |

### What this does NOT protect against

- **LLM data exposure** — message content enters the LLM context. If you use a cloud provider, their data policies apply.
- **Prompt injection via messages** — a malicious message could contain text that an LLM interprets as instructions. This MCP does not sanitize message content (doing so would corrupt the data).
- **AppleScript race conditions** — if Messages.app is mid-send, a concurrent send via AppleScript could target the wrong conversation. Low probability but non-zero.
- **macOS schema changes** — a macOS update could cause silent decode failures. See [Platform Fragility](#platform-fragility--risks).

## Platform Constraints

| Constraint | Impact | Mitigation |
|------------|--------|-----------|
| macOS only | No Linux/Windows support | Clear error on non-macOS |
| FDA required | Cannot read chat.db without it | Descriptive error with grant instructions |
| No official API | Can break on macOS updates | Version-aware queries, graceful fallback |
| No FTS on chat.db | Search uses LIKE (slower on large DBs) | Limit parameter, date-ordered results |
| attributedBody format | Proprietary binary encoding | Multi-strategy decoder with fallback |
| AppleScript for sends | Requires TCC Automation grant | macOS prompts on first use |
| Group chat creation | Less reliable via AppleScript | Documented limitation |
| No real-time events | Cannot subscribe to new messages | Poll via `messages_recent` with `since` |
| Nix CDHash churn | FDA grant resets on rebuild | Sign binary, or use HTTP isolation |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MESSAGES_WRITE_ENABLED` | Enable send operations | `false` |
| `MESSAGES_DB_PATH` | Override chat.db path | `~/Library/Messages/chat.db` |
| `MESSAGES_MCP_TRANSPORT` | `stdio` or `http` | `stdio` |
| `MESSAGES_MCP_HOST` | HTTP bind address | `127.0.0.1` |
| `MESSAGES_MCP_PORT` | HTTP port | `8770` |
| `MESSAGES_MCP_API_TOKEN` | Bearer token for HTTP transport | _(none)_ |

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
├── server.py        — FastMCP 2.0 server, 15 tool definitions
├── database.py      — SQLite chat.db reader (read-only, async via to_thread)
├── typedstream.py   — NSArchiver attributedBody decoder (Ventura+)
├── applescript.py   — AppleScript send bridge (/usr/bin/osascript)
├── contacts.py      — Optional AddressBook/Contacts integration
├── models.py        — Config, write/confirm gates, PII scrubbing, exceptions
├── formatters.py    — Token-efficient pipe-delimited output
└── __main__.py      — Entry point
```

**Dependencies:** `fastmcp`, `pydantic`. No network dependencies — everything is local (SQLite + AppleScript).

## Sidereal Marketplace

This MCP conforms to the `messages-v1` service contract (10/10 operations):
- **Required (3/3):** chats, messages, search
- **Recommended (3/3):** chat, contacts, attachments
- **Optional (2/2):** stats, unread
- **Gated (2/2):** send, send_file

See `sidereal-plugin.yaml` for the full plugin manifest.

## License

MIT
