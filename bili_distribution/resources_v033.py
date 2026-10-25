"""Current resource extension; old 0.3.2 resource graph stays byte-identical."""
from . import resources as legacy

ROOT = legacy.ROOT
EXTRA_RESOURCE_FILES = (
    'docs/README-v033.md', 'docs/prerequisites-v033.md',
    'docs/video-reference-v033.md', 'docs/host-capture-recipes-v033.md',
    'docs/installable-integration-v033.md', 'docs/release-v033-acceptance-scope.md',
)
RESOURCE_FILES = legacy.RESOURCE_FILES + EXTRA_RESOURCE_FILES
PROTOCOL_EDGES = {
    'docs/installable-integration-v033.md': ('docs/host-capture-recipes-v033.md',
        'docs/read-workflow.md', 'docs/browser-host-contract.md', 'docs/prerequisites-v033.md'),
    'docs/host-capture-recipes-v033.md': ('docs/host-capture-recipes.md', 'docs/browser-host-contract.md'),
}
legacy_recipe_path = legacy.legacy_recipe_path


def resource_path(relative):
    if relative not in RESOURCE_FILES:
        raise ValueError('resource_not_allowlisted')
    path = legacy.resource_root() / relative
    if not path.is_file() or path.is_symlink():
        raise ValueError('resource_missing')
    return path


def check_closure(root=None):
    # Validate the unchanged graph using its existing implementation first.
    root = legacy.Path(root) if root is not None else legacy.resource_root()
    old = legacy.check_closure(root)
    edges = list(old['edges'])
    for source in EXTRA_RESOURCE_FILES:
        path = root / source
        if path.is_symlink() or not path.is_file():
            raise ValueError('resource_missing:' + source)
        targets = set(PROTOCOL_EDGES.get(source, ()))
        targets.update(legacy.normalize_link(source, target)
                       for target in legacy.relative_links(path.read_text()))
        for target in sorted(targets):
            dest = root / target
            if target not in RESOURCE_FILES or not dest.is_file() or dest.is_symlink():
                raise ValueError('resource_closure_missing:' + source + '->' + target)
            edges.append({'source':source, 'target':target})
    return dict(ok=True, resource_count=len(RESOURCE_FILES), edges=edges,
                scope=old['scope'], historical_resource_count=old['resource_count'])
