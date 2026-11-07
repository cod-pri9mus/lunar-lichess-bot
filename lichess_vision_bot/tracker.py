"""Legal-game tracking and move inference from observed piece placement."""

from __future__ import annotations

import chess


class TrackerError(RuntimeError):
    pass


class GameTracker:
    def __init__(self, board: chess.Board, our_color: chess.Color):
        self.board = board
        self.our_color = our_color
        self._snapshots: list[str] = []
        self.last_infer_diff = 0

    def our_turn(self) -> bool:
        return self.board.turn == self.our_color

    def placement(self) -> str:
        return self.board.board_fen()

    @staticmethod
    def same_placement(board: chess.Board, observed: chess.Board) -> bool:
        """Compare piece placement, ignoring the king square of a side in check.

        Lichess paints a red check glow around the checked king; that tint can
        make the piece classifier label the king as another piece.  The king
        cannot be captured, so the tracker's king square is authoritative.
        """
        ignore = None
        if board.is_check():
            ignore = board.king(board.turn)
        for square in chess.SQUARES:
            if square == ignore:
                continue
            if board.piece_at(square) != observed.piece_at(square):
                return False
        return True

    def placement_matches(self, observed: chess.Board | str) -> bool:
        if isinstance(observed, str):
            observed = _board_from_placement(observed)
        return self.same_placement(self.board, observed)

    def push(self, move: chess.Move) -> None:
        if move not in self.board.legal_moves:
            raise TrackerError(f"illegal move {move.uci()} in {self.board.fen()}")
        self._snapshots.append(self.board.board_fen())
        self.board.push(move)

    def undo(self) -> bool:
        if not self.board.move_stack:
            return False
        self.board.pop()
        if self._snapshots:
            self._snapshots.pop()
        return True

    def rewind_to(self, placement: str) -> bool:
        for index in range(len(self._snapshots) - 1, -1, -1):
            if self._snapshots[index] == placement:
                while len(self._snapshots) > index:
                    self.board.pop()
                    self._snapshots.pop()
                return True
        return False

    def infer_move(
        self, observed: chess.Board | str, *, tolerance: int = 0
    ) -> chess.Move | None:
        """Find the legal move whose resulting placement matches the observation.

        ``tolerance`` allows a few misclassified squares.  The checked king's
        square is always ignored in the simulated result, so a red check glow
        cannot break move inference.
        """
        if isinstance(observed, str):
            observed = _board_from_placement(observed)
        self.last_infer_diff = 0
        if self.placement_matches(observed):
            return None

        best_move: chess.Move | None = None
        best_diff = tolerance + 1
        for move in list(self.board.legal_moves):
            self.board.push(move)
            ignore = self.board.king(self.board.turn) if self.board.is_check() else None
            diff = 0
            for square in chess.SQUARES:
                if square == ignore:
                    continue
                if self.board.piece_at(square) != observed.piece_at(square):
                    diff += 1
                    if diff >= best_diff:
                        break
            self.board.pop()
            if diff < best_diff:
                best_diff = diff
                best_move = move
                if diff == 0:
                    break
        self.last_infer_diff = best_diff if best_move is not None else 0
        return best_move

    def is_game_over(self) -> bool:
        return self.board.is_game_over(claim_draw=False)

    def ascii(self) -> str:
        return str(self.board)


def _board_from_placement(placement: str) -> chess.Board:
    return chess.Board(placement + " w - - 0 1")
