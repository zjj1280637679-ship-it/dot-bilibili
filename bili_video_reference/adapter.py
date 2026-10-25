"""Additive reference entry reusing the existing workflow and its only ledger."""
from facade import search_read
from facade.contracts import envelope
from .contracts import validate


def read_video(args, *, profile, invocation_id):
    """Normalize once and delegate once; host supplies durable invocation identity.

    Equivalent BVID/canonical-URL input denotes the same intent. The underlying
    facade owns budgets, persistence, cached retries, and conflict detection.
    No navigation, browser service, retry loop, or additional ledger lives here.
    """
    try:
        normalized = validate(args)
    except ValueError as exc:
        return envelope(None, code=str(exc), action='correct_arguments')
    return search_read(normalized, profile=profile, invocation_id=invocation_id)
