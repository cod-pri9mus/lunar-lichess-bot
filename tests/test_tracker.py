from __future__ import annotations

import chess
import pytest

from lichess_vision_bot.tracker import GameTracker


def placement_after(fen: str, move_uci: str) -> str:
    board = chess.Board(fen)
    board.push_uci(move_uci)
    return board.board_fen()


def test_infers_e4():
    tracker = GameTracker(chess.Board(), chess.BLACK)
    placement = placement_after(chess.STARTING_FEN, "e2e4")
    move = tracker.infer_move(placement)
    assert move == chess.Move.from_uci("e2e4")


def test_infers_castling():
    fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
    tracker = GameTracker(chess.Board(fen), chess.BLACK)
    placement = placement_after(fen, "e1g1")
    assert tracker.infer_move(placement) == chess.Move.from_uci("e1g1")


def test_infers_en_passant():
    fen = "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2"
    tracker = GameTracker(chess.Board(fen), chess.BLACK)
    placement = placement_after(fen, "e5d6")
    assert tracker.infer_move(placement) == chess.Move.from_uci("e5d6")


def test_infers_promotion_choice():
    fen = "4k3/1P6/8/8/8/8/8/4K3 w - - 0 1"
    tracker = GameTracker(chess.Board(fen), chess.BLACK)
    placement = placement_after(fen, "b7b8n")
    assert tracker.infer_move(placement) == chess.Move.from_uci("b7b8n")


def test_rewind_and_undo():
    tracker = GameTracker(chess.Board(), chess.WHITE)
    start = tracker.placement()
    tracker.push(chess.Move.from_uci("e2e4"))
    tracker.push(chess.Move.from_uci("e7e5"))
    assert tracker.rewind_to(start)
    assert tracker.placement() == start
    assert tracker.undo() is False


def test_push_rejects_illegal():
    tracker = GameTracker(chess.Board(), chess.WHITE)
    with pytest.raises(Exception):
        tracker.push(chess.Move.from_uci("e2e5"))


def test_placement_matches_ignores_checked_king():
    fen = "rnbqkb1r/pp3ppp/3p1n2/1Bp5/3NP3/2N5/PPP2PPP/R1BQK2R b KQkq - 0 7"
    board = chess.Board(fen)
    assert board.is_check()
    tracker = GameTracker(board, chess.BLACK)
    observed = board.copy()
    observed.remove_piece_at(chess.E8)
    observed.set_piece_at(chess.E8, chess.Piece(chess.QUEEN, chess.WHITE))
    assert tracker.placement_matches(observed)


def test_infer_move_tolerates_one_misread_square():
    fen = "rnbqkb1r/pp3ppp/3p1n2/1Bp5/3NP3/2N5/PPP2PPP/R1BQK2R b KQkq - 0 7"
    tracker = GameTracker(chess.Board(fen), chess.WHITE)
    after = chess.Board(fen)
    after.push_uci("b8c6")
    observed = after.copy()
    observed.remove_piece_at(chess.E8)
    observed.set_piece_at(chess.E8, chess.Piece(chess.QUEEN, chess.WHITE))
    move = tracker.infer_move(observed, tolerance=2)
    assert move == chess.Move.from_uci("b8c6")
    assert tracker.last_infer_diff == 1


def test_our_king_in_check_is_ignored():
    board = chess.Board("4k3/8/8/8/8/8/4r3/4K3 w - - 0 1")
    assert board.is_check()
    tracker = GameTracker(board, chess.WHITE)
    observed = board.copy()
    observed.remove_piece_at(chess.E1)
    observed.set_piece_at(chess.E1, chess.Piece(chess.QUEEN, chess.WHITE))
    assert tracker.placement_matches(observed)
