"""Unicode-safe image I/O for Windows paths.

OpenCV's ``imread``/``imwrite`` use the ANSI code page on Windows and fail on
paths with non-ASCII characters (for example, a Cyrillic user name).  Reading/writing the encoded buffer
through numpy uses Python's Unicode path handling instead.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def imread(path: str | Path) -> np.ndarray | None:
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def imwrite(path: str | Path, image: np.ndarray) -> bool:
    path = Path(path)
    suffix = path.suffix or ".png"
    ok, buffer = cv2.imencode(suffix, image)
    if not ok:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer.tofile(str(path))
    return True
