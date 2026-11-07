"""Calibration and board-read diagnostics."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import chess
import cv2
import numpy as np

from .board_detect import (
    BoardGeometry,
    find_board,
    geometry_from_rect,
    make_geometry,
)
from .capture import CaptureError, Frame, ScreenCapture
from .coords import visual_to_square
from .imgio import imread, imwrite
from .pieces import build_start_library, load_library, save_library
from .vision import BoardReader, VisualReading, infer_orientation_from_visual

log = logging.getLogger(__name__)


def _resolve_dir(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def _capture_frame(config, image: Optional[str] = None) -> Optional[Frame]:
    if image:
        array = imread(image)
        if array is None:
            log.error("cannot read image: %s", image)
            return None
        return Frame(image=array, origin=(0, 0))
    capture = ScreenCapture(config.vision.monitor, config.vision.board_rect)
    try:
        return capture.grab()
    except CaptureError as exc:
        log.error("%s", exc)
        return None
    finally:
        capture.close()


def _geometry(config, frame: Frame, *, image_mode: bool = False) -> Optional[BoardGeometry]:
    if config.vision.board_rect is not None:
        return geometry_from_rect(
            config.vision.board_rect,
            frame.origin,
            relative=not image_mode,
            inset_pct=config.vision.board_inset_pct,
        )
    found = find_board(frame.image)
    if found is None:
        if image_mode:
            height, width = frame.image.shape[:2]
            if 0.90 <= width / max(1, height) <= 1.10 and min(width, height) >= 300:
                log.info("using the whole square image as the board")
                return geometry_from_rect(
                    (0, 0, width, height),
                    frame.origin,
                    inset_pct=config.vision.board_inset_pct,
                )
        return None
    quad, score = found
    log.info("board detected (checkerboard score %.2f, quad %s)", score, quad.astype(int).tolist())
    return make_geometry(quad, frame.origin, inset_pct=config.vision.board_inset_pct)


def _library(config):
    templates_dir = _resolve_dir(config.base_dir, config.vision.templates_dir)
    bundled = Path(__file__).resolve().parent / "assets" / "cburnett"
    return load_library(templates_dir) or load_library(bundled), templates_dir


def _explicit_orientation(config) -> Optional[chess.Color]:
    value = config.vision.orientation
    if value != "auto":
        return {"white": chess.WHITE, "black": chess.BLACK}[value]
    value = config.vision.color
    if value != "auto":
        return {"white": chess.WHITE, "black": chess.BLACK}[value]
    return None


def _orientation(config, visual: VisualReading, bottom: Optional[chess.Color]) -> Optional[chess.Color]:
    explicit = _explicit_orientation(config)
    if explicit is not None:
        return explicit
    if bottom is not None:
        return bottom
    return infer_orientation_from_visual(visual)


def _print_reading(
    reader: BoardReader,
    visual: VisualReading,
    orientation: chess.Color,
    threshold: float,
) -> bool:
    reading = reader.board_reading(visual, orientation)
    print()
    print(f"orientation (bottom colour): {'white' if orientation == chess.WHITE else 'black'}")
    print(f"confidence: {visual.confidence:.3f}   occupied: {visual.occupied}   unknown: {visual.unknown}")
    print(f"valid: {reading.valid}")
    print()
    if reading.valid:
        board = chess.Board(reading.placement + " w - - 0 1")
        print(board)
    else:
        print("placement:", reading.placement)

    print()
    print("per-square confidence (row 0 = top):")
    for row in range(8):
        cells = []
        for col in range(8):
            piece = visual.cells[row][col]
            score = visual.scores[row][col]
            symbol = piece.symbol() if piece is not None else "."
            cells.append(f"{symbol}:{score:.2f}")
        print("  ".join(cells))

    low = []
    for row in range(8):
        for col in range(8):
            piece = visual.cells[row][col]
            if piece is not None and visual.scores[row][col] < threshold:
                square = chess.square_name(visual_to_square(row, col, orientation))
                low.append((square, piece.symbol(), visual.scores[row][col]))
    if low:
        print()
        print("low-confidence squares:")
        for square, symbol, score in low:
            print(f"  {square}: {symbol} {score:.3f}")
    return reading.valid


def check_vision(config, image: Optional[str] = None) -> int:
    frame = _capture_frame(config, image)
    if frame is None:
        return 2
    geometry = _geometry(config, frame, image_mode=bool(image))
    if geometry is None:
        log.error("board not found; set vision.board_rect or pass --rect x,y,w,h")
        return 2

    library, _templates_dir = _library(config)
    reader = BoardReader(
        library,
        crop_pct=config.vision.cell_crop_pct,
        confidence_threshold=config.vision.confidence_threshold,
    )
    visual = reader.visual(frame, geometry)

    bottom = None
    if visual.start_pattern:
        built = build_start_library(
            visual.signatures,
            threshold=config.vision.confidence_threshold,
            bottom_color=_explicit_orientation(config),
        )
        if built is not None:
            auto_library, bottom = built
            reader.library = auto_library
            visual = reader.visual(frame, geometry)
            print(
                "auto-calibrated templates from the starting position "
                f"(bottom colour: {'white' if bottom == chess.WHITE else 'black'})"
            )

    orientation = _orientation(config, visual, bottom)
    if orientation is None:
        log.error("cannot determine orientation; pass --color or --orientation")
        return 2

    ok = _print_reading(
        reader, visual, orientation, config.vision.confidence_threshold
    )

    debug_dir = _resolve_dir(config.base_dir, config.vision.debug_dir)
    debug_dir.mkdir(parents=True, exist_ok=True)
    path = debug_dir / f"vision_check_{time.strftime('%Y%m%d_%H%M%S')}.png"
    image = annotate_frame(
        frame, geometry, visual, orientation, config.vision.confidence_threshold
    )
    imwrite(path, image)
    print()
    print(f"annotated frame: {path}")
    return 0 if ok else 1


def calibrate(config, image: Optional[str] = None) -> int:
    frame = _capture_frame(config, image)
    if frame is None:
        return 2
    geometry = _geometry(config, frame, image_mode=bool(image))
    if geometry is None:
        log.error("board not found; set vision.board_rect or pass --rect x,y,w,h")
        return 2

    templates_dir = _resolve_dir(config.base_dir, config.vision.templates_dir)
    reader = BoardReader(
        None,
        crop_pct=config.vision.cell_crop_pct,
        confidence_threshold=config.vision.confidence_threshold,
    )
    visual = reader.visual(frame, geometry)
    built = build_start_library(
        visual.signatures,
        threshold=config.vision.confidence_threshold,
        bottom_color=_explicit_orientation(config),
    )
    if built is None:
        log.error(
            "calibration needs the standard starting position, a visible board and "
            "readable piece colours; set the board to the start and try again"
        )
        return 2

    library, bottom = built
    save_library(
        templates_dir,
        library.samples,
        source="calibration at start position",
        threshold=config.vision.confidence_threshold,
    )
    print(
        f"saved {len(library.samples)} templates to {templates_dir} "
        f"(bottom colour: {'white' if bottom == chess.WHITE else 'black'})"
    )
    print("our colour will be the bottom colour unless vision.color is set")

    reader.library = library
    visual = reader.visual(frame, geometry)
    _print_reading(reader, visual, bottom, config.vision.confidence_threshold)

    debug_dir = _resolve_dir(config.base_dir, config.vision.debug_dir)
    debug_dir.mkdir(parents=True, exist_ok=True)
    path = debug_dir / f"calibration_{time.strftime('%Y%m%d_%H%M%S')}.png"
    image = annotate_frame(
        frame, geometry, visual, bottom, config.vision.confidence_threshold
    )
    imwrite(path, image)
    print(f"annotated frame: {path}")
    return 0


def annotate_frame(
    frame: Frame,
    geometry: BoardGeometry,
    visual: VisualReading,
    orientation: Optional[chess.Color],
    threshold: float,
) -> np.ndarray:
    image = frame.image.copy()
    quad = geometry.quad.astype(np.int32)
    cv2.polylines(image, [quad], True, (0, 255, 0), 2)

    edge = float(geometry.size - 1)
    for index in range(9):
        position = index * geometry.size / 8.0
        vertical = np.array([[[position, 0.0]], [[position, edge]]], dtype=np.float32)
        horizontal = np.array([[[0.0, position]], [[edge, position]]], dtype=np.float32)
        for line in (vertical, horizontal):
            mapped = cv2.perspectiveTransform(line, geometry.inverse).reshape(-1, 2)
            start = tuple(np.round(mapped[0]).astype(int))
            end = tuple(np.round(mapped[1]).astype(int))
            cv2.line(image, start, end, (80, 180, 80), 1)

    for row in range(8):
        for col in range(8):
            x, y = geometry.cell_to_frame(col, row)
            piece = visual.cells[row][col]
            score = visual.scores[row][col]
            label = piece.symbol() if piece is not None else "."
            color = (0, 255, 0) if (piece is not None and score >= threshold) else (0, 0, 255)
            cv2.putText(
                image,
                f"{label}{score:.2f}" if piece is not None else ".",
                (int(x) - 14, int(y) + 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.35,
                color,
                1,
                cv2.LINE_AA,
            )
    return image
