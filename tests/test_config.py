from __future__ import annotations

import json
from pathlib import Path

import pytest

from lichess_vision_bot.config import ConfigError, apply_overrides, load_config


def write_config(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_defaults(tmp_path):
    path = write_config(tmp_path, {})
    config = load_config(path)
    assert config.vision.monitor == 1
    assert config.vision.color == "auto"
    assert config.input.mode == "drag"
    assert config.engine.move_time_s == 1.0


def test_unknown_section_key(tmp_path):
    path = write_config(tmp_path, {"vision": {"nope": 1}})
    with pytest.raises(ConfigError):
        load_config(path)


def test_unknown_top_level_key(tmp_path):
    path = write_config(tmp_path, {"wat": 1})
    with pytest.raises(ConfigError):
        load_config(path)


def test_invalid_choice(tmp_path):
    path = write_config(tmp_path, {"vision": {"color": "green"}})
    with pytest.raises(ConfigError):
        load_config(path)


def test_overrides(tmp_path):
    path = write_config(tmp_path, {})
    config = load_config(path)
    config = apply_overrides(config, rect=(10, 20, 600, 600), color="white", no_input=True)
    assert config.vision.board_rect == (10, 20, 600, 600)
    assert config.vision.color == "white"
    assert config.input.enabled is False


def test_logging_path_is_resolved(tmp_path):
    path = write_config(tmp_path, {"logging": {"file": "logs/bot.log"}})
    config = load_config(path)
    assert Path(config.logging.file).is_absolute()
    assert Path(config.logging.file) == tmp_path / "logs" / "bot.log"


def test_ignore_window_default(tmp_path):
    config = load_config(write_config(tmp_path, {}))
    assert config.vision.ignore_window_title == "Lichess Bot"
    assert config.vision.source == "dom"


def test_promotion_wait_default(tmp_path):
    config = load_config(write_config(tmp_path, {}))
    assert config.input.promotion_wait_s == 0.9
