---
title: "HTTP Status Codes — Be Precise, Never Default to 200 or 500"
impact: HIGH
impactDescription: "Prevents ambiguous API responses that break HTTP clients, caches, and monitoring systems"
tags: [api, http, status-codes, error-handling]
---

## HTTP Status Codes — Be Precise

Return the most specific status code available. Don't default to 200 or 500.

```text
2xx — Success
  200 OK            — Standard success (GET, PATCH)
  201 Created       — Resource created (POST). MUST include Location header
  202 Accepted      — Async processing started. Return status endpoint
  204 No Content    — Success, no body (DELETE)

3xx — Redirection
  301 Moved Permanently
  304 Not Modified  — Cached response still valid (ETag/If-None-Match)

4xx — Client Error
  400 Bad Request   — Malformed input (validation errors)
  401 Unauthorized  — Missing or invalid credentials
  403 Forbidden     — Authenticated but not authorized
  404 Not Found     — Resource doesn't exist
  409 Conflict      — Resource state conflict (duplicate, version mismatch)
  422 Unprocessable — Semantic validation failure (well-formed but wrong)
  429 Too Many Requests — Rate limit exceeded

5xx — Server Error
  500 Internal Error — Unexpected failure (bug). Never return by default
  502 Bad Gateway   — Upstream returned invalid response
  503 Unavailable   — Temporarily down (maintenance, overload)
  504 Gateway Timeout — Upstream didn't respond in time
```

- **Never return 500 by catching and swallowing.** 500 means "bug."
- **Never return 200 with an error message.** Breaks every HTTP client, cache, and monitoring system.
- **401 vs 403**: 401 = "who are you?" (missing auth). 403 = "I know who you are, but no."
