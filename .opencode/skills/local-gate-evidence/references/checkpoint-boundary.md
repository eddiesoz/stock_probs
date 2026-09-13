# Export and checkpoint boundary

A local-gate pass and an `EXP-*` checkpoint answer different questions. Never merge their results.

## Gate evidence

The local gate may prove deterministic tests, package/install/runtime behavior, browser/MCP checks,
migrations/backups, and measured performance for its exact revision and environment. It does not
export the session, review secrets, create a commit, push, or verify a remote revision.

## Export checkpoint evidence

An export checkpoint separately records:

1. the overwritten sanitized full-session export and successful parse;
2. message/part/byte/line inventory and SHA-256;
3. redaction count and canonical secret-pattern review;
4. local commit identity, parent, message, and UTC;
5. push result and exact remote-revision equality; and
6. named reviewer plus every unavailable field.

Only the coordinator-owned export gate may mutate Git or claim checkpoint completion. A gate
reviewer reports checkpoint fields as `Pending`, `Blocked`, or `Unavailable` when they were not
performed; a previous checkpoint does not satisfy a later one.
