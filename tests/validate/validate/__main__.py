"""Entrypoint — `uv run python -m validate`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
