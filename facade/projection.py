"""Allowlisted public evidence projection; internal receipts never leave adapter."""
import re

FIELDS = {'title', 'uploader', 'description', 'duration', 'displayed_counts'}
SAFE_ERRORS = frozenset({'target_mismatch','login_required','captcha','browser_unavailable',
    'access_denied','dom_unavailable','context_changed','context_unavailable',
    'host_outcome_unknown','host_exchange_failed','host_setup_failed','budget_exhausted',
    'cooldown','rate_limited'})

def field(value, text=False):
    if not isinstance(value, dict) or value.get('state') not in ('visible', 'not_visible'):
        raise ValueError('invalid_field')
    out = {k:value[k] for k in ('state', 'value')}
    if not (out['value'] is None or isinstance(out['value'], str)
            or isinstance(out['value'], list) and all(isinstance(v,str) for v in out['value'])):
        raise ValueError('invalid_field')
    if text:
        if (type(value.get('truncated')) is not bool or (value.get('observed_original_length') is not None
                and type(value.get('observed_original_length')) is not int)):
            raise ValueError('invalid_text_markers')
        out.update({k:value[k] for k in ('truncated','observed_original_length')})
    return out

def search(items):
    if not isinstance(items, list) or len(items)>10:
        raise ValueError('invalid_items')
    out=[]
    for item in items:
        row={k:item[k] for k in ('title','url','bvid','uploader','duration','displayed_counts')}
        if (not all(isinstance(row[k],str) for k in ('title','url','bvid','uploader','duration'))
                or not isinstance(row['displayed_counts'],list)
                or not all(isinstance(v,str) for v in row['displayed_counts'])):
            raise ValueError('invalid_item')
        out.append(row)
    return out

def video(data):
    if (not isinstance(data.get('bvid'), str) or not re.fullmatch(r'BV[0-9A-Za-z]{10}', data['bvid'])
            or data.get('observed_url') != 'https://www.bilibili.com/video/'+data['bvid']+'/'):
        raise ValueError('invalid_video')
    metadata=data['metadata']
    if not isinstance(metadata, dict):
        raise ValueError('invalid_metadata')
    return {'bvid':data['bvid'], 'url':data['observed_url'],
            'metadata':{k:field(metadata[k]) for k in FIELDS}}

def comments(threads):
    if not isinstance(threads,list) or len(threads)>3:
        raise ValueError('invalid_threads')
    for t in threads:
        if not isinstance(t, dict) or type(t.get('snapshot_position')) is not int or t.get('visibility') not in ('full','partial'):
            raise ValueError('invalid_thread')
    return [dict(snapshot_position=t['snapshot_position'], visibility=t['visibility'],
                 author=field(t['author']), text=field(t['text'], True),
                 timestamp_display=field(t['timestamp_display']),
                 like_count_display=field(t['like_count_display'])) for t in threads]
