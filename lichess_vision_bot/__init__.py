"""Vision-driven Lichess autoplay bot.

The package enables per-monitor DPI awareness on import on Windows so that
``mss`` screen coordinates and ``pyautogui`` cursor coordinates refer to the
same physical pixels.
"""

from __future__ import annotations

import ctypes
import sys

__version__ = "1.0.0"


def enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor v2
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


enable_dpi_awareness()
