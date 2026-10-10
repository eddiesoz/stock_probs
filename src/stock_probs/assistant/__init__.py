"""Owner-scoped AI assistant application boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stock_probs.assistant.storage import AssistantStorage

__all__ = ["AssistantStorage"]


def __getattr__(name: str) -> object:
    """Load the public storage class only when a caller requests it."""

    if name != "AssistantStorage":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from stock_probs.assistant.storage import AssistantStorage

    globals()[name] = AssistantStorage
    return AssistantStorage
