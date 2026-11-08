"""Piece template extraction, classification and on-disk libraries.

Templates are background-normalised crops of a single piece: the mask is the
alpha channel and the RGB is the piece colour.  Comparing masks makes the
classifier independent of the square colour, while the masked mean luminance
separates white pieces from black pieces of the same silhouette.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence

import chess
import cv2
import numpy as np
from PIL import Image

TEMPLATE_SIZE = 64
# Lichess draws the file/rank coordinates inside the edge squares.  When a
# piece leaves such a square the glyphs remain, and a low threshold turns that
# residue into a phantom piece (the a8 "white bishop" stall).  6% is safely
# above that residue and well below any real piece (a pawn is >10%).
EMPTY_AREA_FRACTION = 0.06
DEFAULT_DIFF_THRESHOLD = 18.0


@dataclass(frozen=True)
class CellSignature:
    mask: np.ndarray       # (T, T) float32, 0..1
    rgb: np.ndarray        # (T, T, 3) float32, 0..1
    mean_luma: float       # 0..255, weighted by mask
    area_fraction: float   # mask area / cropped cell area


@dataclass(frozen=True)
class PieceSample:
    piece: chess.Piece
    signature: CellSignature


def _estimate_background(cell_bgr: np.ndarray) -> np.ndarray:
    h, w = cell_bgr.shape[:2]
    m = max(2, int(round(min(h, w) * 0.08)))
    ring = np.concatenate(
        [
            cell_bgr[:m, :, :].reshape(-1, 3),
            cell_bgr[-m:, :, :].reshape(-1, 3),
            cell_bgr[:, :m, :].reshape(-1, 3),
            cell_bgr[:, -m:, :].reshape(-1, 3),
        ],
        axis=0,
    )
    return np.median(ring, axis=0).astype(np.float32)


def _luma(rgb: np.ndarray, mask: np.ndarray) -> float:
    # Minimum channel is deliberately used instead of weighted luminance:
    # it is not fooled by red/yellow/green overlays (check, last move) that
    # tint one channel while the piece itself stays white or black.
    values = np.min(rgb, axis=2)
    total = float(mask.sum())
    if total <= 1e-6:
        return 0.0
    return float((values * mask).sum() / total) * 255.0


def _suppress_red(cell_bgr: np.ndarray) -> np.ndarray:
    """Neutralise red-dominant overlays such as Lichess's check glow.

    Brown board squares are also slightly red-dominant; they are turned into a
    neutral equivalent, which is harmless because piece masks are relative to
    the per-cell background and pieces themselves are white/black.
    """
    blue, green, red = cv2.split(cell_bgr)
    neutral = np.maximum(green, blue)
    excess = red.astype(np.int16) - neutral.astype(np.int16)
    red = np.where(excess > 30, neutral, red).astype(np.uint8)
    return cv2.merge([blue, green, red])


def signature_from_cell(
    cell_bgr: np.ndarray,
    *,
    crop_pct: float = 6.0,
    diff_threshold: float = DEFAULT_DIFF_THRESHOLD,
    size: int = TEMPLATE_SIZE,
) -> Optional[CellSignature]:
    """Extract a background-independent piece signature, or None if empty."""
    h, w = cell_bgr.shape[:2]
    if h < 8 or w < 8:
        return None
    c = int(round(min(h, w) * crop_pct / 100.0))
    if c * 2 >= min(h, w) - 4:
        c = 0
    cell = cell_bgr[c : h - c, c : w - c] if c else cell_bgr
    cell = _suppress_red(cell)

    bg = _estimate_background(cell)
    diff = np.sqrt(np.sum((cell.astype(np.float32) - bg) ** 2, axis=2))
    mask_u8 = (diff > diff_threshold).astype(np.uint8) * 255
    mask_u8 = cv2.medianBlur(mask_u8, 3)
    mask = mask_u8 > 0

    area_fraction = float(mask.mean())
    if area_fraction < EMPTY_AREA_FRACTION:
        return None

    ys, xs = np.nonzero(mask)
    if xs.size < 8:
        return None
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    pad = max(1, int(round(0.04 * max(x1 - x0, y1 - y0))))
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(cell.shape[1], x1 + pad)
    y1 = min(cell.shape[0], y1 + pad)

    img = cell[y0:y1, x0:x1]
    m = mask[y0:y1, x0:x1]
    img = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
    m = cv2.resize(m.astype(np.float32), (size, size), interpolation=cv2.INTER_AREA)
    m = np.clip(m, 0.0, 1.0)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    return CellSignature(
        mask=m.astype(np.float32),
        rgb=rgb.astype(np.float32),
        mean_luma=_luma(rgb, m),
        area_fraction=area_fraction,
    )


def signature_from_rgba(rgba: np.ndarray, *, size: int = TEMPLATE_SIZE) -> Optional[CellSignature]:
    """Build a signature from a rendered transparent piece image."""
    rgba = np.asarray(rgba)
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("expected an RGBA image")
    alpha = rgba[..., 3].astype(np.float32) / 255.0
    ys, xs = np.nonzero(alpha > 0.15)
    if xs.size < 8:
        return None
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    pad = max(1, int(round(0.03 * max(x1 - x0, y1 - y0))))
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(rgba.shape[1], x1 + pad)
    y1 = min(rgba.shape[0], y1 + pad)

    rgb = rgba[y0:y1, x0:x1, :3].astype(np.float32) / 255.0
    m = alpha[y0:y1, x0:x1]
    rgb = cv2.resize(rgb, (size, size), interpolation=cv2.INTER_AREA)
    m = np.clip(cv2.resize(m, (size, size), interpolation=cv2.INTER_AREA), 0.0, 1.0)
    return CellSignature(
        mask=m.astype(np.float32),
        rgb=rgb.astype(np.float32),
        mean_luma=_luma(rgb, m),
        area_fraction=float((alpha > 0.15).mean()),
    )


class TemplateLibrary:
    """A set of labelled piece templates with a vectorised matcher."""

    def __init__(self, samples: Sequence[PieceSample], *, max_per_piece: int = 3):
        if not samples:
            raise ValueError("template library needs at least one sample")
        grouped: dict[str, list[PieceSample]] = {}
        for sample in samples:
            grouped.setdefault(sample.piece.symbol(), []).append(sample)
        chosen: list[PieceSample] = []
        for group in grouped.values():
            group = sorted(group, key=lambda s: -s.signature.area_fraction)
            chosen.extend(group[:max_per_piece])
        self.samples = chosen
        self._pieces = [s.piece for s in chosen]
        self._masks = np.stack([s.signature.mask for s in chosen]).astype(np.float32)
        self._lumas = np.array([s.signature.mean_luma for s in chosen], np.float32)
        self._areas = self._masks.sum(axis=(1, 2)).astype(np.float32)

    def classify_many(
        self, signatures: Sequence[Optional[CellSignature]]
    ) -> list[tuple[Optional[chess.Piece], float]]:
        results: list[tuple[Optional[chess.Piece], float]] = [(None, 0.0)] * len(signatures)
        indexes = [i for i, sig in enumerate(signatures) if sig is not None]
        if not indexes:
            return results

        masks = np.stack([signatures[i].mask for i in indexes]).astype(np.float32)
        lumas = np.array([signatures[i].mean_luma for i in indexes], np.float32)

        inter = np.tensordot(masks, self._masks, axes=([1, 2], [1, 2]))
        areas = masks.sum(axis=(1, 2)).astype(np.float32)
        union = areas[:, None] + self._areas[None, :] - inter
        shape = np.divide(inter, union, out=np.zeros_like(inter), where=union > 1e-6)
        luma_score = np.clip(1.0 - np.abs(lumas[:, None] - self._lumas[None, :]) / 120.0, 0.0, 1.0)
        scores = 0.70 * shape + 0.30 * luma_score

        best = scores.argmax(axis=1)
        for row, index in enumerate(indexes):
            piece = self._pieces[int(best[row])]
            results[index] = (piece, float(scores[row, int(best[row])]))
        return results

    def classify_one(self, signature: CellSignature) -> tuple[Optional[chess.Piece], float]:
        return self.classify_many([signature])[0]


def select_for_piece(
    samples: Iterable[PieceSample],
) -> dict[chess.Piece, list[PieceSample]]:
    grouped: dict[chess.Piece, list[PieceSample]] = {}
    for sample in samples:
        grouped.setdefault(sample.piece, []).append(sample)
    return grouped


def save_library(
    directory: str | Path,
    samples: Sequence[PieceSample],
    *,
    source: str,
    threshold: float = 0.60,
) -> None:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    entries = []
    for index, sample in enumerate(samples):
        symbol = sample.piece.symbol()
        filename = f"{symbol}_{index:03d}.png"
        rgb = np.clip(sample.signature.rgb * 255.0, 0, 255).astype(np.uint8)
        alpha = np.clip(sample.signature.mask * 255.0, 0, 255).astype(np.uint8)
        rgba = np.dstack([rgb, alpha])
        Image.fromarray(rgba, mode="RGBA").save(directory / filename)
        entries.append({"piece": symbol, "file": filename})
    meta = {
        "version": 1,
        "source": source,
        "created": datetime.now(timezone.utc).isoformat(),
        "threshold": threshold,
        "samples": entries,
    }
    (directory / "library.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def load_library(directory: str | Path) -> Optional[TemplateLibrary]:
    directory = Path(directory)
    meta_path = directory / "library.json"
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        samples: list[PieceSample] = []
        for entry in meta.get("samples", []):
            path = directory / entry["file"]
            if not path.is_file():
                continue
            rgba = np.asarray(Image.open(path).convert("RGBA"))
            signature = signature_from_rgba(rgba)
            if signature is None:
                continue
            samples.append(PieceSample(chess.Piece.from_symbol(entry["piece"]), signature))
        if not samples:
            return None
        return TemplateLibrary(samples)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None


BACK_RANK_TYPES = (
    chess.ROOK,
    chess.KNIGHT,
    chess.BISHOP,
    chess.QUEEN,
    chess.KING,
    chess.BISHOP,
    chess.KNIGHT,
    chess.ROOK,
)


def looks_like_start(occupied: Sequence[Sequence[bool]]) -> bool:
    return (
        all(occupied[r][c] for r in (0, 1, 6, 7) for c in range(8))
        and not any(occupied[r][c] for r in (2, 3, 4, 5) for c in range(8))
    )


def build_start_library(
    signatures: Sequence[Sequence[Optional[CellSignature]]],
    *,
    threshold: float = 0.60,
    bottom_color: Optional[chess.Color] = None,
) -> Optional[tuple[TemplateLibrary, chess.Color]]:
    """Capture exact templates from a board showing the standard start position.

    Returns (library, colour_at_the_bottom) or None when the position is not the
    start, the square colours are ambiguous, or the verification read fails.
    """
    occupied = [[signatures[r][c] is not None for c in range(8)] for r in range(8)]
    if not looks_like_start(occupied):
        return None

    if bottom_color is None:
        bottom_luma = float(
            np.mean(
                [signatures[r][c].mean_luma for r in (6, 7) for c in range(8) if signatures[r][c]]
            )
        )
        top_luma = float(
            np.mean(
                [signatures[r][c].mean_luma for r in (0, 1) for c in range(8) if signatures[r][c]]
            )
        )
        if abs(bottom_luma - top_luma) < 25.0:
            return None
        bottom_color = chess.WHITE if bottom_luma > top_luma else chess.BLACK
    top_color = not bottom_color

    samples: list[PieceSample] = []
    expected: list[Optional[chess.Piece]] = []
    for r in range(8):
        for c in range(8):
            expected.append(None)

    def add(row: int, col: int, piece: chess.Piece) -> None:
        sig = signatures[row][col]
        if sig is None:
            return
        samples.append(PieceSample(piece, sig))
        expected[row * 8 + col] = piece

    for col in range(8):
        # On a flipped (black-bottom) board the visual columns run h..a, so the
        # standard back-rank order is mirrored.  Without this the black king and
        # queen templates are swapped.
        piece_type = BACK_RANK_TYPES[col if bottom_color == chess.WHITE else 7 - col]
        add(7, col, chess.Piece(piece_type, bottom_color))
        add(0, col, chess.Piece(piece_type, top_color))
    for col in range(8):
        add(6, col, chess.Piece(chess.PAWN, bottom_color))
        add(1, col, chess.Piece(chess.PAWN, top_color))

    try:
        library = TemplateLibrary(samples)
    except ValueError:
        return None

    flat = [signatures[r][c] for r in range(8) for c in range(8)]
    results = library.classify_many(flat)
    for (piece, score), want in zip(results, expected):
        if want is None:
            if piece is not None and score >= threshold:
                return None
            continue
        if piece != want or score < threshold:
            return None
    return library, bottom_color
