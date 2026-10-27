"""Small raw-response metadata parser and injected one-call transport contract.

No HTTP implementation, authentication, search, redirect, retry or persistence.
Parsing a response is not authentication or real-environment acceptance.
"""
from dataclasses import dataclass, field
from enum import Enum
import json
import math
import re
from typing import Protocol

BVID = re.compile(r"BV[0-9A-Za-z]{10}\Z", re.ASCII)
MAX_BODY_BYTES = 512 * 1024
FIELDS = ("title", "aid", "duration", "pubdate")


class Provenance(str, Enum):
    SYNTHETIC = "synthetic"
    SUPPLIED = "supplied_response_unverified"


@dataclass(frozen=True)
class ReadRequest:
    bvid: str
    operation: str = field(default="video.metadata.read", init=False)
    endpoint_key: str = field(default="web_view_v1", init=False)


@dataclass(frozen=True, repr=False)
class TransportReply:
    """Trusted transport's disposition. No headers/cookies/URL are accepted.

    response requires HTTP status + raw UTF-8 JSON bytes. Other dispositions
    mean no parsable response is available; raw body is ignored.
    """
    disposition: str
    http_status: int | None = None
    body: bytes = field(default=b"", repr=False)

    def __repr__(self):
        return "<TransportReply raw body redacted>"


class Transport(Protocol):
    def __call__(self, request: ReadRequest) -> TransportReply: ...


@dataclass(frozen=True, repr=False)
class MetadataResult:
    status: str
    data: dict = field(repr=False)
    field_states: dict
    error: str | None
    provenance: Provenance
    upstream_code: int | None = None
    transport_calls: int = 0

    def __repr__(self):
        return "<MetadataResult status=" + self.status + " metadata redacted>"

    def to_dict(self):
        # A fresh JSON snapshot, not an alias to mutable raw-response data.
        return {"status": self.status, "data": json.loads(json.dumps(self.data)),
                "field_states": dict(self.field_states), "error": self.error,
                "source": self.provenance.value, "upstream_code": self.upstream_code,
                "transport_calls": self.transport_calls,
                "coverage": {"projection_fields": list(FIELDS),
                             "projection_complete": self.status == "parsed",
                             "full_api_response": False},
                "live_verified": False, "auth_assessment": "not_assessed"}


def _result(status, provenance, error=None, *, data=None, states=None, code=None, calls=0):
    return MetadataResult(status, data or {}, states or {}, error, provenance, code, calls)


def valid_bvid(value):
    return type(value) is str and BVID.fullmatch(value) is not None


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("nonfinite_json")


def _finite_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("nonfinite_json")
    return value


def parse_metadata(body, expected_bvid, *, provenance=Provenance.SUPPLIED, transport_calls=0):
    """Parse raw web-view envelope; no coerced types, target fallback or raw errors.

    Only code=integer zero + data object + exact bvid can yield parsed/partial.
    Nonzero codes are preserved numerically without guessing risk/auth/not-found.
    """
    if type(provenance) is not Provenance:
        raise ValueError("explicit_known_provenance_required")
    if type(transport_calls) is not int or transport_calls not in (0, 1):
        raise ValueError("invalid_transport_call_count")
    fail = lambda status, error, code=None: _result(status, provenance, error, code=code, calls=transport_calls)
    if not valid_bvid(expected_bvid):
        return fail("rejected", "invalid_bvid")
    if type(body) is not bytes or len(body) > MAX_BODY_BYTES:
        return fail("unknown", "invalid_or_oversize_body")
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=_unique,
                           parse_constant=_invalid_constant, parse_float=_finite_float)
    except (ValueError, UnicodeError, RecursionError):
        return fail("unknown", "malformed_json")
    if type(value) is not dict or type(value.get("code")) is not int:
        return fail("unknown", "invalid_business_envelope")
    code = value["code"]
    if not -(2**31) <= code < 2**31:
        return fail("unknown", "invalid_business_envelope")
    if code != 0:
        return fail("upstream_error", "upstream_business_error", code)
    data = value.get("data")
    if type(data) is not dict:
        return fail("unknown", "missing_or_invalid_data", code)
    returned_bvid = data.get("bvid")
    if not valid_bvid(returned_bvid):
        return fail("unknown", "missing_or_invalid_identity", code)
    if returned_bvid != expected_bvid:
        return fail("wrong_target", "response_identity_mismatch", code)
    projected = {"bvid": expected_bvid}
    states = {}
    for name in FIELDS:
        if name not in data:
            states[name] = "missing"
            continue
        item = data[name]
        if name == "title":
            valid = (type(item) is str and bool(item.strip()) and len(item) <= 500
                     and not any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in item))
        else:
            valid = type(item) is int and (1 if name == "aid" else 0) <= item <= 2**63 - 1
        states[name] = "present" if valid else "invalid"
        if valid:
            projected[name] = item
    complete = all(state == "present" for state in states.values())
    return _result("parsed" if complete else "partial", provenance,
                   None if complete else "metadata_projection_incomplete",
                   data=projected, states=states, code=code, calls=transport_calls)


class MetadataAdapter:
    """One injected call per explicit read. Outer dispatcher owns pause/grants/ledger.

    A trusted future transport owns network permission, account context, response
    size while streaming, timeouts and no-redirect behavior. None is implemented.
    """
    def __init__(self, transport: Transport, *, provenance: Provenance):
        if not callable(transport) or type(provenance) is not Provenance:
            raise ValueError("trusted_transport_and_provenance_required")
        self._transport, self._provenance = transport, provenance

    def read(self, bvid):
        if not valid_bvid(bvid):
            return _result("rejected", self._provenance, "invalid_bvid")
        try:
            response = self._transport(ReadRequest(bvid))
        except (TimeoutError, ConnectionError, OSError):
            return _result("unknown", self._provenance, "transport_outcome_unknown", calls=1)
        except Exception:
            return _result("unknown", self._provenance, "transport_contract_unknown", calls=1)
        if type(response) is not TransportReply or type(response.disposition) is not str:
            return _result("unknown", self._provenance, "invalid_transport_reply", calls=1)
        if response.disposition in ("blocked", "pending", "deferred", "unknown"):
            return _result(response.disposition, self._provenance,
                           "transport_" + response.disposition, calls=1)
        if response.disposition != "response" or type(response.http_status) is not int:
            return _result("unknown", self._provenance, "invalid_transport_reply", calls=1)
        if response.http_status != 200:
            return _result("unknown", self._provenance, "http_non_success", calls=1)
        return parse_metadata(response.body, bvid, provenance=self._provenance, transport_calls=1)
