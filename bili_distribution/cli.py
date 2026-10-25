"""0.3.2 resource instructions; old frozen transport remains unchanged."""
import argparse
import json
import sys
from bili_integration.cli import diagnostics
from .resources import ROOT, check_closure, resource_path, legacy_recipe_path, LEGACY_RECIPE_SHA256


def instructions():
    closure = check_closure()
    return dict(version='0.3.2', runtime_root=str(ROOT), native_tool_registration=False,
                resources={name: str(resource_path(path)) for name, path in {
                    'workflow_protocol': 'docs/read-workflow.md',
                    'host_contract': 'docs/browser-host-contract.md',
                    'capture_protocol': 'docs/host-capture-recipes.md',
                    'integration_guide': 'docs/installable-integration-v032.md',
                    'video_reference_guide': 'docs/video-reference-v1.md',
                }.items()} | {
                    'capture_recipe': str(legacy_recipe_path('scripts/host_capture_recipes.js')),
                    'projection_recipe': str(legacy_recipe_path('scripts/host_projection_recipe.js')),
                },
                recipe_version='host-capture-v1',
                recipe_sha256=dict(LEGACY_RECIPE_SHA256),
                video_recipe_instructions='python -m bili_video_reference.cli instructions',
                resource_closure=closure,
                commands={'search_status': 'bili-tools', 'video_reference': 'bili-video-reference'},
                obligations=['Keep existing ledger on original absolute runtime_root.',
                             'Use fresh supported-host tab/source observations.',
                             'Persist complete intent and stable invocation ID before calling.',
                             'Service spool concurrently with authorized supported browser tools.',
                             'Unknown is not cancellation or permission to replay.'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['instructions', 'diagnose'])
    args = parser.parse_args(argv)
    result = instructions() if args.action == 'instructions' else dict(
        **diagnostics(), resource_closure=check_closure(), distribution_version='0.3.2')
    print(json.dumps(result, ensure_ascii=True))
    return 0


def tool_main(argv=None):
    """Only installation information is versioned; business dispatch is frozen."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ('instructions', 'diagnose'):
        return main(args)
    from bili_integration.cli import main as frozen_main
    return frozen_main(args)


if __name__ == '__main__':
    raise SystemExit(main())
