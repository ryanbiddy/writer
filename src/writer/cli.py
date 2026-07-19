"""Writer command-line entry point."""

from __future__ import annotations

import argparse
import os
import sys

from writer import __version__
from writer.auth import ensure_token
from writer.http_api import DEFAULT_HOST, DEFAULT_PORT, create_server
from writer.uoink_client import UOINK_TOKEN_ENV, UoinkClient


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--version"]:
        print(__version__)
        return 0
    if not args or args == ["--help"]:
        print(
            "usage: writer [--version] <command>\n\n"
            "commands:\n"
            "  writer serve [--port 5181]   local editor and HTTP API\n"
            "  writer serve-mcp             direct MCP stdio server\n"
            "  writer doctor                local readiness check\n"
        )
        return 0
    if args[0] == "serve-mcp":
        from writer import mcp_server
        return mcp_server.run(args[1:])
    if args[0] == "doctor":
        from writer import doctor
        return doctor.run(args[1:])
    if args[0] == "serve":
        parser = argparse.ArgumentParser(prog="writer serve")
        parser.add_argument("--host", default=DEFAULT_HOST)
        parser.add_argument("--port", type=int, default=DEFAULT_PORT)
        parser.add_argument("--database", default=None)
        parsed = parser.parse_args(args[1:])
        token = ensure_token()
        uoink = None
        if str(os.environ.get(UOINK_TOKEN_ENV) or "").strip():
            uoink = UoinkClient.from_env()
        server = create_server(
            host=parsed.host,
            port=parsed.port,
            token=token,
            database=parsed.database,
            uoink=uoink,
        )
        actual_port = int(server.server_address[1])
        print(
            f"Writer is ready at "
            f"http://127.0.0.1:{actual_port}/#token={token}")
        print("Press Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0
    print(f"unknown command: {args[0]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
