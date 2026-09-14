---
title: "Type Hints and Docstrings — Mandatory Typing, Google-Style Documentation"
impact: HIGH
impactDescription: "Prevents type-related bugs and makes code self-documenting"
tags: [python, type-hints, docstrings, google-style, annotations]
---

## Type Hints — Mandatory

Every function must have complete type annotations.

```python
# Bad — no types, returns None on error
def get_user(user_id):
    ...

# Good — complete types, explicit return
def get_user(user_id: int) -> User | None:
    """Return the user with the given ID, or None if not found."""
    ...

# Good — using Optional for clarity
from typing import Optional

def find_by_email(email: str) -> Optional[User]:
    ...
```

- **Use the latest syntax** available in the project's Python version. Python 3.10: `X | None` over `Optional[X]`, `list[X]` over `List[X]`.
- **Annotate all public functions/methods** with complete types (args + return).
- **Internal helpers** should be annotated too — it catches bugs and documents intent.
- **Never use `Any`** unless at a genuine API boundary with external untyped code. Prefer `object` or a `Protocol`.

## Docstrings — Google Style

Every function, class, module, and non-obvious block must have a Google-style docstring.

```python
def transfer_funds(
    from_account: AccountId,
    to_account: AccountId,
    amount: Decimal
) -> TransferResult:
    """Transfer funds between two accounts atomically.

    Both accounts must be active and belong to the same currency.
    The transfer is atomic — either both accounts are updated or
    neither is.

    Args:
        from_account: The account to debit.
        to_account: The account to credit.
        amount: The amount to transfer in the accounts' currency.

    Returns:
        TransferResult with the new balances and transaction ID.

    Raises:
        InsufficientFundsError: If from_account has insufficient balance.
        AccountFrozenError: If either account is frozen.
    """
    ...
```

- **Classes:** Document purpose, attributes, and invariants in the class docstring.
- **Modules:** A brief `"""Provides X, Y, Z."""` at the top.
- **Keep comments current.** Stale comments are worse than no comments — update them when logic changes.
