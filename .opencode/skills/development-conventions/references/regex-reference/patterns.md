---
title: "Regex Reference — Common Patterns, Escaping, Backtracking Prevention"
impact: HIGH
impactDescription: "Prevents catastrophic backtracking, language-specific escaping bugs, and wrong pattern selections"
tags: [regex, patterns, escaping, backtracking, safety]
---

## Regex Reference

## 🔴 HARD RULE — Prevent Catastrophic Backtracking

Nested quantifiers with overlapping matches can cause regex engines to run exponentially. Apply these rules to every non-trivial regex:

| Dangerous pattern | Why | Fix |
|------------------|-----|-----|
| `(a+)+` | Nested quantifiers — `+` inside `+` | `a+` (remove outer quantifier) |
| `(a|)*` | Alternation inside `*` | Anchor with `^...$` and remove `*` |
| `(a|b)*` on long string with no match | Every position tries every alternation | Make atomic: `(?>a|b)*` or rewrite |
| `a.*b` on very long line | `.*` backtracks character by character | `a[^a]*b` or `a.*?b` with anchoring |
| `(\d+,)+\d+` on malformed input | `+` inside `+` with comma | `\d+(,\d+)*` (unroll the loop) |

Always test complex regexes before deploying.

## Common Patterns

| Pattern | Regex | Notes |
|---------|-------|-------|
| Email (basic) | `^[\w.+-]+@[\w-]+\.[\w.-]+$` | Covers 95% of cases. Check DNS MX for production. |
| URL | `^https?://[\w.-]+(:\d+)?(/[\w./%-]*)?$` | HTTP/HTTPS only. Omit anchors for extraction. |
| Semver | `^\d+\.\d+\.\d+$` | For pre-release: `^\d+\.\d+\.\d+(-[\w.]+)?(\+[\w.]+)?$` |
| IPv4 | `^(?:\d{1,3}\.){3}\d{1,3}$` | Format only. Check range after match. |
| Date ISO 8601 | `^\d{4}-\d{2}-\d{2}$` | Full datetime: `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z\|[+-]\d{2}:\d{2})$` |
| Hex color | `^#([0-9a-fA-F]{3}\|[0-9a-fA-F]{6})$` | Supports `#rgb` and `#rrggbb` |
| Slug | `^[a-z0-9]+(-[a-z0-9]+)*$` | Lowercase alphanumeric with hyphens |
| UUID v4 | `^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$` | Version/variant markers at positions 13 and 17 |

## Language-Specific Escaping

### JavaScript
```javascript
// Regex literals avoid one layer of escaping
const re = /^\w+@\w+\.\w+$/;
// String constructor needs double-escaping
const re2 = new RegExp("^\\w+@\\w+\\.\\w+$");
```
**Gotcha:** Literal syntax doesn't support variable interpolation. Use `new RegExp(...)` but double-escape.

### Python
```python
import re
# Raw strings avoid double escaping (USE THESE)
pattern = r"^\w+@\w+\.\w+$"
re.match(pattern, email)
```
**Gotcha:** `re` module doesn't support variable-length lookbehind. Raw strings are mandatory.

### Rust
```rust
use regex::Regex;
let re = Regex::new(r"^\w+@\w+\.\w+$").unwrap();
```
**Gotcha:** Rust's `regex` crate doesn't support backreferences or lookahead/lookbehind.

### Go
```go
import "regexp"
re := regexp.MustCompile(`^\w+@\w+\.\w+$`)
```
**Gotcha:** Go's `regexp` uses RE2 — no backreferences, no lookahead/lookbehind, no possessive quantifiers. Guarantees linear time.

### Bash
```bash
grep -E '^\w+@\w+\.\w+$' emails.txt
if [[ "$email" =~ ^[a-z]+@[a-z]+\.[a-z]+$ ]]; then echo "valid"; fi
```
**Gotcha:** Bash `=~` uses POSIX ERE — no `\d` (use `[0-9]`), no `\w` (use `[a-zA-Z0-9_]`).

## Model Notes

- **7B-9B models**: Most likely to forget escaping rules. Always check the language's escaping section.
- **14B-27B models**: Better at pattern logic but prone to catastrophic backtracking with nested quantifiers.
- **All local models**: Use the Common Patterns table as a template library. Don't write regexes from scratch for common validations.
- **When regex seems complex**: Consider string methods or dedicated parsers instead.
