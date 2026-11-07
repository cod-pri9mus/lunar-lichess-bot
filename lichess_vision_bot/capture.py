"""Fast screen capture with a physical-pixel coordinate origin."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import mss
import numpy as np

from .imgio import imread


class CaptureError(RuntimeError):
    pass


@dataclass(frozen=True)
class Frame:
    image: np.ndarray            # BGR
    origin: tuple[int, int]      # absolute screen coordinate of image[0, 0]


class ScreenCapture:
    def __init__(self, monitor: int = 1, rect: Optional[tuple[int, int, int, int]] = None):
        self._sct = mss.mss()
        monitors = self._sct.monitors
        if not (1 <= monitor < len(monitors)):
            raise CaptureError(
                f"monitor {monitor} does not exist; available indices: 1..{len(monitors) - 1}"
            )
        self._monitor = monitors[monitor]
        self._rect = rect

    def grab(self) -> Frame:
        if self._rect is not None:
            x, y, w, h = self._rect
            region = {"left": int(x), "top": int(y), "width": int(w), "height": int(h)}
            origin = (int(x), int(y))
        else:
            region = self._monitor
            origin = (int(self._monitor["left"]), int(self._monitor["top"]))
        try:
            shot = self._sct.grab(region)
        except Exception as exc:  # mss raises its own ScreenShotError
            raise CaptureError(f"screen capture failed: {exc}") from exc
        bgra = np.asarray(shot)
        bgr = cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR)
        return Frame(image=bgr, origin=origin)

    @property
    def monitor_region(self) -> dict:
        return dict(self._monitor)

    def close(self) -> None:
        try:
            self._sct.close()
        except Exception:
            pass


class StaticCapture:
    """Replay a saved screenshot; useful for dry-runs and diagnostics."""

    def __init__(self, path: str):
        image = imread(path)
        if image is None:
            raise CaptureError(f"cannot read image: {path}")
        self._frame = Frame(image=image, origin=(0, 0))

    def grab(self) -> Frame:
        return self._frame

    def monitor_region(self) -> dict:
        return {"left": 0, "top": 0, "width": self._frame.image.shape[1], "height": self._frame.image.shape[0]}

    def close(self) -> None:
        pass
