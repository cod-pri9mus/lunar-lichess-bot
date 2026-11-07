#!/usr/bin/env python3
"""Launcher for the vision bot."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from lichess_vision_bot.cli import main


def _already_running() -> bool:
    if sys.platform != "win32":
        return False
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, "LunarLichessBot")
    if not handle:
        return False
    return ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS


if __name__ == "__main__":
    if _already_running():
        print("Lunar Lichess Bot уже запущен.")
        raise SystemExit(1)
    raise SystemExit(main(default_config=Path(__file__).resolve().with_name("config.json")))
