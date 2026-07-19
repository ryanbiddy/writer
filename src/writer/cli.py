"""Writer command-line entry point."""

from __future__ import annotations

import sys

from writer import __version__


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--version"]:
        print(__version__)
        return 0
    if not args or args == ["--help"]:
        print(
            "usage: writer [--version]\n\n"
            "Private migration scaffold. Product commands arrive in "
            "later rollback stages."
        )
        return 0
    print(f"unknown command: {args[0]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
