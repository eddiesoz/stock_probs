---
title: "Testing and Tools — pytest, ruff, mypy Conventions"
impact: MEDIUM
impactDescription: "Ensures consistent test quality, linting, and type checking across the project"
tags: [python, pytest, ruff, mypy, testing, linting, type-checking]
---

## Testing — pytest

```python
# tests/test_user_service.py
import pytest
from user_service import UserService, UserNotFoundError

@pytest.fixture
def service():
    """Fixture providing a UserService with a test database."""
    svc = UserService(database_url="sqlite:///:memory:")
    svc.migrate()
    return svc

def test_get_user_returns_user(service):
    """get_user returns the user when it exists."""
    user = service.get_user(1)
    assert user.name == "Test User"

def test_get_user_raises_when_not_found(service):
    """get_user raises UserNotFoundError for nonexistent IDs."""
    with pytest.raises(UserNotFoundError):
        service.get_user(99999)
```

- **Use `pytest`** unless the project uses `unittest`. Fixtures, parametrization, markers.
- **One test file per source file** (or one test file per module).
- **Test filename:** `test_*.py` in `tests/` directory. Pytest discovers these.
- **Test function names must describe what they test.** `test_get_user_raises_when_not_found` not `test_error`.
- **Arrange-Act-Assert pattern** and meaningful error messages.

## Linting & Formatting — ruff

`ruff` is the single tool for both linting and formatting. No flake8, isort, or black needed.

- Run `ruff check .` before committing. Fix every issue.
- Run `ruff format .` to auto-format.
- Check `pyproject.toml` for project-specific ruff configuration.
- CI runs `ruff check . && ruff format --check .`. A failure here blocks merge.

## Type Checking — mypy

- Run `mypy src/` after ruff passes. Type errors block merge.
- `mypy` config lives in `pyproject.toml` under `[tool.mypy]`.
- Use `--strict` for new projects. For existing projects, match the project's level of strictness.
