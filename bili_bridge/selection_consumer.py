"""Narrow first-party receipt-consumption port; not a Python security sandbox.

The composition root supplies only the atomic consumption callback. The adapter
owns no journal, transaction or policy; the kernel remains their sole authority.
"""
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Protocol

from .contracts import Request


class SelectionConsumer(Protocol):
    def consume_browser_selection(self, request: Request) -> Mapping[str, str | float]:
        """Consume exact scoped journal evidence once, or propagate failure."""
        ...


class JournalSelectionConsumer:
    """Expose one method and a detached immutable view of the kernel result.

    The private bound callback still references its provider. Introspection is
    not prevented; this reduces accidental authority in trusted business code.
    """
    __slots__ = ('_consume',)

    def __init__(self, consume: Callable[[Request], dict]):
        self._consume = consume

    def consume_browser_selection(self, request: Request) -> Mapping[str, str | float]:
        # Current kernel selection fields are scalar strings/timestamps. Copy
        # detaches the view; do not expose a mutable journal-owned dictionary.
        return MappingProxyType(dict(self._consume(request)))
