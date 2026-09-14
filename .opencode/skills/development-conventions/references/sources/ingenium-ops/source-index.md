# Ingenium Operations

Operational patterns specific to the Ingenium MCP Server project itself — dashboard consistency, seeding, CRUD layering, and MCP tool parity.

## 🔴 HARD RULEs

- **ALL MCP tool operations must go through the API** — never write directly to the DB from MCP tool handlers.
- **Seeding is idempotent** — `INSERT OR IGNORE`. Re-running seed never overwrites existing data.
- **Dashboard components must use Tailwind CSS v4** — no CSS modules, no inline styles, no custom CSS files.

## Dashboard UI Consistency

- Pages render data as clickable cards → full-screen overlay (Overlay.tsx)
- Each card shows: name/title + truncated snippet + metadata tags
- Overlay shows: full detail with Preview/Source toggle (MarkdownViewer.tsx)
- Loading states: "Loading..." text
- Empty states: contextual message

## CRUD Layering

```
MCP Tool → REST API → Core Library → SQLite
```

Each layer validates and transforms. The MCP tool maps to a single route, the route calls a core function, the core function executes the DB query. No layer skips another.

## Idempotent Seeding

- Skills: `INSERT OR IGNORE INTO skills`
- Plugins: `INSERT OR IGNORE INTO plugins` + write to disk
- Agents: `INSERT OR IGNORE INTO agents` + write to disk
- After seed: `syncAllSkills()` / `syncAllAgents()` to restore all disk files

## References

- See `references/mcp-tool-parity.md` for ensuring every API route has a matching MCP tool
- See `references/layered-crud.md` for the 3-layer architecture pattern
- See `references/dashboard-ui.md` for component patterns
