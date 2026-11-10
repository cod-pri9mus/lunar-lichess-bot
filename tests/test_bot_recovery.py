from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import chess
import numpy as np
import pytest

from lichess_vision_bot.bot import VisionBot, _advantage_text, _win_probability
from lichess_vision_bot.config import load_config
from lichess_vision_bot.imgio import imwrite
from lichess_vision_bot.tracker import GameTracker
from lichess_vision_bot.vision import BoardReading
from synthetic import render_board


def _config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"vision": {"source": "screen"}}', encoding="utf-8")
    return path


@pytest.fixture()
def bot(tmp_path):
    image = tmp_path / "board.png"
    imwrite(image, np.full((480, 480, 3), 200, dtype=np.uint8))
    instance = VisionBot(
        load_config(_config(tmp_path)),
        image=str(image),
        web=False,
        use_hotkeys=False,
        open_browser=False,
    )
    instance._our_color = chess.BLACK
    try:
        yield instance
    finally:
        instance.close()


def test_stall_is_temporary(bot):
    bot._stall("test stall")
    assert bot._stalled is True
    assert bot._finished is False
    assert bot._recover_at > 0.0

    bot._recover()
    assert bot._stalled is False
    assert bot._recover_at == 0.0
    assert bot._resync_requested is True
    assert bot._geometry is None


def test_resync_resets_when_the_observed_board_is_unreachable(bot):
    bot._tracker = GameTracker(chess.Board(), chess.BLACK)
    board = chess.Board("4k3/8/8/8/8/8/8/4K3 b - - 0 1")
    reading = BoardReading(board.board_fen(), board, True, 0, 1.0)

    bot._resync(reading)

    assert bot._tracker is not None
    assert bot._tracker.board.board_fen() == board.board_fen()
    assert bot._tracker.board.turn == chess.BLACK
    assert bot._stalled is False


def test_start_tracker_clears_the_finished_state(bot):
    bot._stalled = True
    bot._finished = True
    bot._recover_at = 123.0

    bot._start_tracker(SimpleNamespace(key="x"), chess.WHITE)

    assert bot._stalled is False
    assert bot._finished is False
    assert bot._recover_at == 0.0
    assert bot._tracker is not None


def test_dom_start_adopts_the_board(bot):
    payload = {
        "fen": "4k3/8/8/8/8/8/8/4K3 b - - 0 1",
        "turn": "black",
        "orientation": "black",
        "color": "black",
        "rect": {"x": 0, "y": 0, "width": 640, "height": 640},
    }

    bot._handle_dom(payload)

    assert bot._tracker is not None
    assert bot._tracker.board.board_fen() == "4k3/8/8/8/8/8/8/4K3"
    assert bot._our_color == chess.BLACK
    assert bot._geometry is not None


def test_set_elo_command_updates_engine_and_config(bot):
    bot._engine = MagicMock()

    bot._handle_command("set-elo:2000")

    bot._engine.set_elo.assert_called_once_with(2000)
    assert bot.config.engine.uci_elo == 2000
    assert bot._web_state.snapshot()["config"]["uci_elo"] == 2000


def test_set_move_time_command_updates_engine_and_config(bot):
    bot._engine = MagicMock()

    bot._handle_command("set-move-time:0.3")

    bot._engine.set_move_time.assert_called_once_with(0.3)
    assert bot.config.engine.move_time_s == 0.3
    assert bot._web_state.snapshot()["config"]["move_time_s"] == 0.3


def test_win_probability_and_advantage():
    assert _advantage_text(SimpleNamespace(mate_in=None, score_cp=102)) == "+1.02"
    assert _advantage_text(SimpleNamespace(mate_in=3, score_cp=None)) == "мат 3"
    assert _win_probability(SimpleNamespace(mate_in=None, score_cp=0)) == 50.0
    assert _win_probability(SimpleNamespace(mate_in=3, score_cp=None)) == 100.0
    assert _win_probability(SimpleNamespace(mate_in=-2, score_cp=None)) == 0.0


def test_start_from_current_reads_the_board_and_the_clock(tmp_path):
    board = chess.Board("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 2")
    rendered = render_board(board, orientation=chess.BLACK)
    side = rendered.shape[0]
    page = np.full((side + 240, side + 80, 3), 30, dtype=np.uint8)
    page[120 : 120 + side, 40 : 40 + side] = rendered
    page[20:100, 40 : 40 + side] = 220          # top clock bright: White to move
    page[140 + side : 220 + side, 40 : 40 + side] = 60
    image = tmp_path / "current.png"
    imwrite(image, page)

    instance = VisionBot(
        load_config(_config(tmp_path)),
        image=str(image),
        web=False,
        use_hotkeys=False,
        open_browser=False,
    )
    try:
        instance._start_from_current("black", False, my_turn=False)
        assert instance._tracker is not None
        assert instance._our_color == chess.BLACK
        assert instance._tracker.board.turn == chess.WHITE
        assert instance._tracker.board.board_fen() == board.board_fen()
    finally:
        instance.close()


def test_start_from_current_uses_the_selected_colour_and_turn(tmp_path):
    board = chess.Board("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 2")
    rendered = render_board(board, orientation=chess.BLACK)
    side = rendered.shape[0]
    page = np.full((side + 240, side + 80, 3), 30, dtype=np.uint8)
    page[120 : 120 + side, 40 : 40 + side] = rendered
    page[20:100, 40 : 40 + side] = 220
    page[140 + side : 220 + side, 40 : 40 + side] = 60
    image = tmp_path / "current.png"
    imwrite(image, page)

    instance = VisionBot(
        load_config(_config(tmp_path)),
        image=str(image),
        web=False,
        use_hotkeys=False,
        open_browser=False,
    )
    try:
        instance._start_from_current("black", False, my_turn=True)
        assert instance._tracker is not None
        assert instance._our_color == chess.BLACK
        assert instance._orientation == chess.BLACK
        assert instance._tracker.board.turn == chess.BLACK
        assert instance._tracker.board.board_fen() == board.board_fen()
    finally:
        instance.close()


def test_templates_from_before_boot_are_ignored(tmp_path):
    folder = tmp_path / "templates"
    folder.mkdir()
    (folder / "library.json").write_text(
        json.dumps({"created": "2020-01-01T00:00:00+00:00", "samples": []}),
        encoding="utf-8",
    )
    image = tmp_path / "board.png"
    imwrite(image, np.full((480, 480, 3), 200, dtype=np.uint8))
    instance = VisionBot(
        load_config(_config(tmp_path)),
        image=str(image),
        web=False,
        use_hotkeys=False,
        open_browser=False,
    )
    try:
        assert instance._templates_are_stale() is True
    finally:
        instance.close()
