"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import chess

from .config import ConfigError, apply_overrides, load_config
from .logging_setup import setup_logging
from .capture import CaptureError

log = logging.getLogger(__name__)


def _parse_rect(text: str) -> tuple[int, int, int, int]:
    parts = text.replace(" ", "").split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("expected x,y,width,height")
    try:
        values = tuple(int(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("all four values must be integers") from exc
    if values[2] < 100 or values[3] < 100:
        raise argparse.ArgumentTypeError("width and height must be >= 100")
    return values  # type: ignore[return-value]


def build_parser(default_config: str | Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lichess-vision-bot",
        description="Screen-vision Lichess autoplay bot driven by Stockfish.",
    )
    parser.add_argument(
        "--config",
        default=str(default_config),
        help="path to config.json (default: next to run.py)",
    )
    parser.add_argument("--fen", help="start from this FEN instead of the initial position")
    parser.add_argument("--color", choices=("white", "black"), help="side the bot plays")
    parser.add_argument(
        "--orientation",
        choices=("white", "black"),
        help="colour displayed at the bottom of the board",
    )
    parser.add_argument("--rect", type=_parse_rect, help="board rectangle x,y,width,height")
    parser.add_argument("--dry-run", action="store_true", help="read and suggest, never touch the mouse")
    parser.add_argument("--once", action="store_true", help="stop after the first move (or suggestion)")
    parser.add_argument("--debug-vision", action="store_true", help="save annotated frames")
    parser.add_argument("--no-hotkeys", action="store_true", help="disable global hotkeys")
    parser.add_argument(
        "--image",
        help="use a saved screenshot instead of the screen (forces --dry-run; with --check-vision or --calibrate it is one-shot)",
    )
    parser.add_argument("--log-level", help="override the configured log level")
    parser.add_argument("--no-web", action="store_true", help="не запускать браузерную панель")
    parser.add_argument("--web-host", default="127.0.0.1", help="адрес панели (по умолчанию 127.0.0.1)")
    parser.add_argument("--web-port", type=int, default=8765, help="порт панели (по умолчанию 8765)")
    parser.add_argument("--no-browser", action="store_true", help="не открывать панель в браузере")
    parser.add_argument("--calibrate", action="store_true", help="capture templates from the start position and exit")
    parser.add_argument("--check-vision", action="store_true", help="read the board once and exit")
    parser.add_argument("--check-engine", action="store_true", help="run a Stockfish sanity check and exit")
    parser.add_argument("--version", action="version", version="lichess-vision-bot 1.0.0")
    return parser


def main(argv=None, *, default_config: str | Path = "config.json") -> int:
    parser = build_parser(default_config)
    args = parser.parse_args(argv)
    if not (0 <= args.web_port <= 65535):
        parser.error("--web-port must be between 0 and 65535")

    try:
        config = load_config(args.config)
        config = apply_overrides(
            config,
            rect=args.rect,
            color=args.color,
            orientation=args.orientation,
        )
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    setup_logging(config.logging, level_override=args.log_level)
    log.info("config: %s", Path(args.config).resolve())

    if args.image:
        if args.calibrate or args.check_vision:
            pass
        else:
            if not args.dry_run:
                log.warning("--image forces --dry-run")
            args.dry_run = True

    if args.calibrate:
        from .diagnostics import calibrate

        return calibrate(config, image=args.image)

    if args.check_vision:
        from .diagnostics import check_vision

        return check_vision(config, image=args.image)

    if args.check_engine:
        from .engine import EngineStartError, StockfishEngine

        try:
            engine = StockfishEngine(config.engine)
        except EngineStartError as exc:
            log.error("%s", exc)
            return 2
        try:
            log.info("engine: %s", engine.name)
            if engine.self_test():
                log.info("engine self-test passed (mate in one found)")
                return 0
            log.error("engine self-test failed")
            return 1
        finally:
            engine.close()

    if args.image and not (args.calibrate or args.check_vision):
        log.info("static image source: mouse input disabled")

    if not config.engine.path:
        log.error(
            "Stockfish not found. Put stockfish.exe next to run.py or set engine.path in config.json."
        )
        return 2

    if args.fen:
        try:
            chess.Board(args.fen)
        except ValueError as exc:
            print(f"invalid --fen: {exc}", file=sys.stderr)
            return 2

    from .bot import VisionBot

    try:
        bot = VisionBot(
            config,
            fen=args.fen,
            dry_run=args.dry_run,
            once=args.once,
            use_hotkeys=not args.no_hotkeys,
            debug_vision=args.debug_vision,
            image=args.image,
            web=not args.no_web,
            web_host=args.web_host,
            web_port=args.web_port,
            open_browser=not args.no_browser and args.image is None,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except CaptureError as exc:
        print(f"capture error: {exc}", file=sys.stderr)
        return 2

    try:
        bot.run()
    except KeyboardInterrupt:
        log.info("interrupted")
    except Exception:
        log.exception("bot crashed")
        return 1
    return 0
