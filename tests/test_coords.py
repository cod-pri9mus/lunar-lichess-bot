from __future__ import annotations

import chess

from lichess_vision_bot.coords import square_to_visual, visual_to_square


def test_coordinate_round_trip_white():
    for square in chess.SQUARES:
        row, col = square_to_visual(square, chess.WHITE)
        assert visual_to_square(row, col, chess.WHITE) == square


def test_coordinate_round_trip_black():
    for square in chess.SQUARES:
        row, col = square_to_visual(square, chess.BLACK)
        assert visual_to_square(row, col, chess.BLACK) == square


def test_corners():
    assert square_to_visual(chess.A1, chess.WHITE) == (7, 0)
    assert square_to_visual(chess.H8, chess.WHITE) == (0, 7)
    assert square_to_visual(chess.A1, chess.BLACK) == (0, 7)
    assert square_to_visual(chess.H8, chess.BLACK) == (7, 0)
