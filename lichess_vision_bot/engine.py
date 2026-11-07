"""Stockfish UCI wrapper."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Optional

import chess
import chess.engine

from .config import EngineConfig

log = logging.getLogger(__name__)


class EngineStartError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchResult:
    move: Optional[chess.Move]
    score_cp: Optional[int] = None
    mate_in: Optional[int] = None


class StockfishEngine:
    def __init__(self, config: EngineConfig):
        if not config.path:
            raise EngineStartError(
                "Stockfish executable not found. Put stockfish.exe next to run.py, "
                "or set engine.path in config.json."
            )
        self._config = config
        self._engine = self._spawn()

    def _spawn(self) -> chess.engine.SimpleEngine:
        try:
            engine = chess.engine.SimpleEngine.popen_uci(self._config.path)
        except (OSError, chess.engine.EngineError) as exc:
            raise EngineStartError(f"cannot start Stockfish at {self._config.path}: {exc}") from exc

        options: dict[str, object] = {}
        supported = engine.options
        if "Threads" in supported:
            options["Threads"] = self._config.threads
        if "Hash" in supported:
            options["Hash"] = self._config.hash_mb
        if "Move Overhead" in supported:
            options["Move Overhead"] = self._config.move_overhead_ms
        if self._config.skill_level is not None and "Skill Level" in supported:
            options["Skill Level"] = self._config.skill_level
        if self._config.uci_elo is not None:
            if "UCI_LimitStrength" in supported:
                options["UCI_LimitStrength"] = True
            if "UCI_Elo" in supported:
                options["UCI_Elo"] = self._config.uci_elo
        try:
            if options:
                engine.configure(options)
        except chess.engine.EngineError as exc:
            log.warning("engine rejected some options: %s", exc)
        return engine

    @property
    def name(self) -> str:
        ident = self._engine.id or {}
        return str(ident.get("name", "Stockfish"))

    def restart(self) -> None:
        try:
            self._engine.quit()
        except Exception:
            pass
        self._engine = self._spawn()

    def set_elo(self, elo: int) -> None:
        """Apply a new UCI_Elo cap while the engine is running."""
        self._config = replace(self._config, uci_elo=elo)
        supported = self._engine.options
        options: dict[str, object] = {}
        if "UCI_LimitStrength" in supported:
            options["UCI_LimitStrength"] = True
        if "UCI_Elo" in supported:
            options["UCI_Elo"] = elo
        try:
            if options:
                self._engine.configure(options)
            self._engine.ping()
        except chess.engine.EngineError as exc:
            log.warning("engine rejected the Elo change: %s", exc)

    def play(self, board: chess.Board) -> SearchResult:
        limit = chess.engine.Limit(time=self._config.move_time_s)
        if self._config.depth is not None:
            limit = chess.engine.Limit(depth=self._config.depth, time=self._config.move_time_s)
        try:
            info = self._engine.analyse(board, limit)
        except chess.engine.EngineError as exc:
            log.warning("engine failure (%s), restarting", exc)
            self.restart()
            info = self._engine.analyse(board, limit)

        if isinstance(info, list):
            info = info[0] if info else {}
        pv = info.get("pv") or []
        move = pv[0] if pv else None
        score_cp: Optional[int] = None
        mate_in: Optional[int] = None
        score = info.get("score")
        if isinstance(score, chess.engine.PovScore):
            pov = score.pov(board.turn)
            if pov.is_mate():
                mate_in = pov.mate()
            else:
                score_cp = pov.score()
        return SearchResult(move=move, score_cp=score_cp, mate_in=mate_in)

    def self_test(self) -> bool:
        board = chess.Board("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1")
        result = self.play(board)
        return result.move is not None and result.move.uci() == "a1a8"

    def close(self) -> None:
        try:
            self._engine.quit()
        except Exception:
            pass
