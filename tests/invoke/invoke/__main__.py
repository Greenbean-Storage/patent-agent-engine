"""Entrypoint — `uv run python -m invoke`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
