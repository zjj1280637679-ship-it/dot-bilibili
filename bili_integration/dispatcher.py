"""One dispatch decision; host context is never accepted as a business argument."""
from facade import search_read, status
from facade.contracts import envelope


def dispatch(request, *, profile, invocation_id=None):
    """Dispatch the README tool envelope. invocation_id is trusted host metadata.

    The host must durably save the complete intent and reuse the ID on retries.
    This function does not synthesize an ID or start a browser dispatcher.
    """
    if (not isinstance(request, dict) or set(request) != {'tool', 'arguments'}
            or not isinstance(request['arguments'], dict)):
        return envelope(None, code='invalid_arguments', action='correct_arguments')
    if request['tool'] == 'bili_status':
        return status(request['arguments'], profile=profile)
    if request['tool'] == 'bili_search_read':
        if (not isinstance(invocation_id, str) or not invocation_id
                or len(invocation_id) > 1000):
            return envelope(None, code='host_invocation_required', action='contact_host')
        try:
            invocation_id.encode('utf-8', 'strict')
        except UnicodeError:
            return envelope(None, code='host_invocation_required', action='contact_host')
        return search_read(request['arguments'], profile=profile, invocation_id=invocation_id)
    return envelope(None, code='unknown_tool', action='correct_arguments')
