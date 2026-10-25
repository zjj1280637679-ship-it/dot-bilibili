"""Trusted journal-backed exact-result navigation; not a generic browser driver."""
from .contracts import Result
from .selection_consumer import SelectionConsumer
from .relays import RelayEnvelope, RelayStation, current_envelope
from .browser_host import BINDING, HostError
from .browser_video_open_contracts import OPERATION

class BrowserVideoOpenPlugin:
    name = 'host-browser-video-open'
    capabilities = frozenset({OPERATION})
    mutating = frozenset()

    def __init__(self, host, selection_consumer: SelectionConsumer):
        self.host, self.selection_consumer = host, selection_consumer

    def execute(self, request):
        data = dict(source='browser_dom',bvid=request.target,coverage='destination_only',complete=False)
        if request.capability != OPERATION or request.account != BINDING or not isinstance(request.payload,dict) or set(request.payload) != {'source_operation_id'}:
            return Result('rejected',data,'browser_request_scope')
        try:
            envelope = current_envelope() or RelayEnvelope.from_request(request)
            predecessor = 'kernel.execute' if envelope.path else None
            envelope = RelayStation('browser.host.video_open',predecessor,frozenset({'read'})).forward(envelope,request)
            selection = self.selection_consumer.consume_browser_selection(request)
            receipt = self.host.open_video(request.operation_id,envelope.correlation_id,request.target,dict(selection))
            data.update(receipt,source_operation_id=selection['source_operation_id'],relay_trace=list(envelope.path))
            return Result('applied' if receipt['status']=='observed' else 'blocked',data,receipt['error'])
        except HostError as exc:
            return Result('unknown' if str(exc)=='host_outcome_unknown' else 'blocked',data,str(exc))
        except (ValueError,OSError):
            return Result('blocked',data,'host_exchange_failed')
