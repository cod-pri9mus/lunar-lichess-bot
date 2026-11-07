"""Locate the chess board on screen and build a perspective mapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import cv2
import numpy as np


@dataclass(frozen=True)
class BoardGeometry:
    quad: np.ndarray            # 4x2 in frame coordinates (tl, tr, br, bl)
    size: int                   # warped board side in pixels
    matrix: np.ndarray          # frame -> warp
    inverse: np.ndarray         # warp -> frame
    unit: np.ndarray            # normalised board [0,1]^2 -> frame
    origin: tuple[int, int]     # absolute screen coordinate of the frame's (0, 0)

    def warp(self, frame_bgr: np.ndarray) -> np.ndarray:
        return cv2.warpPerspective(
            frame_bgr, self.matrix, (self.size, self.size), flags=cv2.INTER_LINEAR
        )

    def cell_to_frame(self, col: int, row: int) -> tuple[float, float]:
        point = np.array([[[(col + 0.5) / 8.0, (row + 0.5) / 8.0]]], dtype=np.float32)
        mapped = cv2.perspectiveTransform(point, self.unit)[0, 0]
        return float(mapped[0]), float(mapped[1])

    def cell_to_screen(self, col: int, row: int) -> tuple[int, int]:
        x, y = self.cell_to_frame(col, row)
        return int(round(self.origin[0] + x)), int(round(self.origin[1] + y))

    def frame_point_to_screen(self, x: float, y: float) -> tuple[int, int]:
        return int(round(self.origin[0] + x)), int(round(self.origin[1] + y))

    def cell_size_screen(self) -> float:
        top = np.linalg.norm(self.quad[1] - self.quad[0])
        bottom = np.linalg.norm(self.quad[2] - self.quad[3])
        return float((top + bottom) / 2.0 / 8.0)

    def board_size_screen(self) -> tuple[float, float]:
        return (
            float(max(np.linalg.norm(self.quad[1] - self.quad[0]), np.linalg.norm(self.quad[2] - self.quad[3]))),
            float(max(np.linalg.norm(self.quad[3] - self.quad[0]), np.linalg.norm(self.quad[2] - self.quad[1]))),
        )


def order_quad(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    sums = points.sum(axis=1)
    diffs = np.diff(points, axis=1).ravel()
    top_left = points[np.argmin(sums)]
    bottom_right = points[np.argmax(sums)]
    top_right = points[np.argmin(diffs)]
    bottom_left = points[np.argmax(diffs)]
    return np.array([top_left, top_right, bottom_right, bottom_left], dtype=np.float32)


def make_geometry(
    quad: np.ndarray,
    origin: tuple[int, int],
    *,
    size: int = 800,
    inset_pct: float = 0.0,
) -> BoardGeometry:
    quad = order_quad(quad)
    if inset_pct:
        center = quad.mean(axis=0)
        quad = center + (quad - center) * (1.0 - inset_pct / 100.0)
    destination = np.array(
        [[0, 0], [size - 1, 0], [size - 1, size - 1], [0, size - 1]], dtype=np.float32
    )
    matrix = cv2.getPerspectiveTransform(quad, destination)
    inverse = cv2.getPerspectiveTransform(destination, quad)
    unit = cv2.getPerspectiveTransform(
        np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32), quad
    )
    return BoardGeometry(
        quad=quad.astype(np.float32),
        size=size,
        matrix=matrix,
        inverse=inverse,
        unit=unit,
        origin=(int(origin[0]), int(origin[1])),
    )


def geometry_from_rect(
    rect: tuple[int, int, int, int],
    origin: tuple[int, int],
    *,
    relative: bool = True,
    size: int = 800,
    inset_pct: float = 0.0,
) -> BoardGeometry:
    x, y, w, h = rect
    if relative:
        quad = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
    else:
        quad = np.array(
            [[x, y], [x + w - 1, y], [x + w - 1, y + h - 1], [x, y + h - 1]],
            dtype=np.float32,
        )
    return make_geometry(quad, origin, size=size, inset_pct=inset_pct)


def _checkerboard_score(frame_bgr: np.ndarray, quad: np.ndarray) -> float:
    size = 320
    destination = np.array(
        [[0, 0], [size - 1, 0], [size - 1, size - 1], [0, size - 1]], dtype=np.float32
    )
    matrix = cv2.getPerspectiveTransform(order_quad(quad), destination)
    warp = cv2.warpPerspective(frame_bgr, matrix, (size, size))
    step = size // 8
    colors = np.zeros((8, 8, 3), dtype=np.float32)
    variation = np.zeros((8, 8), dtype=np.float32)

    for row in range(8):
        for col in range(8):
            cell = warp[row * step : (row + 1) * step, col * step : (col + 1) * step]
            margin = max(2, step // 6)
            ring = np.concatenate(
                [
                    cell[:margin, :, :].reshape(-1, 3),
                    cell[-margin:, :, :].reshape(-1, 3),
                    cell[:, :margin, :].reshape(-1, 3),
                    cell[:, -margin:, :].reshape(-1, 3),
                ],
                axis=0,
            ).astype(np.float32)
            colors[row, col] = np.median(ring, axis=0)
            variation[row, col] = float(np.median(np.abs(ring - colors[row, col]).sum(axis=1)))

    opposite: list[float] = []
    same: list[float] = []
    for row in range(8):
        for col in range(8):
            if row + 1 < 8:
                opposite.append(float(np.linalg.norm(colors[row, col] - colors[row + 1, col])))
            if col + 1 < 8:
                opposite.append(float(np.linalg.norm(colors[row, col] - colors[row, col + 1])))
            if row + 2 < 8:
                same.append(float(np.linalg.norm(colors[row, col] - colors[row + 2, col])))
            if col + 2 < 8:
                same.append(float(np.linalg.norm(colors[row, col] - colors[row, col + 2])))
    if not opposite:
        return 0.0
    contrast = float(np.mean(opposite))
    purity = float(np.mean(same)) if same else 0.0
    if contrast < 18.0:
        return 0.0
    score = contrast / (purity + 10.0)
    if float(np.mean(variation)) > 28.0:
        score *= 0.5
    return score


def _quad_area(quad: np.ndarray) -> float:
    return float(cv2.contourArea(quad.reshape(-1, 1, 2)))


def _is_excluded(points: np.ndarray, rects: Sequence[tuple[int, int, int, int]]) -> bool:
    if not rects:
        return False
    center_x, center_y = (float(value) for value in points.mean(axis=0))
    for x, y, width, height in rects:
        if x <= center_x <= x + width and y <= center_y <= y + height:
            return True
    return False


def _similar(a: np.ndarray, b: np.ndarray) -> bool:
    ca, cb = a.mean(axis=0), b.mean(axis=0)
    aa, ab = _quad_area(a), _quad_area(b)
    if aa <= 0 or ab <= 0:
        return False
    return float(np.linalg.norm(ca - cb)) < 0.03 * max(aa, ab) ** 0.5 and abs(aa - ab) / max(aa, ab) < 0.12


def _saturation_quads(
    frame_bgr: np.ndarray,
    *,
    min_area_frac: float,
    min_side: float,
) -> list[np.ndarray]:
    """Fallback candidates: the board is usually the largest saturated square."""
    height, width = frame_bgr.shape[:2]
    scale = 0.5 if max(height, width) > 800 else 1.0
    small = cv2.resize(frame_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale != 1.0 else frame_bgr
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    mask = (hsv[..., 1] > 30).astype(np.uint8) * 255
    kernel = max(3, int(round(min(small.shape[:2]) * 0.012)) | 1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((kernel, kernel), np.uint8))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    quads: list[np.ndarray] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w * h < min_area_frac * small.shape[0] * small.shape[1]:
            continue
        aspect = w / max(1, h)
        if not 0.80 <= aspect <= 1.25:
            continue
        if min(w, h) / scale < min_side:
            continue
        x, y, w, h = (value / scale for value in (x, y, w, h))
        quads.append(
            np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=np.float32)
        )
    return quads


def find_board(
    frame_bgr: np.ndarray,
    *,
    min_area_frac: float = 0.03,
    exclude_rects: Sequence[tuple[int, int, int, int]] = (),
) -> Optional[tuple[np.ndarray, float]]:
    """Return (quad, checkerboard score) for the most board-like region."""
    height, width = frame_bgr.shape[:2]
    scale = 0.5 if max(height, width) > 1000 else 1.0
    if scale != 1.0:
        small = cv2.resize(frame_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    else:
        small = frame_bgr
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 40, 120)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    min_area = min_area_frac * small.shape[0] * small.shape[1]
    candidates: list[np.ndarray] = []
    for contour in contours:
        if cv2.contourArea(contour) < min_area:
            continue
        perimeter = cv2.arcLength(contour, True)
        if perimeter <= 0:
            continue
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approx) == 4:
            points = approx.reshape(4, 2).astype(np.float32)
        else:
            rect = cv2.minAreaRect(contour)
            (_, _), (rw, rh), _ = rect
            if rw < 10 or rh < 10:
                continue
            points = cv2.boxPoints(rect).astype(np.float32)
        points = order_quad(points / scale)
        sides = [
            float(np.linalg.norm(points[1] - points[0])),
            float(np.linalg.norm(points[2] - points[1])),
            float(np.linalg.norm(points[3] - points[2])),
            float(np.linalg.norm(points[0] - points[3])),
        ]
        if min(sides) < 150:
            continue
        aspect = (sides[0] + sides[2]) / max(1e-6, sides[1] + sides[3])
        if not 0.80 <= aspect <= 1.25:
            continue
        if _quad_area(points) > 0.995 * height * width:
            continue
        if any(_similar(points, existing) for existing in candidates):
            continue
        candidates.append(points)

    for points in _saturation_quads(
        frame_bgr, min_area_frac=min_area_frac, min_side=150.0
    ):
        if _quad_area(points) > 0.995 * height * width:
            continue
        candidates.append(points)

    best: Optional[tuple[float, np.ndarray, float]] = None
    for points in candidates:
        if _is_excluded(points, exclude_rects):
            continue
        score = _checkerboard_score(frame_bgr, points)
        if score < 1.5:
            continue
        weight = score * _quad_area(points)
        if best is None or weight > best[0]:
            best = (weight, points, score)
    if best is None:
        return None
    return best[1], best[2]
