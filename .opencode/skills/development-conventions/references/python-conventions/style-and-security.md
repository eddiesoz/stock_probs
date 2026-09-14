---
title: "Style, Security, and Framework Conventions — File Organization, Naming, Error Handling, Security"
impact: MEDIUM
impactDescription: "Ensures consistent code style, secure coding practices, and framework-specific patterns"
tags: [python, style, security, naming, error-handling, django, fastapi, flask]
---

## Style, Security, and Framework Conventions

### File Organization

- **Package structure:** `src/` layout (`src/package_name/`) for libraries and larger projects. Flat `package_name/` for small apps.
- **`__init__.py` files are for re-exporting the public API,** not for logic.
- **One class per file (usually).** Small helper classes co-located with their primary class.
- **`constants.py`** for module-level constants.
- **`exceptions.py`** for custom exception classes, co-located in the relevant package.

### Naming Conventions

- **PascalCase:** `UserService`, `ValidationError`. No acronyms: `HttpClient` not `HTTPClient`.
- **snake_case:** `get_user_by_id`, `is_active`, `MAX_RETRIES`.
- **No single-letter variables** except `i`/`j` for loop indices and `x`/`y` for coordinates.
- **No abbreviations.** `config` not `cfg`, `response` not `resp`.
- **Private members:** single leading underscore `_internal_method`.
- **Constants:** UPPER_CASE at module level.

### Error Handling

```python
class ValidationError(AppError):
    """Raised when input validation fails."""

def process_payment(amount: Decimal) -> PaymentResult:
    if amount <= 0:
        raise ValidationError(f"Amount must be positive, got {amount}")
    ...

# Catch specific exceptions, not bare except:
try:
    result = process_payment(amount)
except ValidationError as e:
    logger.warning("Payment rejected", extra={"error": str(e)})
    raise  # Re-raise if caller can't handle it
```

- **Never `except:` or `except Exception`** without re-raising.
- **Raise specific exception types,** not `ValueError` for everything.
- **Wrap external errors** with context: `raise DatabaseError(...) from e`.
- **Use `logging` module** — never `print()` in production code.

### Django / Flask / FastAPI Addenda

- **Django:** Class-Based Views for CRUD, Function-Based for custom logic
- **FastAPI:** Pydantic models for request/response, dependency injection for shared logic
- **Flask:** Blueprints for modularity, application factory pattern

### Secure Coding

- **No secrets in code.** Use `os.environ` or `python-dotenv` for config.
- **Validate all input.** API handlers, CLI arguments, file uploads — sanitize before processing.
- **SQL: parameterized queries only.** No string interpolation.
- **Never `eval()` or `exec()` on user input.**
- **Hash passwords:** `bcrypt` or `argon2`, never MD5/SHA1.
