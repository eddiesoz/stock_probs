# Layered CRUD Architecture

The Ingenium system uses a strict 3-layer architecture:

## Layer 1: MCP Tool (`ingenium-server/`)
- Receives tool call from OpenCode
- Validates required parameters
- Calls HTTP endpoint on the API
- Returns JSON response

## Layer 2: REST API (`ingenium-api/`)
- Receives HTTP request
- Auth middleware validates
- `requireProject()` resolves project name → UUID
- Calls core library function
- Returns standardized `{ data }` or `{ error }` envelope

## Layer 3: Core Library (`ingenium-core/`)
- Receives typed parameters
- Opens DB connection
- Executes SQL (wrapped in `execTransaction` for writes)
- Calls `checkpointAfterWrite()` after every 50 writes
- Returns typed object

## NEVER
- MCP tool calling core functions directly (bypasses API)
- API writing raw SQL (use core functions)
- Any layer modifying another layer's data without going through the chain
