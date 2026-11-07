"""Square <-> visual grid coordinate mapping."""

from __future__ import annotations

import chess


def square_to_visual(square: chess.Square, orientation: chess.Color) -> tuple[int, int]:
    """Return (row, col) in the on-screen 8x8 grid (row 0 is the top)."""
    file_index = chess.square_file(square)
    rank_index = chess.square_rank(square)
    if orientation == chess.WHITE:
        return 7 - rank_index, file_index
    return rank_index, 7 - file_index


def visual_to_square(row: int, col: int, orientation: chess.Color) -> chess.Square:
    if orientation == chess.WHITE:
        return chess.square(col, 7 - row)
    return chess.square(7 - col, row)


def visual_cell_name(row: int, col: int) -> str:
    return f"{'abcdefgh'[col]}{8 - row}"
