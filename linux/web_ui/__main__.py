from __future__ import annotations

import argparse

import uvicorn

from .server import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Grok Bridge Web UI")
    parser.add_argument("--host", default="0.0.0.0", help="Web UI host")
    parser.add_argument("--port", type=int, default=19999, help="Web UI port")
    parser.add_argument(
        "--bridge-url",
        default="http://localhost:19998",
        help="Grok Bridge API URL",
    )
    args = parser.parse_args()

    app = create_app(bridge_url=args.bridge_url)
    print(f"Grok Web UI: http://{args.host}:{args.port}")
    print(f"Bridge API:  {args.bridge_url}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
