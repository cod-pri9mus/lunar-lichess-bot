from __future__ import annotations

import chess
import numpy as np

from lichess_vision_bot.board_detect import make_geometry
from lichess_vision_bot.capture import Frame
from lichess_vision_bot.turn import detect_turn
from synthetic import render_board


def _frame_with_clocks(top_luma: int, bottom_luma: int) -> tuple[Frame, object]:
    board = render_board(chess.Board())
    side = board.shape[0]
    page = np.full((side + 240, side + 80, 3), 30, dtype=np.uint8)
    page[120 : 120 + side, 40 : 40 + side] = board
    page[20:100, 40 : 40 + side] = top_luma
    page[140 + side : 220 + side, 40 : 40 + side] = bottom_luma
    quad = np.array(
        [[40, 120], [40 + side - 1, 120], [40 + side - 1, 120 + side - 1], [40, 120 + side - 1]],
        dtype=np.float32,
    )
    geometry = make_geometry(quad, (0, 0), inset_pct=0.0)
    return Frame(image=page, origin=(0, 0)), geometry


def test_bright_bottom_clock_means_bottom_to_move():
    frame, geometry = _frame_with_clocks(top_luma=80, bottom_luma=220)
    assert detect_turn(frame, geometry, chess.WHITE) == chess.WHITE


def test_bright_top_clock_means_top_to_move():
    frame, geometry = _frame_with_clocks(top_luma=220, bottom_luma=80)
    assert detect_turn(frame, geometry, chess.WHITE) == chess.BLACK


def test_unreadable_clocks_return_none():
    frame, geometry = _frame_with_clocks(top_luma=140, bottom_luma=140)
    assert detect_turn(frame, geometry, chess.BLACK) is None
