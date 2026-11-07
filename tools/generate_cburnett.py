"""Render the Lichess cburnett piece set into classifier templates."""

from __future__ import annotations

import io
import sys
import urllib.request
from pathlib import Path

import chess
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import resvg_py  # noqa: E402

from lichess_vision_bot.pieces import PieceSample, save_library, signature_from_rgba  # noqa: E402

PIECES = "PNBQRKpnbqrk"
URL = "https://lichess1.org/assets/piece/cburnett/{name}.svg"


def main() -> int:
    out = ROOT / "lichess_vision_bot" / "assets" / "cburnett"
    samples: list[PieceSample] = []
    for symbol in PIECES:
        prefix = "w" if symbol.isupper() else "b"
        name = f"{prefix}{symbol.upper()}"
        with urllib.request.urlopen(URL.format(name=name), timeout=30) as response:
            svg = response.read().decode("utf-8")
        png = resvg_py.svg_to_bytes(svg_string=svg, width=256, height=256)
        rgba = np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))
        signature = signature_from_rgba(rgba)
        if signature is None:
            raise RuntimeError(f"empty render for {name}")
        samples.append(PieceSample(chess.Piece.from_symbol(symbol), signature))
    save_library(out, samples, source="lichess cburnett SVG", threshold=0.60)
    print(f"wrote {len(samples)} templates to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
