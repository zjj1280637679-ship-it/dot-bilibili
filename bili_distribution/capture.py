"""Current release's fixed capture mapping, shared by both read routes."""
import hashlib
from scripts.compose_host_capture_v3 import PINNED_SHA256, compose
from .resources_v033 import ROOT, resource_path, check_closure, legacy_recipe_path

VERSION = '0.3.3'
RECIPE_VERSION = 'host-capture-v3'
ROUTE_RECIPES = {'bili_search_read': RECIPE_VERSION, 'bili_read_video': RECIPE_VERSION}


def instructions():
    function = compose()
    return dict(version=VERSION, recipe_version=RECIPE_VERSION,
        route_recipes=dict(ROUTE_RECIPES), runtime_root=str(ROOT),
        native_tool_registration=False,
        resources={
            'capture_recipe': str(ROOT/'scripts/host_capture_recipes_v3.js'),
            'capture_composer': str(ROOT/'scripts/compose_host_capture_v3.py'),
            'projection_recipe': str(legacy_recipe_path('scripts/host_projection_recipe.js')),
            **{key:str(resource_path(path)) for key,path in {
                'capture_protocol':'docs/host-capture-recipes-v033.md',
                'workflow_protocol':'docs/read-workflow.md',
                'host_contract':'docs/browser-host-contract.md',
                'integration_guide':'docs/installable-integration-v033.md',
                'video_reference_guide':'docs/installable-integration-v033.md',
                'acceptance_scope':'docs/release-v033-acceptance-scope.md',
            }.items()}},
        components=[dict(path=str(ROOT/'scripts'/name),sha256=digest)
                    for name,digest in PINNED_SHA256.items()],
        capture_recipe_sha256=PINNED_SHA256['host_capture_recipes_v3.js'],
        composed_function_sha256=hashlib.sha256(function.encode()).hexdigest(),
        composition='Run the returned fixed composer locally, verify compose() UTF-8 hash (without CLI newline), evaluate one function with kind/limit only; never install page globals.',
        limits={'search_inspected_visible_cards':10,'search_max_video_items':10,
                'comments_max_threads':3,'limit_parameter':'comments only; validated 1..3 for all kinds'},
        resource_closure=check_closure(),
        commands={'search_status':'bili-tools','video_reference':'bili-video-reference'},
        obligations=['Preserve canonical runtime root, existing ledger and spool continuity.',
                     'Fresh source/tab preflight and unchanged exact BV, budget and receipt validation.',
                     'Keep recipe pins and diagnostics outside closed receipts.',
                     'Unknown is not cancellation or permission to replay.'])
