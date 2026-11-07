from __future__ import annotations

import chess
import cv2
import numpy as np
import pytest

from lichess_vision_bot.board_detect import make_geometry
from lichess_vision_bot.capture import Frame
from lichess_vision_bot.pieces import (
    build_start_library,
    load_library,
    signature_from_cell,
)
from lichess_vision_bot.vision import (
    START_BOARD_FEN,
    BoardReader,
    infer_bottom_color,
)
from synthetic import ASSETS, render_board

GEOMETRY = make_geometry(
    np.array([[0, 0], [799, 0], [799, 799], [0, 799]], dtype=np.float32),
    (0, 0),
    inset_pct=0.0,
)


def read(image, orientation=chess.WHITE, threshold=0.60):
    library = load_library(ASSETS)
    assert library is not None
    reader = BoardReader(library, crop_pct=6.0, confidence_threshold=threshold)
    frame = Frame(image=image, origin=(0, 0))
    visual = reader.visual(frame, GEOMETRY)
    return reader, visual, reader.board_reading(visual, orientation)


def test_start_position_round_trip():
    image = render_board(chess.Board())
    _reader, visual, reading = read(image)
    assert visual.occupied == 32
    assert visual.unknown == 0
    assert reading.valid
    assert reading.placement == START_BOARD_FEN


def test_midgame_position_round_trip():
    fen = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"
    board = chess.Board(fen)
    image = render_board(board)
    _reader, _visual, reading = read(image)
    assert reading.valid
    assert reading.placement == board.board_fen()


def test_bottom_colour_matches_the_visible_board():
    image = render_board(chess.Board())
    _reader, visual, _reading = read(image)
    assert infer_bottom_color(visual) == chess.WHITE

    flipped = render_board(chess.Board(), orientation=chess.BLACK)
    _reader, visual, _reading = read(flipped, chess.BLACK)
    assert infer_bottom_color(visual) == chess.BLACK


def test_flipped_board_round_trip():
    fen = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"
    board = chess.Board(fen)
    image = render_board(board, orientation=chess.BLACK)
    _reader, _visual, reading = read(image, orientation=chess.BLACK)
    assert reading.valid
    assert reading.placement == board.board_fen()


def test_start_bootstrap_infers_bottom_colour():
    image = render_board(chess.Board())
    library = load_library(ASSETS)
    reader = BoardReader(library, crop_pct=6.0)
    visual = reader.visual(Frame(image, (0, 0)), GEOMETRY)
    built = build_start_library(visual.signatures)
    assert built is not None
    auto_library, bottom = built
    assert bottom == chess.WHITE
    assert len(auto_library.samples) >= 12


def test_start_bootstrap_honours_explicit_bottom_colour():
    image = render_board(chess.Board())
    reader = BoardReader(None, crop_pct=6.0)
    visual = reader.visual(Frame(image, (0, 0)), GEOMETRY)
    built = build_start_library(visual.signatures, bottom_color=chess.BLACK)
    assert built is not None
    _library, bottom = built
    assert bottom == chess.BLACK


def test_start_bootstrap_flipped_infers_black():
    image = render_board(chess.Board(), orientation=chess.BLACK)
    reader = BoardReader(None, crop_pct=6.0)
    visual = reader.visual(Frame(image, (0, 0)), GEOMETRY)
    built = build_start_library(visual.signatures)
    assert built is not None
    _library, bottom = built
    assert bottom == chess.BLACK


def test_empty_board_is_empty():
    image = render_board("8/8/8/8/8/8/8/8")
    _reader, visual, reading = read(image)
    assert visual.occupied == 0
    assert not visual.start_pattern
    assert not reading.valid


def test_check_highlight_keeps_black_king():
    fen = "rnbqkb1r/pp3ppp/3p1n2/1Bp5/3NP3/2N5/PPP2PPP/R1BQK2R b KQkq - 0 7"
    board = chess.Board(fen)
    assert board.is_check()
    image = render_board(board, check_square=chess.E8)
    _reader, visual, reading = read(image)
    assert reading.valid
    assert reading.placement == board.board_fen()


@pytest.mark.parametrize(
    "fen",
    [
        "8/8/8/8/8/8/8/K6k w - - 0 1",
        "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
        "8/2P5/3K4/8/8/8/8/7k w - - 0 1",
    ],
)
def test_sparse_positions(fen):
    board = chess.Board(fen)
    image = render_board(board)
    _reader, _visual, reading = read(image)
    assert reading.valid
    assert reading.placement == board.board_fen()


def _draw_corner_coords(cell):
    cv2.putText(
        cell, "a", (34, 92), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (245, 245, 245), 3, cv2.LINE_AA
    )
    cv2.putText(
        cell, "8", (78, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (245, 245, 245), 3, cv2.LINE_AA
    )
    return cell


def test_coordinate_labels_on_an_empty_corner_are_ignored():
    cell = render_board("8/8/8/8/8/8/8/8")[0:100, 0:100].copy()
    _draw_corner_coords(cell)
    assert signature_from_cell(cell, crop_pct=6.0) is None


def test_coordinate_labels_keep_a_real_piece():
    cell = render_board("r7/8/8/8/8/8/8/8")[0:100, 0:100].copy()
    _draw_corner_coords(cell)
    signature = signature_from_cell(cell, crop_pct=6.0)
    assert signature is not None
    library = load_library(ASSETS)
    assert library is not None
    piece, score = library.classify_one(signature)
    assert piece == chess.Piece(chess.ROOK, chess.BLACK)
    assert score >= 0.60
