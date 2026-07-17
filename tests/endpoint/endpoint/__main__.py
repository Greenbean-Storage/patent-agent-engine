"""Entrypoint — `uv run python -m endpoint`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
