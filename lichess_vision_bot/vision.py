"""Read the board from a warped image and convert it to a FEN placement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import chess
import numpy as np

from .board_detect import BoardGeometry
from .capture import Frame
from .coords import visual_to_square
from .pieces import (
    CellSignature,
    TemplateLibrary,
    looks_like_start,
    signature_from_cell,
)

START_BOARD_FEN = chess.Board().board_fen()


@dataclass
class VisualReading:
    signatures: list[list[Optional[CellSignature]]]
    cells: list[list[Optional[chess.Piece]]]
    scores: list[list[float]]
    occupied: int
    unknown: int
    confidence: float
    classified: bool
    start_pattern: bool
    key: str


@dataclass
class BoardReading:
    placement: str
    board: chess.Board
    valid: bool
    unknown: int
    confidence: float


def _visual_key(signatures: Sequence[Sequence[Optional[CellSignature]]]) -> str:
    parts: list[str] = []
    for row in signatures:
        for sig in row:
            if sig is None:
                parts.append(".")
            else:
                parts.append(f"{int(sig.mean_luma)}:{int(sig.area_fraction * 10000)}")
    return "|".join(parts)


class BoardReader:
    def __init__(
        self,
        library: Optional[TemplateLibrary],
        *,
        crop_pct: float = 6.0,
        confidence_threshold: float = 0.60,
    ):
        self.library = library
        self.crop_pct = crop_pct
        self.confidence_threshold = confidence_threshold
        self._prev_warp: Optional[np.ndarray] = None
        self._prev_visual: Optional[VisualReading] = None
        self._prev_library: Optional[TemplateLibrary] = None

    def _split_cells(self, warp: np.ndarray) -> list[list[np.ndarray]]:
        height, width = warp.shape[:2]
        step_y = height / 8.0
        step_x = width / 8.0
        cells: list[list[np.ndarray]] = []
        for row in range(8):
            y0 = int(round(row * step_y))
            y1 = int(round((row + 1) * step_y))
            line = []
            for col in range(8):
                x0 = int(round(col * step_x))
                x1 = int(round((col + 1) * step_x))
                line.append(warp[y0:y1, x0:x1])
            cells.append(line)
        return cells

    def visual(self, frame: Frame, geometry: BoardGeometry) -> VisualReading:
        warp = geometry.warp(frame.image)
        if (
            self._prev_warp is not None
            and self._prev_visual is not None
            and self._prev_library is self.library
            and np.array_equal(warp, self._prev_warp)
        ):
            return self._prev_visual

        cells = self._split_cells(warp)
        signatures: list[list[Optional[CellSignature]]] = []
        for row in range(8):
            line = []
            for col in range(8):
                line.append(signature_from_cell(cells[row][col], crop_pct=self.crop_pct))
            signatures.append(line)

        occupied_cells = [sig for line in signatures for sig in line if sig is not None]
        occupied = len(occupied_cells)
        pieces: list[list[Optional[chess.Piece]]] = [[None] * 8 for _ in range(8)]
        scores: list[list[float]] = [[0.0] * 8 for _ in range(8)]
        unknown = occupied
        confidence = 0.0
        classified = self.library is not None

        if self.library is not None and occupied:
            flat = [signatures[r][c] for r in range(8) for c in range(8)]
            results = self.library.classify_many(flat)
            total = 0.0
            unknown = 0
            for index, (piece, score) in enumerate(results):
                row, col = divmod(index, 8)
                if signatures[row][col] is None:
                    continue
                pieces[row][col] = piece
                scores[row][col] = score
                total += score
                if score < self.confidence_threshold:
                    unknown += 1
            confidence = total / occupied if occupied else 0.0

        occupied_grid = [[signatures[r][c] is not None for c in range(8)] for r in range(8)]
        reading = VisualReading(
            signatures=signatures,
            cells=pieces,
            scores=scores,
            occupied=occupied,
            unknown=unknown,
            confidence=confidence,
            classified=classified,
            start_pattern=looks_like_start(occupied_grid),
            key=_visual_key(signatures),
        )
        self._prev_warp = warp
        self._prev_visual = reading
        self._prev_library = self.library
        return reading

    def board_reading(self, visual: VisualReading, orientation: chess.Color) -> BoardReading:
        board = chess.Board(None)
        unknown = 0
        for row in range(8):
            for col in range(8):
                piece = visual.cells[row][col]
                if piece is None:
                    continue
                board.set_piece_at(visual_to_square(row, col, orientation), piece)
                if visual.scores[row][col] < self.confidence_threshold:
                    unknown += 1

        valid = (
            visual.classified
            and visual.occupied >= 2
            and unknown == 0
            and visual.confidence >= self.confidence_threshold
        )
        return BoardReading(
            placement=board.board_fen(),
            board=board,
            valid=valid,
            unknown=unknown,
            confidence=visual.confidence,
        )

    def classify_warped_cell(
        self, warp: np.ndarray, row: int, col: int
    ) -> tuple[Optional[chess.Piece], float]:
        if self.library is None or not (0 <= row < 8 and 0 <= col < 8):
            return None, 0.0
        cells = self._split_cells(warp)
        signature = signature_from_cell(cells[row][col], crop_pct=self.crop_pct)
        if signature is None:
            return None, 0.0
        return self.library.classify_one(signature)


def infer_orientation_from_visual(visual: VisualReading) -> Optional[chess.Color]:
    """Infer which colour sits at the bottom from a start-position reading."""
    bottom = [
        visual.cells[r][c]
        for r in (6, 7)
        for c in range(8)
        if visual.cells[r][c] is not None
    ]
    if len(bottom) < 12:
        return None
    white = sum(1 for piece in bottom if piece.color == chess.WHITE)
    if white >= 0.75 * len(bottom):
        return chess.WHITE
    if white <= 0.25 * len(bottom):
        return chess.BLACK
    return None


def infer_bottom_color(visual: VisualReading) -> Optional[chess.Color]:
    """Return the colour of the side at the bottom of the board.

    Lichess always shows the user's side at the bottom, and the bot plays that
    side.  Inspect the bottom ranks first; if they are too sparse, use the top
    ranks and invert them.
    """
    for row in (7, 6):
        pieces = [
            visual.cells[row][col]
            for col in range(8)
            if visual.cells[row][col] is not None
        ]
        if len(pieces) < 3:
            continue
        white = sum(1 for piece in pieces if piece.color == chess.WHITE)
        if white >= 0.75 * len(pieces):
            return chess.WHITE
        if white <= 0.25 * len(pieces):
            return chess.BLACK
    for row in (0, 1):
        pieces = [
            visual.cells[row][col]
            for col in range(8)
            if visual.cells[row][col] is not None
        ]
        if len(pieces) < 3:
            continue
        white = sum(1 for piece in pieces if piece.color == chess.WHITE)
        if white >= 0.75 * len(pieces):
            return chess.BLACK
        if white <= 0.25 * len(pieces):
            return chess.WHITE
    return None
