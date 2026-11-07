from __future__ import annotations

import numpy as np

from lichess_vision_bot.board_detect import make_geometry


def test_cell_centers_on_axis_aligned_board():
    geometry = make_geometry(
        np.array([[100, 200], [900, 200], [900, 1000], [100, 1000]], dtype=np.float32),
        (0, 0),
        size=800,
        inset_pct=0.0,
    )
    assert geometry.cell_to_screen(0, 0) == (150, 250)
    assert geometry.cell_to_screen(3, 4) == (450, 650)
    assert geometry.cell_to_screen(7, 7) == (850, 950)


def test_origin_is_added():
    geometry = make_geometry(
        np.array([[0, 0], [800, 0], [800, 800], [0, 800]], dtype=np.float32),
        (50, 60),
        size=800,
        inset_pct=0.0,
    )
    assert geometry.cell_to_screen(0, 0) == (100, 110)
    assert geometry.cell_to_screen(7, 7) == (800, 810)


def test_cell_size():
    geometry = make_geometry(
        np.array([[0, 0], [800, 0], [800, 800], [0, 800]], dtype=np.float32),
        (0, 0),
        size=800,
        inset_pct=0.0,
    )
    assert geometry.cell_size_screen() == 100.0
