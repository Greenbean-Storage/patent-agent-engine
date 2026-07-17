"""Entrypoint — `uv run python -m lint`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
