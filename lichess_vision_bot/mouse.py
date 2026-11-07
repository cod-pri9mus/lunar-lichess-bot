"""Human-like mouse input for board moves."""

from __future__ import annotations

import logging
import math
import random
import time
from typing import Callable, Optional

import chess
import pyautogui

from .board_detect import BoardGeometry
from .config import InputConfig
from .coords import square_to_visual

log = logging.getLogger(__name__)


class MouseController:
    def __init__(self, config: InputConfig):
        self._config = config
        self._py = pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0

    def focus_window(self, title: Optional[str]) -> bool:
        if not title:
            return False
        try:
            import pygetwindow as gw

            matches = [w for w in gw.getAllWindows() if title.lower() in (w.title or "").lower()]
            if not matches:
                return False
            window = matches[0]
            if window.isMinimized:
                window.restore()
            window.activate()
            return True
        except Exception as exc:
            log.debug("window focus failed: %s", exc)
            return False

    def make_move(
        self,
        geometry: BoardGeometry,
        move: chess.Move,
        orientation: chess.Color,
        *,
        promotion_picker: Optional[Callable[[chess.Move], bool]] = None,
    ) -> None:
        source_row, source_col = square_to_visual(move.from_square, orientation)
        target_row, target_col = square_to_visual(move.to_square, orientation)
        source = geometry.cell_to_screen(source_col, source_row)
        target = geometry.cell_to_screen(target_col, target_row)
        cell_px = geometry.cell_size_screen()
        source = self._jitter(source, cell_px)
        target = self._jitter(target, cell_px)

        if self._config.mode == "click":
            self._click(source)
            time.sleep(random.uniform(0.08, 0.14))
            self._click(target)
        else:
            self._drag(source, target)

        if move.promotion and promotion_picker:
            # Lichess opens an animated promotion strip after the drag.  Clicking
            # it in the same tick often lands before the strip is there, so the
            # pawn stays on the last rank with no piece chosen.
            time.sleep(self._config.promotion_wait_s)
            promotion_picker(move)

        time.sleep(self._config.post_move_wait_s)
        # Leave the target square immediately: Lichess draws a hover outline
        # there, which changes the cell signature and can make the confirmation
        # read look unstable forever (the "no clean board read" stall).
        self.park(geometry)

    def _jitter(self, point: tuple[int, int], cell_px: float) -> tuple[float, float]:
        jitter = cell_px * self._config.jitter_pct / 100.0
        return (
            point[0] + random.uniform(-jitter, jitter),
            point[1] + random.uniform(-jitter, jitter),
        )

    def _click(self, point: tuple[float, float]) -> None:
        self._py.moveTo(round(point[0]), round(point[1]), _pause=False)
        time.sleep(random.uniform(0.02, 0.05))
        self._py.click()

    def _drag(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        duration = (
            random.uniform(*self._config.move_duration_s)
            if self._config.human_like
            else 0.12
        )
        path = self._path(start, end, human_like=self._config.human_like)
        self._py.moveTo(round(start[0]), round(start[1]), _pause=False)
        time.sleep(random.uniform(0.02, 0.05))
        self._py.mouseDown(button="left")
        time.sleep(random.uniform(*self._config.down_pause_s))

        began = time.perf_counter()
        count = max(1, len(path) - 1)
        for index, point in enumerate(path[1:], start=1):
            self._py.moveTo(round(point[0]), round(point[1]), _pause=False)
            due = began + duration * index / count
            delay = due - time.perf_counter()
            if delay > 0:
                time.sleep(delay)

        time.sleep(random.uniform(*self._config.up_pause_s))
        self._py.mouseUp(button="left")

    def _path(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        *,
        human_like: bool,
        steps: int = 16,
    ) -> list[tuple[float, float]]:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        distance = math.hypot(dx, dy)
        if not human_like or distance < 20:
            return [
                (start[0] + dx * i / steps, start[1] + dy * i / steps)
                for i in range(steps + 1)
            ]
        perpendicular = (-dy / distance, dx / distance)
        bend = random.uniform(-0.06, 0.06) * distance
        c1 = (
            start[0] + dx * 0.33 + perpendicular[0] * bend,
            start[1] + dy * 0.33 + perpendicular[1] * bend,
        )
        c2 = (
            start[0] + dx * 0.66 - perpendicular[0] * bend * 0.6,
            start[1] + dy * 0.66 - perpendicular[1] * bend * 0.6,
        )
        points = []
        for i in range(steps + 1):
            t = i / steps
            u = 1.0 - t
            x = u**3 * start[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t**3 * end[0]
            y = u**3 * start[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t**3 * end[1]
            points.append((x, y))
        return points

    def press_key(self, key: str) -> None:
        self._py.press(key)

    def park(self, geometry: BoardGeometry) -> None:
        if not self._config.park_outside:
            return
        x_min = float(min(p[0] for p in geometry.quad))
        x_max = float(max(p[0] for p in geometry.quad))
        y_mid = float(sum(float(p[1]) for p in geometry.quad) / 4.0)
        target_x = x_min - 40 if x_min > 60 else x_max + 40
        sx, sy = geometry.frame_point_to_screen(target_x, y_mid)
        try:
            self._py.moveTo(sx, sy, _pause=False)
        except Exception:
            pass
