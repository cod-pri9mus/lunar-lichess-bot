from __future__ import annotations

import chess
import numpy as np

from lichess_vision_bot.board_detect import find_board
from synthetic import board_in_page, render_board


def test_finds_board_on_a_page():
    board = render_board(chess.Board(), cell=80)
    page, (x, y, w, h) = board_in_page(board, page_size=(1200, 900), offset=(300, 100))
    found = find_board(page)
    assert found is not None
    quad, score = found
    assert score > 1.5
    xs = quad[:, 0]
    ys = quad[:, 1]
    assert abs(float(xs.min()) - x) < 12
    assert abs(float(ys.min()) - y) < 12
    assert abs(float(xs.max()) - (x + w)) < 12
    assert abs(float(ys.max()) - (y + h)) < 12


def test_plain_page_has_no_board():
    page = np.full((900, 1200, 3), 230, dtype=np.uint8)
    assert find_board(page) is None


def test_small_board_is_ignored():
    board = render_board(chess.Board(), cell=20)
    page, _ = board_in_page(board, page_size=(1600, 1200), offset=(700, 500))
    assert find_board(page) is None


def test_excludes_panel_preview_window():
    page = np.full((1000, 1400, 3), 235, dtype=np.uint8)
    preview = render_board(chess.Board(), cell=75)   # 600x600 panel preview
    real = render_board(chess.Board(), cell=62)      # 496x496 Lichess board
    page[40:640, 40:640] = preview
    page[200:696, 800:1296] = real

    found = find_board(page, exclude_rects=((0, 0, 700, 700),))
    assert found is not None
    quad, _score = found
    assert float(quad[:, 0].min()) > 700
    assert float(quad[:, 1].min()) > 190
