"""Video route shares current capture mapping, delegates business unchanged."""
import sys
from .current_cli import main as resource_main


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ('instructions','diagnose'):
        return resource_main(args)
    from bili_video_reference.cli import main as business_main
    return business_main(args)


if __name__ == '__main__':
    raise SystemExit(main())
