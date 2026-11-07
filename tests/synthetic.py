"""Synthetic board renderer used by the vision tests."""

from __future__ import annotations

import json
from pathlib import Path

import chess
import cv2
import numpy as np
from PIL import Image

from lichess_vision_bot.coords import square_to_visual

ASSETS = Path(__file__).resolve().parents[1] / "lichess_vision_bot" / "assets" / "cburnett"
_META = json.loads((ASSETS / "library.json").read_text(encoding="utf-8"))
_FILES = {entry["piece"]: entry["file"] for entry in _META["samples"]}

LIGHT_BGR = (181, 217, 240)   # #f0d9b5 RGB
DARK_BGR = (99, 136, 181)     # #b58863 RGB


def piece_image(piece: chess.Piece) -> np.ndarray:
    return np.asarray(Image.open(ASSETS / _FILES[piece.symbol()]).convert("RGBA"))


def render_board(
    placement,
    *,
    orientation: chess.Color = chess.WHITE,
    cell: int = 100,
    background: tuple[int, int, int] = (40, 40, 40),
    check_square: chess.Square | None = None,
) -> np.ndarray:
    board = chess.Board(placement) if isinstance(placement, str) else placement
    size = cell * 8
    image = np.full((size, size, 3), background, dtype=np.uint8)

    for row in range(8):
        for col in range(8):
            color = LIGHT_BGR if (row + col) % 2 == 0 else DARK_BGR
            image[row * cell : (row + 1) * cell, col * cell : (col + 1) * cell] = color

    for square, piece in board.piece_map().items():
        row, col = square_to_visual(square, orientation)
        rgba = piece_image(piece)
        target = int(round(cell * 0.86))
        resized = cv2.resize(rgba, (target, target), interpolation=cv2.INTER_AREA)
        alpha = resized[..., 3:4].astype(np.float32) / 255.0
        rgb = cv2.cvtColor(resized[..., :3], cv2.COLOR_RGB2BGR).astype(np.float32)
        x = col * cell + (cell - target) // 2
        y = row * cell + (cell - target) // 2
        roi = image[y : y + target, x : x + target].astype(np.float32)
        image[y : y + target, x : x + target] = np.clip(
            rgb * alpha + roi * (1.0 - alpha), 0, 255
        ).astype(np.uint8)

    if check_square is not None:
        row, col = square_to_visual(check_square, orientation)
        cx = col * cell + cell / 2.0
        cy = row * cell + cell / 2.0
        yy, xx = np.mgrid[0 : image.shape[0], 0 : image.shape[1]]
        distance = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / (cell * 0.8)
        alpha = np.clip(1.0 - distance, 0.0, 1.0) ** 1.7 * 0.6
        red = np.zeros_like(image, dtype=np.float32)
        red[..., 2] = 255.0
        image = np.clip(
            image.astype(np.float32) * (1.0 - alpha[..., None])
            + red * alpha[..., None],
            0,
            255,
        ).astype(np.uint8)
    return image


def board_in_page(board_image: np.ndarray, *, page_size=(1200, 900), offset=(300, 100)):
    width, height = page_size
    page = np.full((height, width, 3), (235, 235, 235), dtype=np.uint8)
    x, y = offset
    h, w = board_image.shape[:2]
    page[y : y + h, x : x + w] = board_image
    return page, (x, y, w, h)
