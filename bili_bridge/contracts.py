"""Frozen v0.1 adapter contracts. Adapters are trusted, not sandboxed."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Request:
    operation_id: str
    account: str
    capability: str
    target: str
    payload: dict


@dataclass(frozen=True)
class Result:
    status: str
    data: dict
    error: str | None = None


class Plugin(Protocol):
    name: str
    capabilities: frozenset[str]
    mutating: frozenset[str]

    def execute(self, request: Request) -> Result: ...
