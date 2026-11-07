"""Configuration loading, defaults and validation."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, Optional


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class EngineConfig:
    path: Optional[str] = None
    threads: int = 2
    hash_mb: int = 256
    skill_level: Optional[int] = None
    uci_elo: Optional[int] = None
    move_time_s: float = 1.0
    depth: Optional[int] = None
    move_overhead_ms: int = 100


@dataclass(frozen=True)
class VisionConfig:
    monitor: int = 1
    board_rect: Optional[tuple[int, int, int, int]] = None
    ignore_window_title: Optional[str] = "Lichess Bot"
    orientation: str = "auto"          # auto | white | black : colour at the bottom
    color: str = "auto"                # auto | white | black : the side we play
    capture_fps: float = 12.0
    stable_reads: int = 3
    confidence_threshold: float = 0.60
    cell_crop_pct: float = 6.0
    board_inset_pct: float = 1.0
    redetect_interval_s: float = 15.0
    templates_dir: str = "templates"
    auto_save_templates: bool = True
    debug_dir: str = "debug"
    save_debug_frames: bool = False


@dataclass(frozen=True)
class InputConfig:
    enabled: bool = True
    mode: str = "drag"                 # drag | click
    human_like: bool = True
    move_duration_s: tuple[float, float] = (0.14, 0.28)
    jitter_pct: float = 9.0
    down_pause_s: tuple[float, float] = (0.06, 0.12)
    up_pause_s: tuple[float, float] = (0.03, 0.08)
    post_move_wait_s: float = 0.35
    confirm_timeout_s: float = 2.2
    max_move_retries: int = 3
    promotion_mode: str = "auto"       # auto | auto_queen | dialog
    promotion_wait_s: float = 0.9      # let the Lichess promotion dialog animate
    focus_window: Optional[str] = None
    park_outside: bool = True


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    file: Optional[str] = "logs/bot.log"
    max_bytes: int = 5_000_000
    backup_count: int = 5


@dataclass(frozen=True)
class BotConfig:
    engine: EngineConfig
    vision: VisionConfig
    input: InputConfig
    logging: LoggingConfig
    base_dir: Path


def _section(cls, data: Any, name: str):
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"'{name}' must be a JSON object")
    allowed = {f.name for f in fields(cls)}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"'{name}' has unknown key(s): {', '.join(unknown)}")
    return cls(**data)


def _find_engine(configured: Optional[str], base_dir: Path) -> Optional[Path]:
    candidates: list[Path] = []
    if configured:
        p = Path(configured).expanduser()
        candidates.append(p if p.is_absolute() else base_dir / p)
    candidates.extend([
        base_dir / "stockfish.exe",
        base_dir / "stockfish" / "stockfish.exe",
    ])
    stockfish_dir = base_dir / "stockfish"
    if stockfish_dir.is_dir():
        candidates.extend(sorted(stockfish_dir.rglob("stockfish*.exe")))
    which = shutil.which("stockfish")
    if which:
        candidates.append(Path(which))
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


def _validate_choice(value: str, allowed: tuple[str, ...], name: str) -> None:
    if value not in allowed:
        raise ConfigError(f"'{name}' must be one of {allowed}, got {value!r}")


def _validate_range(value: float, low: float, high: float, name: str) -> None:
    if not (low <= value <= high):
        raise ConfigError(f"'{name}' must be between {low} and {high}, got {value}")


def _validate(config: BotConfig) -> None:
    v = config.vision
    i = config.input
    _validate_choice(v.orientation, ("auto", "white", "black"), "vision.orientation")
    _validate_choice(v.color, ("auto", "white", "black"), "vision.color")
    _validate_range(v.capture_fps, 1.0, 30.0, "vision.capture_fps")
    _validate_range(v.confidence_threshold, 0.30, 0.99, "vision.confidence_threshold")
    _validate_range(v.stable_reads, 1, 10, "vision.stable_reads")
    _validate_range(v.cell_crop_pct, 0.0, 20.0, "vision.cell_crop_pct")
    _validate_range(v.board_inset_pct, 0.0, 10.0, "vision.board_inset_pct")
    if v.ignore_window_title is not None and not isinstance(v.ignore_window_title, str):
        raise ConfigError("vision.ignore_window_title must be a string or null")
    _validate_choice(i.mode, ("drag", "click"), "input.mode")
    _validate_choice(i.promotion_mode, ("auto", "auto_queen", "dialog"), "input.promotion_mode")
    _validate_range(config.engine.move_time_s, 0.05, 30.0, "engine.move_time_s")
    _validate_range(config.engine.threads, 1, 128, "engine.threads")
    _validate_range(config.engine.hash_mb, 16, 65536, "engine.hash_mb")
    if config.engine.depth is not None:
        _validate_range(config.engine.depth, 1, 60, "engine.depth")
    if config.engine.skill_level is not None:
        _validate_range(config.engine.skill_level, 0, 20, "engine.skill_level")
    if config.engine.uci_elo is not None:
        _validate_range(config.engine.uci_elo, 1320, 3190, "engine.uci_elo")
    if len(i.move_duration_s) != 2 or i.move_duration_s[0] <= 0 or i.move_duration_s[1] < i.move_duration_s[0]:
        raise ConfigError("input.move_duration_s must be [min, max] with 0 < min <= max")
    if len(i.down_pause_s) != 2 or len(i.up_pause_s) != 2:
        raise ConfigError("input.down_pause_s and input.up_pause_s must be [min, max]")
    _validate_range(i.jitter_pct, 0.0, 30.0, "input.jitter_pct")
    _validate_range(i.confirm_timeout_s, 0.3, 15.0, "input.confirm_timeout_s")
    _validate_range(i.max_move_retries, 0, 20, "input.max_move_retries")
    _validate_range(i.promotion_wait_s, 0.1, 3.0, "input.promotion_wait_s")
    if v.board_rect is not None:
        rect = v.board_rect
        if len(rect) != 4 or any(int(x) != x for x in rect):
            raise ConfigError("vision.board_rect must be four integers [x, y, width, height]")
        if rect[2] < 100 or rect[3] < 100:
            raise ConfigError("vision.board_rect width and height must be >= 100")


def load_config(path: str | Path) -> BotConfig:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a JSON object")

    allowed = {"engine", "vision", "input", "logging"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigError(f"unknown top-level key(s): {', '.join(unknown)}")

    base_dir = path.parent
    engine = _section(EngineConfig, raw.get("engine", {}), "engine")
    resolved = _find_engine(engine.path, base_dir)
    if resolved is not None and str(resolved) != engine.path:
        engine = replace(engine, path=str(resolved))
    config = BotConfig(
        engine=engine,
        vision=_section(VisionConfig, raw.get("vision", {}), "vision"),
        input=_section(InputConfig, raw.get("input", {}), "input"),
        logging=_section(LoggingConfig, raw.get("logging", {}), "logging"),
        base_dir=base_dir,
    )
    if config.logging.file:
        log_path = Path(config.logging.file).expanduser()
        if not log_path.is_absolute():
            config = replace(
                config,
                logging=replace(config.logging, file=str(base_dir / log_path)),
            )
    _validate(config)
    return config


def apply_overrides(
    config: BotConfig,
    *,
    rect: Optional[tuple[int, int, int, int]] = None,
    color: Optional[str] = None,
    orientation: Optional[str] = None,
    no_input: bool = False,
) -> BotConfig:
    vision = config.vision
    inp = config.input
    if rect is not None:
        vision = replace(vision, board_rect=rect)
    if color is not None:
        vision = replace(vision, color=color)
    if orientation is not None:
        vision = replace(vision, orientation=orientation)
    if no_input:
        inp = replace(inp, enabled=False)
    result = replace(config, vision=vision, input=inp)
    _validate(result)
    return result
