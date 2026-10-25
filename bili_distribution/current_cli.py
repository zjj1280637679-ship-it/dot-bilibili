"""Current-release resource selection; original business transport unchanged."""
import argparse
import json
import sys
from bili_integration.cli import diagnostics
from .capture import instructions, VERSION
from .resources_v033 import check_closure


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['instructions','diagnose'])
    args = parser.parse_args(argv)
    result = instructions() if args.action == 'instructions' else dict(
        **diagnostics(), resource_closure=check_closure(), distribution_version=VERSION)
    print(json.dumps(result, ensure_ascii=True))
    return 0


def tool_main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ('instructions','diagnose'):
        return main(args)
    from bili_integration.cli import main as business_main
    return business_main(args)


if __name__ == '__main__':
    raise SystemExit(tool_main())
