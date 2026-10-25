"""Plugin-local module relay for the fetch / parse / normalize primitives.

These are trusted-code composition guards, not a Python sandbox. Data crosses
module boundaries as immutable strings; provider JSON never grants authority.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json

from .contracts import Request, Result
from .fixtures import decode_video_html, normalize_video_state, outcome
from .relays import RelayEnvelope, RelayStation, current_envelope


@dataclass(frozen=True)
class FetchedDocument:
    envelope: RelayEnvelope
    html: str


@dataclass(frozen=True)
class ParsedDocument:
    envelope: RelayEnvelope
    state_json: str


@dataclass(frozen=True)
class NormalizedMetadata:
    envelope: RelayEnvelope
    result_json: str


class MetadataPipeline:
    """The only production metadata plugin path, with no direct module bypass."""
    def __init__(self, fetcher, *, source):
        if source not in ("public_html", "offline_fixture"):
            raise ValueError("invalid metadata source")
        self.fetcher = fetcher
        self.source = source

    def fetch(self, envelope, request):
        predecessor = "kernel.execute" if envelope.path else None
        advanced = RelayStation("metadata.fetch", predecessor=predecessor, effects=frozenset({"read"})).forward(envelope, request)
        html = self.fetcher(request.target)
        if isinstance(html, Result):
            return html
        if type(html) is not str:
            return outcome("blocked", request.target, self.source, "invalid_transport_document")
        return FetchedDocument(advanced, html)

    def parse(self, packet, request, fetched_at):
        if type(packet) is not FetchedDocument:
            raise ValueError("invalid_parse_envelope")
        advanced = RelayStation("metadata.parse", predecessor="metadata.fetch", effects=frozenset({"read"})).forward(packet.envelope, request)
        state = decode_video_html(packet.html, request.target, source=self.source, part=request.payload.get("part", 1), fetched_at=fetched_at)
        if isinstance(state, Result):
            return state
        return ParsedDocument(advanced, json.dumps(state, ensure_ascii=False, allow_nan=False))

    def normalize(self, packet, request, fetched_at):
        if type(packet) is not ParsedDocument:
            raise ValueError("invalid_normalize_envelope")
        advanced = RelayStation("metadata.normalize", predecessor="metadata.parse", effects=frozenset({"read"})).forward(packet.envelope, request)
        result = normalize_video_state(json.loads(packet.state_json), request.target, source=self.source, part=request.payload.get("part", 1), fetched_at=fetched_at)
        result.data["evidence"]["relay"] = {"schema_version": advanced.schema_version, "correlation_id": advanced.correlation_id, "path": list(advanced.path)}
        return NormalizedMetadata(advanced, json.dumps(asdict(result), ensure_ascii=False, allow_nan=False))

    def execute(self, request):
        envelope = current_envelope() or RelayEnvelope.from_request(request, mutating=False)
        fetched = self.fetch(envelope, request)
        if isinstance(fetched, Result):
            return fetched
        fetched_at = datetime.now(timezone.utc).isoformat() if self.source == "public_html" else None
        parsed = self.parse(fetched, request, fetched_at)
        if isinstance(parsed, Result):
            return parsed
        normalized = self.normalize(parsed, request, fetched_at)
        return Result(**json.loads(normalized.result_json))
