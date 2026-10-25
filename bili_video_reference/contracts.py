"""Pure, literal video-reference grammar; never resolves URLs or redirects."""
import re

BVID_PATTERN = r'BV[0-9A-Za-z]{10}'
URL_PREFIX = 'https://www.bilibili.com/video/'
VIDEO_PATTERN = r'(?:BV[0-9A-Za-z]{10}|https://www[.]bilibili[.]com/video/BV[0-9A-Za-z]{10}/?)'
READ_VIDEO_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['video'],
    'properties': {
        'video': {'type': 'string', 'minLength': 12,
                  'maxLength': len(URL_PREFIX) + 13,
                  'pattern': '^' + VIDEO_PATTERN + r'(?![\s\S])'},
        'comments': {'type': 'boolean', 'default': False}}}


def resolve(video):
    """Return a syntactically valid BVID, not a claim that the video exists.

    No trimming, percent decoding, URL parser normalization, or network I/O.
    Canonical URLs accept an optional trailing slash; other URL forms fail.
    """
    if (not isinstance(video, str) or len(video) > len(URL_PREFIX) + 13
            or re.fullmatch(VIDEO_PATTERN, video) is None):
        raise ValueError('unsupported_video_reference')
    return video[len(URL_PREFIX):].removesuffix('/') if video.startswith(URL_PREFIX) else video


def validate(args):
    if (not isinstance(args, dict) or 'video' not in args
            or set(args) - {'video', 'comments'}
            or type(args.get('comments', False)) is not bool):
        raise ValueError('invalid_arguments')
    bvid = resolve(args['video'])
    return dict(query=bvid, select=bvid, comments=args.get('comments', False))


TOOL_DEFINITION = {
    'name': 'bili_read_video',
    'description':
        'Read visible metadata for a BVID or exact canonical HTTPS Bilibili video '
        'URL, via public search followed by exact BVID selection from fresh '
        'results. Not direct-link navigation: fails if absent from those results. '
        'Uses 4 operations, or 5 with comments=true (at most 3 current-viewport '
        'threads). Navigates the host-authorized tab and may affect history/autoplay. '
        'No scrolling, replies, pagination, media comprehension, account writes, '
        'short links, redirects, or arbitrary URLs. Cached retries are not fresh reads.',
    'parameters': READ_VIDEO_SCHEMA}
