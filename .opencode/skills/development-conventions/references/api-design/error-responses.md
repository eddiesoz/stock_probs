---
title: "Error Response Shape and Versioning — Standardize All Error Output"
impact: HIGH
impactDescription: "Ensures all API consumers can parse errors uniformly; prevents internal information leaks"
tags: [api, errors, responses, versioning]
---

## Error Response Shape — Standardize

Every error response MUST use the same structure.

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable description of what went wrong",
    "details": [
      {
        "field": "email",
        "reason": "must be a valid email address",
        "value": "not-an-email"
      }
    ],
    "requestId": "req_a1b2c3d4"
  }
}
```

- **`code`**: machine-readable, stable, uppercase with underscores
- **`message`**: human-readable, safe to show in UI
- **`details`**: array of field-level errors for validation failures
- **`requestId`**: correlation ID for debugging
- **Never leak internals**: No SQL errors, stack traces, file paths

## Versioning

```text
# URL path versioning (most common, simplest to cache/route)
GET /api/v1/users

# Header versioning (cleaner URLs, harder to test in browser)
GET /api/users
Accept: application/vnd.myapp.v2+json
```

- **URL path versioning** is the safe default
- **Major version only**: `v1`, `v2`, not `v2.1.3`
- **Never break a published version**
- Deprecation: set `Sunset` and `Deprecation` headers
