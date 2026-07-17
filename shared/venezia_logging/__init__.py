import logging
import logging.handlers
import os
import sys
from pathlib import Path

import structlog


def setup_logging(*, json_output: bool = False, log_dir: str | None = None) -> None:
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    console_renderer = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                console_renderer,
            ],
            foreign_pre_chain=shared_processors,
        )
    )
    root.addHandler(ch)

    # File handler — activated by LOG_DIR env var or explicit argument
    resolved_dir = log_dir or os.getenv("LOG_DIR")
    if resolved_dir:
        log_path = Path(resolved_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_path / "app.log",
            maxBytes=10 * 1024 * 1024,  # 10 MB per file
            backupCount=5,
            encoding="utf-8",
        )
        fh.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.processors.JSONRenderer(),
                ],
                foreign_pre_chain=shared_processors,
            )
        )
        root.addHandler(fh)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
