"""Luna RPG v6 - Entry point.

Usage:
    python -m luna
    python -m luna --no-media
    python -m luna --world prehistoric_tribe --companion Kira
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Fix Windows console encoding (cp1252 → utf-8) to prevent OSError on Unicode print()
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class _Tee:
    """Writes to both a stream and a file simultaneously."""
    def __init__(self, stream, file_path: Path) -> None:
        self._stream = stream
        self._file = open(file_path, "w", encoding="utf-8", errors="replace")

    def write(self, data: str) -> int:
        self._stream.write(data)
        self._file.write(data)
        self._file.flush()
        return len(data)

    def flush(self) -> None:
        self._stream.flush()
        self._file.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _setup_logging(level: str) -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    log_path = Path(__file__).resolve().parent.parent.parent / "game_debug.log"

    # Tee stdout/stderr → terminal + file (captures all print() calls too)
    tee = _Tee(sys.stdout, log_path)
    sys.stdout = tee
    sys.stderr = tee

    # logging → same file handler
    file_handler = logging.FileHandler(log_path, encoding="utf-8", mode="a")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))

    console_handler = logging.StreamHandler(tee)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(console_handler)
    root.addHandler(file_handler)

    # Quiet noisy third-party libraries
    for lib in ("httpx", "httpcore", "chromadb", "sqlalchemy"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    # Luna namespace log levels
    # Media pipeline: solo warning in produzione (molto verboso)
    logging.getLogger("luna.media").setLevel(logging.WARNING)
    # Agents: INFO per seguire il flusso dei turn
    logging.getLogger("luna.agents").setLevel(logging.INFO)
    # Core systems: WARNING (silenzioso in produzione)
    logging.getLogger("luna.systems").setLevel(logging.WARNING)
    logging.getLogger("luna.core").setLevel(logging.WARNING)
    # Override per debug: usa --log-level DEBUG per tutti


def main() -> None:
    parser = argparse.ArgumentParser(description="Luna RPG v6")
    parser.add_argument("--world",      default="school_life_complete")
    parser.add_argument("--companion",  default="Luna")
    parser.add_argument("--no-media",   action="store_true")
    parser.add_argument("--log-level",  default="INFO")
    parser.add_argument("--session",    type=int, default=None,
                        help="Load existing session ID")
    args = parser.parse_args()

    _setup_logging(args.log_level)

    # Import here to avoid circular imports at module level
    from luna.ui.app import main as app_main
    import inspect
    sig = inspect.signature(app_main)
    if "world_id" in sig.parameters:
        app_main(
            world_id=args.world,
            companion=args.companion,
            no_media=args.no_media,
            session_id=args.session,
        )
    else:
        app_main(no_media=args.no_media)


if __name__ == "__main__":
    main()
