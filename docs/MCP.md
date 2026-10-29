# Using ZettNAS from AI clients (MCP)

ZettNAS is a [Model Context Protocol](https://modelcontextprotocol.io) server. AI clients
such as Claude Code, Claude Desktop, Cursor or Open WebUI can then read your NAS's
status, search your indexed files and propose changes.

- **Address:** `http://<nas-address>:8082/api/mcp` (Streamable HTTP).
- **Sign-in:** an API token from **Security → API Tokens**, sent as
  `Authorization: Bearer <token>`. The client gets the permissions of the token's
  account, so a token for a non-admin account only sees that account's tools and files.

## Limit what a client can reach

- **Folders.** When you make the token, list the folders it may reach under **Only these
  folders**. A client with that token can then search and open nothing outside them, even
  if the token belongs to an administrator; leave the list empty for every folder the
  account can open. The folders are checked by path, without waking sleeping drives.
- **What it can do.** A token never has more rights than its account, and you can make one
  with fewer.
- **What is connected.** Security → API Tokens shows, for each token, when it was last used,
  from which address and, for MCP clients, which client (for example "Cursor 1.4", as the
  client names itself). **Revoke** cuts a client off at once.
- **Settings to paste.** When a token is made, ZettNAS shows it once together with ready
  settings for Claude Code, Cursor and Claude Desktop, filled in with this server's address.

## What a client can do

The client sees the same tools as Ask Zetty, minus web search and weather:
system status, disks (without waking sleeping ones), fans, storage, network,
containers, a calculator, and search over your indexed documents and photos.

Tools that change something (fan profile, starting or stopping a container, indexing)
never run directly. The client gets a link such as
`http://<nas>:8082/?confirm-action=…`. You open it in ZettNAS, read what will happen, and
click **Confirm**. Links expire after 10 minutes and only work for the same account.

Every call, from the chat or MCP, is written to the security audit log
(`ai.tool.call` and `ai.tool.confirmed`).

## Connect a client

**Claude Code**

```bash
claude mcp add --transport http zettnas http://<nas-address>:8082/api/mcp --header "Authorization: Bearer <token>"
```

**Cursor** (`~/.cursor/mcp.json`)

```json
{ "mcpServers": { "zettnas": { "url": "http://<nas-address>:8082/api/mcp",
  "headers": { "Authorization": "Bearer <token>" } } } }
```

**Claude Desktop and other clients that only start local servers:** use the
`mcp-remote` bridge.

```json
{ "mcpServers": { "zettnas": { "command": "npx",
  "args": ["mcp-remote", "http://<nas-address>:8082/api/mcp", "--header", "Authorization: Bearer <token>"] } } }
```

Use HTTPS (a reverse proxy or Tailscale Serve) when the client isn't on your home
network: the token travels with every request.
