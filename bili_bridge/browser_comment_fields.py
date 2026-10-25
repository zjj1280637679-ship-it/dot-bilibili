"""Strict, inert public comment projections; no stable identity or reply target."""
import unicodedata
from .browser_contracts import fail, text_value

TEXT_LIMIT = 2000


def validate_field(field, limit):
    if not isinstance(field, dict) or set(field) != {'state', 'value'}:
        fail('field_schema')
    if field['state'] == 'not_visible':
        if field['value'] is not None:
            fail('field_state')
    elif field['state'] == 'visible':
        text_value(field['value'], limit)
        if any(unicodedata.category(c) == 'Cc' for c in field['value']):
            fail('invalid_text')
    else:
        fail('field_state')


def validate_text(field):
    if not isinstance(field, dict) or set(field) != {'state', 'value', 'truncated', 'observed_original_length'}:
        fail('text_schema')
    if type(field['truncated']) is not bool:
        fail('text_truncation')
    if field['state'] == 'not_visible':
        if field['value'] is not None or field['truncated'] or field['observed_original_length'] is not None:
            fail('field_state')
        return
    if field['state'] != 'visible':
        fail('field_state')
    value, length = field['value'], field['observed_original_length']
    if not isinstance(value, str) or not 1 <= len(value) <= TEXT_LIMIT:
        fail('invalid_text')
    try:
        value.encode('utf-8', 'strict')
    except UnicodeError:
        fail('invalid_unicode')
    if any(unicodedata.category(c) == 'Cc' and c != '\n' for c in value):
        fail('invalid_text')
    if type(length) is not int or length < 1 or length > 2**53-1:
        fail('text_truncation')
    if field['truncated']:
        if len(value) != TEXT_LIMIT or length <= TEXT_LIMIT:
            fail('text_truncation')
    elif length != len(value):
        fail('text_truncation')


def validate_threads(threads, limit):
    if not isinstance(threads, list) or len(threads) > limit:
        fail('receipt_threads')
    for position, thread in enumerate(threads, 1):
        if not isinstance(thread, dict) or set(thread) != {'snapshot_position', 'visibility', 'author', 'text', 'timestamp_display', 'like_count_display'}:
            fail('thread_schema')
        if type(thread['snapshot_position']) is not int or thread['snapshot_position'] != position:
            fail('snapshot_position')
        if thread['visibility'] not in ('full', 'partial'):
            fail('thread_visibility')
        for key, bound in [('author', 200), ('timestamp_display', 100), ('like_count_display', 100)]:
            validate_field(thread[key], bound)
        validate_text(thread['text'])
