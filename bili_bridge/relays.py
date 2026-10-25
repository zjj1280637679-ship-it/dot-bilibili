"""Functional-primitive relay contracts, not a hostile-code sandbox.

Every hop checks immutable scope and ordered predecessor. Local guards compose
with the shared transaction, not with independent per-station budgets.
"""
from contextvars import ContextVar
from dataclasses import dataclass, replace, field
import hashlib
import json

from .contracts import Request

_KERNEL_ROUTE = ('kernel.schema', 'kernel.grant', 'kernel.budget', 'kernel.journal', 'kernel.execute')
_MODULE_ROUTE = ('metadata.fetch', 'metadata.parse', 'metadata.normalize')

_ACTIVE_ENVELOPE = ContextVar('bili_bridge_relay_envelope', default=None)


def current_envelope():
    return _ACTIVE_ENVELOPE.get()


def request_digest(request):
    value = [request.account, request.capability, request.target, request.payload]
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class RelayEnvelope:
    schema_version: int
    correlation_id: str
    account: str
    capability: str
    target: str
    payload_digest: str
    effect: str
    path: tuple[str, ...] = ()
    _scope_seal: str = field(default='', repr=False)

    @classmethod
    def from_request(cls, request: Request, mutating=False):
        effect = 'write' if mutating else 'read'
        digest = request_digest(request)
        # Integrity checksum detects accidental scope/effect replacement. This
        # is not authentication against malicious in-process Python code.
        seal = hashlib.sha256(json.dumps([1, request.operation_id, request.account,
            request.capability, request.target, digest, effect], ensure_ascii=True).encode()).hexdigest()
        return cls(1, request.operation_id, request.account, request.capability,
                   request.target, digest, effect, (), seal)


@dataclass(frozen=True)
class RelayStation:
    name: str
    predecessor: str | None
    effects: frozenset[str] = frozenset({'read', 'write'})

    def forward(self, envelope: RelayEnvelope, request: Request):
        if not isinstance(envelope, RelayEnvelope):
            raise ValueError('relay_contract_violation')
        expected = RelayEnvelope.from_request(request, envelope.effect == 'write')
        if self.name in _KERNEL_ROUTE:
            route = _KERNEL_ROUTE[:_KERNEL_ROUTE.index(self.name)]
            if envelope.path != route:
                raise ValueError('relay_route_violation')
        elif self.name in _MODULE_ROUTE:
            route = _MODULE_ROUTE[:_MODULE_ROUTE.index(self.name)]
            if envelope.path not in (route, _KERNEL_ROUTE + route):
                raise ValueError('relay_route_violation')
        if (envelope.schema_version != 1 or type(envelope.schema_version) is not int
                or envelope.effect not in self.effects or type(envelope.path) is not tuple
                or replace(envelope, path=()) != expected
                or (envelope.path[-1] if envelope.path else None) != self.predecessor
                or self.name in envelope.path):
            raise ValueError('relay_contract_violation')
        return replace(envelope, path=envelope.path + (self.name,))


class GrantRelay:
    """Exact-scope authorization primitive. Token lookup is broker-owned."""
    @staticmethod
    def rejection(grant, envelope, now):
        if (grant is None or grant['used'] or grant['operation_id'] != envelope.correlation_id
                or grant['digest'] != envelope.payload_digest or grant['expires'] <= now):
            return 'grant_invalid'
        return None


class BudgetRelay:
    """Pure shared-scheduler guard; caller atomically reserves after acceptance."""
    @staticmethod
    def rejection(*, now, high_water, count, last_start, budget, interval):
        if now < high_water:
            return 'clock_rollback'
        if count >= budget:
            return 'hourly_budget'
        if last_start is not None and now - last_start < interval:
            return 'cooldown'
        return None
