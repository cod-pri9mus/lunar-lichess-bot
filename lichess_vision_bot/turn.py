"""Infer whose turn it is from the Lichess clocks.

Lichess highlights the clock of the side to move: the active clock is bright
and the idle one is dimmed.  The clocks sit just above and below the board, so
their mean brightness gives the turn without OCR and without reading a FEN.
"""

from __future__ import annotations

from typing import Optional

import chess
import cv2
import numpy as np

from .board_detect import BoardGeometry
from .capture import Frame


def detect_turn(
    frame: Frame,
    geometry: BoardGeometry,
    bottom_color: chess.Color,
) -> Optional[chess.Color]:
    """Return the colour to move, or None when the clocks are not readable."""
    image = frame.image
    height, width = image.shape[:2]
    quad = geometry.quad
    x_min = float(np.min(quad[:, 0]))
    x_max = float(np.max(quad[:, 0]))
    y_min = float(np.min(quad[:, 1]))
    y_max = float(np.max(quad[:, 1]))
    board_w = x_max - x_min
    board_h = y_max - y_min
    if board_w < 50 or board_h < 50:
        return None

    x0 = int(round(x_min + 0.05 * board_w))
    x1 = int(round(x_max - 0.05 * board_w))
    x0 = max(0, min(width - 1, x0))
    x1 = max(x0 + 1, min(width, x1))

    def strip(y_start: float, y_end: float) -> Optional[np.ndarray]:
        top = max(0, min(height - 1, int(round(y_start))))
        bottom = max(top + 1, min(height, int(round(y_end))))
        region = image[top:bottom, x0:x1]
        return region if region.size else None

    top = strip(y_min - 0.12 * board_h, y_min - 0.02 * board_h)
    bottom = strip(y_max + 0.02 * board_h, y_max + 0.12 * board_h)
    if top is None or bottom is None:
        return None

    top_luma = float(cv2.cvtColor(top, cv2.COLOR_BGR2GRAY).mean())
    bottom_luma = float(cv2.cvtColor(bottom, cv2.COLOR_BGR2GRAY).mean())
    if abs(top_luma - bottom_luma) < 6.0:
        return None
    if bottom_luma > top_luma:
        return bottom_color
    return not bottom_color
