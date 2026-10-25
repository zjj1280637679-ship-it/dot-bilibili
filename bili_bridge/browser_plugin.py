"""One read-only host-browser primitive integrated with existing relay scope."""
from .contracts import Result
from .relays import RelayEnvelope, RelayStation, current_envelope
from .browser_host import BINDING, OPERATION, HostError

class BrowserReadPlugin:
    name = 'host-browser-read'
    capabilities = frozenset({OPERATION})
    mutating = frozenset()

    def __init__(self, host):
        self.host = host

    def execute(self, request):
        data = {'source': 'browser_dom', 'query': request.target, 'items': [], 'coverage': 'visible_subset', 'complete': False}
        if request.capability != OPERATION or request.account != BINDING or not isinstance(request.payload, dict) or set(request.payload) != {'expected_url','expected_tab_id'}:
            return Result('rejected', data, 'browser_request_scope')
        try:
            envelope = current_envelope() or RelayEnvelope.from_request(request)
            predecessor = 'kernel.execute' if envelope.path else None
            envelope = RelayStation('browser.host.read', predecessor, frozenset({'read'})).forward(envelope, request)
            receipt = self.host.read(request.operation_id, envelope.correlation_id, request.target,
                                     request.payload['expected_url'], request.payload['expected_tab_id'])
            data.update(receipt, relay_trace=list(envelope.path))
            return Result('applied' if receipt['status'] == 'observed' else 'blocked', data, receipt['error'])
        except HostError as exc:
            return Result('unknown' if str(exc) == 'host_outcome_unknown' else 'blocked', data, str(exc))
        except (ValueError, OSError):
            return Result('blocked', data, 'host_exchange_failed')
