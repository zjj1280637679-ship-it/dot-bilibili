"""Explicit public resource graph, separate from operation/state transitions."""
from pathlib import Path, PurePosixPath
import re
import hashlib
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_FILES = (
    'README.md', 'SECURITY.md', 'CONTRIBUTING.md',
    'docs/ai-tool-facade.md', 'docs/ai-tool-usage.md',
    'docs/browser-comments.md', 'docs/browser-host-contract.md',
    'docs/browser-public-search.md', 'docs/browser-usage.md', 'docs/browser-video-open.md',
    'docs/delivery-boundaries.md', 'docs/host-capture-recipes-v2.md',
    'docs/host-capture-recipes.md', 'docs/installable-integration.md',
    'docs/installable-integration-v032.md', 'docs/milestone-five-acceptance.md',
    'docs/product-directions.md', 'docs/prerequisites.md', 'docs/progress.json', 'docs/read-workflow.md',
    'docs/verification-budget.md', 'docs/verification.md',
    'docs/video-reference-relationship.md', 'docs/video-reference-v1.md',
)
# These semantic references are code/runbook relations, not discoverable solely
# from Markdown links. The original protocol files are deliberately unchanged.
PROTOCOL_EDGES = {
    'docs/read-workflow.md': (
        'docs/browser-public-search.md', 'docs/browser-usage.md',
        'docs/browser-video-open.md', 'docs/browser-host-contract.md', 'docs/browser-comments.md'),
    'docs/host-capture-recipes-v2.md': ('docs/host-capture-recipes.md', 'docs/browser-host-contract.md'),
    'docs/video-reference-v1.md': ('docs/host-capture-recipes-v2.md', 'docs/video-reference-relationship.md'),
}


def resource_root():
    bundled = Path(__file__).resolve().parent / 'resources'
    return bundled if bundled.is_dir() else ROOT


def resource_path(relative):
    if relative not in RESOURCE_FILES:
        raise ValueError('resource_not_allowlisted')
    path = resource_root() / relative
    if not path.is_file() or path.is_symlink():
        raise ValueError('resource_missing')
    return path


def relative_links(text):
    """Local inline/reference Markdown links in reviewed public documentation.

    No browser/network access; external URLs and same-file anchors are excluded.
    Anchor labels are not validated: this checks file/resource closure only.
    """
    targets = re.findall(r'!?\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)', text)
    targets += re.findall(r'^\s*\[[^\]]+\]:\s*(\S+)', text, flags=re.MULTILINE)
    for target in targets:
        parts = urlsplit(target.strip('<>'))
        if parts.scheme or parts.netloc or not parts.path:
            continue
        yield unquote(parts.path)


def normalize_link(source, target):
    path = PurePosixPath(target)
    if path.is_absolute() or '\\' in target:
        raise ValueError('nonlocal_resource_reference')
    pieces = list(PurePosixPath(source).parent.parts)
    for piece in path.parts:
        if piece == '..':
            if not pieces:
                raise ValueError('resource_reference_escapes_root')
            pieces.pop()
        elif piece != '.':
            pieces.append(piece)
    return '/'.join(pieces)


def check_closure(root=None):
    """Finite allowlist + every local Markdown edge; fail closed on new dependency."""
    root = Path(root) if root is not None else resource_root()
    allowed = set(RESOURCE_FILES)
    edges = []
    for source in RESOURCE_FILES:
        path = root / source
        if path.is_symlink() or not path.is_file():
            raise ValueError('resource_missing:' + source)
        targets = set(PROTOCOL_EDGES.get(source, ()))
        if path.suffix == '.md':
            targets.update(normalize_link(source, target) for target in relative_links(path.read_text()))
        for target in sorted(targets):
            if target not in allowed or not (root / target).is_file() or (root / target).is_symlink():
                raise ValueError('resource_closure_missing:' + source + '->' + target)
            edges.append({'source': source, 'target': target})
    return {'ok': True, 'resource_count': len(allowed), 'edges': edges,
            'scope': 'allowlisted files and relative Markdown/protocol edges; not anchor or implementation proof'}


LEGACY_RECIPE_SHA256 = {
    'scripts/host_capture_recipes.js': '1cdaa1666863524647f1fd8dcc5a3e88010429820067752c6bac331a8b14b64a',
    'scripts/host_projection_recipe.js': 'b5af06c4954bafdfaf54b4f334ee3618a4bf0136ab10d71cd7a1ae2841b01b07',
}


def legacy_recipe_path(relative):
    """The default workflow always uses pinned v1, never page-based route selection."""
    if relative not in LEGACY_RECIPE_SHA256:
        raise ValueError('legacy_recipe_not_allowlisted')
    path = ROOT / relative
    if path.is_symlink() or not path.is_file():
        raise ValueError('legacy_recipe_missing')
    if hashlib.sha256(path.read_bytes()).hexdigest() != LEGACY_RECIPE_SHA256[relative]:
        raise ValueError('legacy_recipe_digest_mismatch')
    return path
