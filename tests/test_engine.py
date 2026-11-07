from __future__ import annotations

import chess

from lichess_vision_bot.config import EngineConfig
from lichess_vision_bot.engine import StockfishEngine


def test_set_elo_updates_the_uci_limit_and_plays():
    engine = StockfishEngine(
        EngineConfig(
            path="stockfish.exe",
            threads=1,
            hash_mb=16,
            move_time_s=0.2,
        )
    )
    try:
        engine.set_elo(1500)
        assert engine._config.uci_elo == 1500
        result = engine.play(chess.Board())
        assert result.move is not None
    finally:
        engine.close()
