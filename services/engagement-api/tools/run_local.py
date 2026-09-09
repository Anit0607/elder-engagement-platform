from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from app.config import load_settings_file
from app.main import create_app

SERVICE_ROOT = Path(__file__).parents[1]
DEFAULT_CONFIG = SERVICE_ROOT.parents[1] / "config" / "engagement" / ".env.example"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the engagement API with an explicit config file.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    settings = load_settings_file(args.config.resolve(strict=True))
    uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
