"""Main vision-driven autoplay state machine."""

from __future__ import annotations

import json
import logging
import threading
import time
import webbrowser
from dataclasses import dataclass, replace
from datetime import datetime, timezone
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
from .capture import CaptureError, Frame, ScreenCapture, StaticCapture
from .config import BotConfig
from .engine import StockfishEngine
from .hotkeys import Hotkeys
from .mouse import MouseController
from .pieces import (
    TemplateLibrary,
    build_start_library,
    load_library,
    save_library,
)
from .tracker import GameTracker, TrackerError
from .turn import detect_turn
from .vision import (
    START_BOARD_FEN,
    BoardReader,
    BoardReading,
    VisualReading,
    infer_bottom_color,
    infer_orientation_from_visual,
)
from .webui import BotState, StateLogHandler, WebServer

log = logging.getLogger(__name__)


@dataclass
class PendingMove:
    move: chess.Move
    pre_placement: str
    pre_board: chess.Board
    expected_placement: str
    deadline: float
    extensions: int = 0


def _parse_color(value: str) -> Optional[chess.Color]:
    return {"white": chess.WHITE, "black": chess.BLACK}.get(value)


def _resolve_dir(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def _color_name(color: Optional[chess.Color]) -> str:
    if color == chess.WHITE:
        return "white"
    if color == chess.BLACK:
        return "black"
    return "unknown"


def _eval_text(result) -> str:
    if result.mate_in is not None:
        return f"mate in {abs(result.mate_in)}"
    if result.score_cp is not None:
        return f"{result.score_cp / 100.0:+.2f}"
    return "?"


def _system_uptime_s() -> float:
    try:
        import ctypes

        return ctypes.windll.kernel32.GetTickCount64() / 1000.0
    except Exception:
        return 0.0


class VisionBot:
    def __init__(
        self,
        config: BotConfig,
        *,
        fen: Optional[str] = None,
        dry_run: bool = False,
        once: bool = False,
        use_hotkeys: bool = True,
        debug_vision: bool = False,
        image: Optional[str] = None,
        web: bool = True,
        web_host: str = "127.0.0.1",
        web_port: int = 8765,
        open_browser: bool = True,
    ):
        self.config = config
        self.dry_run = dry_run or not config.input.enabled
        self.once = once
        self.debug_vision = debug_vision or config.vision.save_debug_frames
        self._image_mode = image is not None
        self._use_hotkeys = use_hotkeys and not self._image_mode
        if image is not None:
            self.dry_run = True

        self._stop = threading.Event()
        self._capture = (
            StaticCapture(image)
            if image is not None
            else ScreenCapture(config.vision.monitor, config.vision.board_rect)
        )
        self._templates_dir = _resolve_dir(config.base_dir, config.vision.templates_dir)
        self._debug_dir = _resolve_dir(config.base_dir, config.vision.debug_dir)
        self._bundled_dir = Path(__file__).resolve().parent / "assets" / "cburnett"

        user_library = load_library(self._templates_dir)
        if user_library is not None and self._templates_are_stale():
            log.info(
                "templates were captured before this Windows boot; "
                "using bundled templates and recalibrating at the start"
            )
            user_library = None
        bundled_library = load_library(self._bundled_dir)
        self._library: Optional[TemplateLibrary] = bundled_library or user_library
        self._library_source = (
            "bundled cburnett"
            if bundled_library
            else ("user templates" if user_library else "none")
        )
        self._paused = threading.Event()
        self._web_enabled = web
        self._web_host = web_host
        self._web_port = web_port
        self._open_browser = open_browser
        self._web: Optional[WebServer] = None
        self._web_state = BotState(self._config_summary())
        self._log_handler = StateLogHandler(self._web_state)
        self._log_handler.setFormatter(
            logging.Formatter("%H:%M:%S %(levelname)s: %(message)s")
        )
        logging.getLogger().addHandler(self._log_handler)
        self._last_state_publish = 0.0
        self._last_frame_publish = 0.0
        self._reader = BoardReader(
            self._library,
            crop_pct=config.vision.cell_crop_pct,
            confidence_threshold=config.vision.confidence_threshold,
        )
        self._geometry: Optional[BoardGeometry] = None
        self._orientation = _parse_color(config.vision.orientation)
        self._orientation_locked = config.vision.orientation != "auto" or bool(fen)
        self._forced_color = _parse_color(config.vision.color)
        self._our_color: Optional[chess.Color] = None
        self._tracker: Optional[GameTracker] = None
        self._pending: Optional[PendingMove] = None
        self._last_key: Optional[str] = None
        self._stable = 0
        self._mismatch = 0
        self._retry = 0
        self._retry_after = 0.0
        self._stalled = False
        self._recover_at = 0.0
        self._finished = False
        self._last_dry_key: Optional[str] = None
        self._last_log: dict[str, float] = {}
        self._engine: Optional[StockfishEngine] = None
        self._mouse: Optional[MouseController] = None
        self._hotkeys: Optional[Hotkeys] = None
        self._stop_after_confirm = False
        self._last_debug = 0.0
        self._last_geometry_scan = 0.0
        self._startup_board = chess.Board(fen) if fen else None
        self._fen_verified = fen is None
        self._resync_requested = False
        self._bootstrap_after = 0.0

        if fen:
            if self._orientation is None and self._forced_color is None:
                raise ValueError("--fen requires --color or --orientation")
            if self._orientation is None:
                self._orientation = self._forced_color
            self._our_color = self._forced_color or self._orientation
            self._tracker = GameTracker(self._startup_board.copy(), self._our_color)

    def _config_summary(self) -> dict:
        return {
            "engine": self.config.engine.path,
            "move_time_s": self.config.engine.move_time_s,
            "skill_level": self.config.engine.skill_level,
            "uci_elo": self.config.engine.uci_elo,
            "monitor": self.config.vision.monitor,
            "board_rect": self.config.vision.board_rect,
            "templates": self._library_source,
            "hotkeys": "F8 пауза · F7 скан · F9 стоп",
        }

    def _templates_are_stale(self) -> bool:
        """True when templates were captured before the current Windows boot."""
        meta_path = self._templates_dir / "library.json"
        if not meta_path.is_file():
            return False
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            created = datetime.fromisoformat(str(meta["created"]))
        except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError):
            return False
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        boot = time.time() - _system_uptime_s()
        return created.timestamp() < boot

    # ------------------------------------------------------------------ setup

    def _setup(self) -> None:
        log.info(
            "starting: monitor=%d rect=%s templates=%s dry_run=%s",
            self.config.vision.monitor,
            self.config.vision.board_rect,
            self._library_source,
            self.dry_run,
        )
        if self._library is None:
            log.info("no templates yet; the bot will auto-calibrate on the starting position")
        if self._orientation is not None:
            log.info("board orientation: %s at the bottom", _color_name(self._orientation))
        if self._startup_board is not None:
            log.info(
                "startup FEN: %s (we play %s)",
                self._startup_board.fen(),
                _color_name(self._our_color),
            )

        self._engine = StockfishEngine(self.config.engine)
        log.info("engine: %s", self._engine.name)
        initial_message = (
            "Ожидание доски по FEN"
            if self._startup_board is not None
            else "Ожидание стартовой позиции"
        )
        self._web_state.update(
            status="waiting",
            message=initial_message,
            engine=self._engine.name,
            templates=self._library_source,
            our_color=_color_name(self._our_color) if self._our_color is not None else None,
        )

        if not self.dry_run:
            self._mouse = MouseController(self.config.input)
            if self.config.input.focus_window:
                if self._mouse.focus_window(self.config.input.focus_window):
                    log.info("focused window matching %r", self.config.input.focus_window)
                else:
                    log.warning("could not focus a window matching %r", self.config.input.focus_window)

        self._hotkeys = Hotkeys(paused=self._paused)
        if self._use_hotkeys and self._hotkeys.start():
            log.info("hotkeys: F8 pause/resume, F7 re-detect, F9 stop")
        elif self._use_hotkeys:
            log.info("hotkeys disabled")

    # ------------------------------------------------------------------- loop

    def run(self) -> None:
        if self._web_enabled:
            self._web = WebServer(self._web_state, self._web_host, self._web_port)
            url = self._web.start()
            if url:
                log.info("browser panel: %s", url)
                self._web_state.update(panel_url=url)
                if self._open_browser:
                    threading.Thread(
                        target=self._open_panel, args=(url,), name="bot-open-panel", daemon=True
                    ).start()
            else:
                log.warning(
                    "browser panel could not bind %s:%s; the bot continues without it",
                    self._web_host,
                    self._web_port,
                )
        try:
            self._setup()
            self._loop()
        finally:
            self.close()
            if self._web is not None:
                self._web.stop()

    def _open_panel(self, url: str) -> None:
        time.sleep(0.4)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    def _loop(self) -> None:
        interval = 1.0 / self.config.vision.capture_fps
        while not self._stop.is_set():
            started = time.perf_counter()
            self._process_web_commands()
            if self._stop.is_set():
                break
            if self._hotkeys is not None:
                if self._hotkeys.stop_requested.is_set():
                    break
                if self._hotkeys.redetect_requested.is_set():
                    self._hotkeys.redetect_requested.clear()
                    self._geometry = None
                    self._stalled = False
                    self._mismatch = 0
                    self._resync_requested = True
                    log.info("re-detecting the board")

            if self._stalled and not self._finished and time.monotonic() >= self._recover_at:
                self._recover()

            self._web_state.update(paused=self._paused.is_set())

            try:
                frame = self._capture.grab()
            except CaptureError as exc:
                log.error("%s", exc)
                self._stop.wait(1.0)
                continue

            geometry = self._ensure_geometry(frame)
            if geometry is None:
                self._log_throttled("geometry", "board not found; waiting (set vision.board_rect if needed)")
                self._publish_frame(frame, None, None)
                self._stop.wait(0.4)
                continue

            try:
                visual = self._reader.visual(frame, geometry)
            except Exception:
                log.exception("vision read failed")
                self._stop.wait(0.4)
                continue

            self._publish(frame, geometry, visual)

            if self.debug_vision and time.monotonic() - self._last_debug > 5.0:
                self._last_debug = time.monotonic()
                self._save_debug(frame, geometry, visual, "live")

            try:
                self._handle(frame, geometry, visual, self._paused.is_set())
            except Exception:
                log.exception("frame handling failed")

            elapsed = time.perf_counter() - started
            if elapsed < interval:
                time.sleep(interval - elapsed)

    # --------------------------------------------------------------- geometry

    def _excluded_window_rects(self, frame: Frame) -> tuple[tuple[int, int, int, int], ...]:
        """Screen rectangles of windows that must not be mistaken for the board.

        The local dashboard can be placed next to Lichess; its live board preview
        is itself a board-like square.  Excluding that window prevents the
        detector from locking onto its own preview (the "half-screen" crop).
        """
        if self._image_mode:
            return ()
        title = self.config.vision.ignore_window_title
        if not title:
            return ()
        try:
            import pygetwindow as gw

            rects: list[tuple[int, int, int, int]] = []
            for window in gw.getAllWindows():
                if getattr(window, "isMinimized", False):
                    continue
                if not getattr(window, "visible", True):
                    continue
                window_title = window.title or ""
                if title.lower() not in window_title.lower():
                    continue
                if window.width < 100 or window.height < 100:
                    continue
                rects.append(
                    (
                        int(window.left - frame.origin[0]),
                        int(window.top - frame.origin[1]),
                        int(window.width),
                        int(window.height),
                    )
                )
            return tuple(rects)
        except Exception as exc:
            log.debug("window exclusion unavailable: %s", exc)
            return ()

    def _ensure_geometry(self, frame: Frame) -> Optional[BoardGeometry]:
        if self.config.vision.board_rect is not None:
            if self._geometry is None:
                self._geometry = geometry_from_rect(
                    self.config.vision.board_rect,
                    frame.origin,
                    relative=not self._image_mode,
                    inset_pct=self.config.vision.board_inset_pct,
                )
                log.info("using configured board rect %s", self.config.vision.board_rect)
            return self._geometry

        now = time.monotonic()
        if self._geometry is not None:
            if self._tracker is not None and not self._stalled:
                return self._geometry
            if now - self._last_geometry_scan < self.config.vision.redetect_interval_s:
                return self._geometry

        self._last_geometry_scan = now
        found = find_board(
            frame.image,
            exclude_rects=self._excluded_window_rects(frame),
        )
        if found is None:
            if self._image_mode:
                height, width = frame.image.shape[:2]
                if 0.90 <= width / max(1, height) <= 1.10 and min(width, height) >= 300:
                    self._geometry = geometry_from_rect(
                        (0, 0, width, height),
                        frame.origin,
                        inset_pct=self.config.vision.board_inset_pct,
                    )
                    log.info("using the whole square image as the board")
            return self._geometry
        quad, score = found
        new_geometry = make_geometry(
            quad, frame.origin, inset_pct=self.config.vision.board_inset_pct
        )
        if self._geometry is None or float(np.linalg.norm(new_geometry.quad - self._geometry.quad)) > 8.0:
            log.info("board detected (checkerboard score %.2f)", score)
            self._geometry = new_geometry
        return self._geometry

    # ----------------------------------------------------------------- logic

    def _handle(
        self,
        frame: Frame,
        geometry: BoardGeometry,
        visual: VisualReading,
        paused: bool = False,
    ) -> None:
        stable = self._update_stability(visual)

        if self._startup_board is not None and not self._fen_verified:
            self._verify_fen(visual, stable)
            return

        if self._tracker is None:
            self._resync_requested = False
            self._wait_for_game(frame, geometry, visual, stable)
            return

        if (
            visual.start_pattern
            and stable
            and self._tracker.placement() != START_BOARD_FEN
            and self._fen_verified
        ):
            log.info("starting position detected; beginning a new game")
            if not self._orientation_locked:
                self._orientation = None
            self._begin_game(frame, geometry, visual)
            return

        if self._stalled:
            return

        reading = self._reader.board_reading(visual, self._orientation)
        if self._resync_requested:
            if stable:
                self._resync_requested = False
                self._resync(reading)
            return
        if self._pending is not None:
            self._handle_pending(reading, stable)
            return

        if not stable:
            return
        if not reading.valid:
            self._log_throttled(
                "invalid",
                f"invalid board read: unknown={reading.unknown} confidence={reading.confidence:.2f}",
            )
            return

        if self._tracker.placement_matches(reading.board):
            if self._tracker.our_turn() and not paused:
                self._play(reading, geometry)
            return

        if self._tracker.rewind_to(reading.placement):
            log.info("takeback detected; rewound the tracker")
            self._mismatch = 0
            return

        if self._tracker.our_turn():
            if self.dry_run:
                move = self._tracker.infer_move(reading.board, tolerance=1)
                if move is not None:
                    try:
                        self._tracker.push(move)
                    except TrackerError as exc:
                        self._mismatch_event(reading, str(exc))
                        return
                    log.info("[dry-run] manual move: %s", move.uci())
                    self._mismatch = 0
                    return
            self._mismatch_event(reading, "board changed on our turn")
            return

        move = self._tracker.infer_move(reading.board, tolerance=1)
        if move is not None:
            try:
                self._tracker.push(move)
            except TrackerError as exc:
                self._mismatch_event(reading, str(exc))
                return
            log.info(
                "opponent played %s%s",
                move.uci(),
                f" (tolerated {self._tracker.last_infer_diff} vision diff)"
                if self._tracker.last_infer_diff
                else "",
            )
            self._web_state.update(
                last_move=move.uci(),
                message=f"Соперник: {move.uci()}",
            )
            self._mismatch = 0
            return

        self._mismatch_event(reading, "observed placement is not reachable by a legal move")

    def _update_stability(self, visual: VisualReading) -> bool:
        if visual.key == self._last_key:
            self._stable += 1
        else:
            self._last_key = visual.key
            self._stable = 1
        return self._stable >= self.config.vision.stable_reads

    def _wait_for_game(
        self, frame: Frame, geometry: BoardGeometry, visual: VisualReading, stable: bool
    ) -> None:
        if self._orientation is None:
            if visual.start_pattern and stable:
                self._begin_game(frame, geometry, visual)
            else:
                self._log_throttled(
                    "start", "waiting for the standard starting position (or pass --fen)"
                )
            return

        reading = self._reader.board_reading(visual, self._orientation)
        if stable and reading.valid and reading.placement == START_BOARD_FEN:
            self._begin_game(frame, geometry, visual)
        else:
            self._log_throttled("start", "waiting for the standard starting position")

    def _verify_fen(self, visual: VisualReading, stable: bool) -> None:
        if not stable or self._tracker is None:
            return
        reading = self._reader.board_reading(visual, self._orientation)
        if not reading.valid:
            self._log_throttled("fen", "waiting for a clean board read for --fen")
            return
        if self._tracker.placement_matches(reading.board):
            self._fen_verified = True
            log.info("the on-screen board matches the provided FEN")
            self._web_state.update(
                status="playing",
                games=1,
                message="FEN подтверждён. Играем.",
            )
            return

        move = self._tracker.infer_move(reading.board, tolerance=1)
        if move is not None:
            try:
                self._tracker.push(move)
            except TrackerError as exc:
                log.warning("FEN catch-up failed: %s", exc)
                return
            self._fen_verified = True
            log.info("FEN verified after %s", move.uci())
            self._web_state.update(
                status="playing",
                games=1,
                message=f"FEN подтверждён после {move.uci()}. Играем.",
            )
            return
        self._log_throttled("fen", "waiting for the on-screen board to match --fen")

    def _begin_game(self, frame: Frame, geometry: BoardGeometry, visual: VisualReading) -> None:
        now = time.monotonic()
        if now < self._bootstrap_after:
            return

        # Fast path: with templates captured from this exact screen, start on
        # the first clean start frame instead of recalibrating.  This matters
        # for 1+0 games where the opponent moves almost immediately.
        orientation = self._orientation
        if orientation is None:
            orientation = infer_orientation_from_visual(visual)
        if (
            orientation is not None
            and self._reader.library is not None
            and self._library_source in ("user templates", "screen capture")
        ):
            reading = self._reader.board_reading(visual, orientation)
            if reading.valid and reading.placement == START_BOARD_FEN:
                log.info("start read with saved templates; beginning a new game")
                self._start_tracker(visual, orientation)
                return

        built = build_start_library(
            visual.signatures,
            threshold=self.config.vision.confidence_threshold,
            bottom_color=self._orientation,
        )
        orientation = self._orientation
        if built is not None:
            library, bottom = built
            self._library = library
            self._reader.library = library
            orientation = bottom
            visual = self._reader.visual(frame, geometry)

        if orientation is None:
            orientation = infer_orientation_from_visual(visual)
        if orientation is None:
            self._bootstrap_after = now + 1.0
            self._log_throttled(
                "orientation",
                "cannot determine the board orientation; pass --color/--orientation or run --calibrate",
            )
            return

        reading = self._reader.board_reading(visual, orientation)
        if not reading.valid or reading.placement != START_BOARD_FEN:
            self._bootstrap_after = now + 1.0
            self._log_throttled("bootstrap", "waiting for a clean starting-position read")
            return

        if built is not None and self.config.vision.auto_save_templates:
            try:
                save_library(
                    self._templates_dir,
                    self._library.samples,
                    source="screen capture at start position",
                    threshold=self.config.vision.confidence_threshold,
                )
                log.info("saved %d templates to %s", len(self._library.samples), self._templates_dir)
            except OSError as exc:
                log.warning("could not save templates: %s", exc)

        self._start_tracker(visual, orientation)

    def _start_tracker(self, visual: VisualReading, orientation: chess.Color) -> None:
        self._orientation = orientation
        # Our colour is always the colour at the bottom of the board.
        self._our_color = orientation
        self._tracker = GameTracker(chess.Board(), self._our_color)
        self._pending = None
        self._mismatch = 0
        self._retry = 0
        self._retry_after = 0.0
        self._stalled = False
        self._finished = False
        self._recover_at = 0.0
        self._resync_requested = False
        self._stable = 0
        self._last_key = visual.key
        log.info("new game: playing %s", _color_name(self._our_color))
        self._web_state.update(
            status="playing",
            our_color=_color_name(self._our_color),
            message=f"Играем за {_color_name(self._our_color)}",
            last_move=None,
            eval=None,
            fen=None,
            ascii=None,
            pending=False,
            confidence=None,
        )
        self._web_state.increment("games")

    # ------------------------------------------------------------------ moves

    def _play(self, reading: BoardReading, geometry: BoardGeometry) -> None:
        if self._tracker is None:
            return
        if self.dry_run:
            if self._last_dry_key == reading.placement:
                return
            try:
                result = self._engine.play(self._tracker.board)
            except Exception as exc:
                log.error("engine failed: %s", exc)
                self._stalled = True
                return
            if result.move is None:
                log.info("no legal move in the tracked position")
                self._stalled = True
                return
            log.info("[dry-run] best move: %s (%s)", result.move.uci(), _eval_text(result))
            self._last_dry_key = reading.placement
            self._web_state.update(
                message=f"Подсказка: {result.move.uci()} ({_eval_text(result)})",
                last_move=result.move.uci(),
                eval=_eval_text(result),
                pending=False,
            )
            if self.once:
                self._stop.set()
            return

        if time.monotonic() < self._retry_after:
            return
        if self._tracker.is_game_over():
            result_text = self._tracker.board.result()
            log.info("game over: %s", result_text)
            self._web_state.update(
                status="finished",
                message=f"Партия окончена: {result_text}. Ожидание новой партии.",
            )
            self._stalled = True
            self._finished = True
            self._recover_at = 0.0
            return

        self._web_state.update(status="thinking", message="Stockfish думает…")
        try:
            result = self._engine.play(self._tracker.board)
        except Exception as exc:
            log.error("engine failed: %s", exc)
            self._stall(f"engine: {exc}")
            return
        if result.move is None:
            log.info("engine returned no move")
            self._stall("engine returned no move")
            return
        move = result.move
        if (
            move.promotion is not None
            and move.promotion != chess.QUEEN
            and self.config.input.promotion_mode == "auto_queen"
        ):
            queen_move = chess.Move(move.from_square, move.to_square, promotion=chess.QUEEN)
            if queen_move in self._tracker.board.legal_moves:
                log.warning(
                    "underpromotion %s replaced by queen (promotion_mode=auto_queen)",
                    move.uci(),
                )
                move = queen_move

        log.info("playing %s (%s)", move.uci(), _eval_text(result))
        self._web_state.update(
            status="playing",
            message=f"Ход: {move.uci()} ({_eval_text(result)})",
            last_move=move.uci(),
            eval=_eval_text(result),
        )
        expected = self._tracker.board.piece_at(move.from_square)
        observed = reading.board.piece_at(move.from_square)
        if expected != observed:
            log.warning(
                "move %s source mismatch: expected %s, observed %s; resyncing",
                move.uci(),
                expected.symbol() if expected else "empty",
                observed.symbol() if observed else "empty",
            )
            self._stall("the source square does not match the tracked piece")
            return
        pre_placement = self._tracker.placement()
        pre_board = self._tracker.board.copy()
        try:
            self._mouse.make_move(
                geometry,
                move,
                self._orientation,
                promotion_picker=self._pick_promotion,
            )
        except Exception as exc:
            log.error("mouse input failed: %s", exc)
            self._stall(f"mouse: {exc}")
            return

        try:
            self._tracker.push(move)
        except TrackerError as exc:
            log.error("internal move error: %s", exc)
            self._stall(f"internal move: {exc}")
            return
        self._pending = PendingMove(
            move=move,
            pre_placement=pre_placement,
            pre_board=pre_board,
            expected_placement=self._tracker.placement(),
            deadline=time.monotonic() + self.config.input.confirm_timeout_s,
        )
        self._web_state.update(
            pending=True,
            moves=len(self._tracker.board.move_stack),
        )
        self._stop_after_confirm = self.once

    def _handle_pending(self, reading: BoardReading, stable: bool) -> None:
        pending = self._pending
        if pending is None:
            return
        now = time.monotonic()

        if reading.valid and self._tracker.placement_matches(reading.board):
            log.info("move confirmed: %s", pending.move.uci())
            self._web_state.update(
                pending=False,
                message=f"Ход подтверждён: {pending.move.uci()}",
            )
            self._pending = None
            self._mismatch = 0
            self._retry = 0
            if self._mouse is not None and self._geometry is not None:
                self._mouse.park(self._geometry)
            if self._stop_after_confirm:
                self._stop.set()
            return

        if stable and reading.valid:
            opponent = self._tracker.infer_move(reading.board, tolerance=1)
            if opponent is not None:
                try:
                    self._tracker.push(opponent)
                except TrackerError as exc:
                    self._stall(str(exc))
                    return
                log.info(
                    "opponent premoved %s%s",
                    opponent.uci(),
                    f" (tolerated {self._tracker.last_infer_diff} vision diff)"
                    if self._tracker.last_infer_diff
                    else "",
                )
                self._pending = None
                self._web_state.update(
                    pending=False,
                    last_move=opponent.uci(),
                    message=f"Соперник: {opponent.uci()}",
                )
                self._mismatch = 0
                self._retry = 0
                if self._stop_after_confirm:
                    self._stop.set()
                return

        if now < pending.deadline:
            return

        if not stable or not reading.valid:
            pending.extensions += 1
            if pending.extensions <= 3:
                pending.deadline = now + 1.0
                return
            self._stall("no clean board read while confirming the move")
            return

        if GameTracker.same_placement(pending.pre_board, reading.board):
            self._tracker.undo()
            self._pending = None
            self._retry += 1
            if self._retry > self.config.input.max_move_retries:
                self._stall("the move did not register")
                return
            log.warning(
                "move %s did not register; retrying %d/%d",
                pending.move.uci(),
                self._retry,
                self.config.input.max_move_retries,
            )
            self._web_state.update(
                message=f"Ход не зарегистрирован, повтор {self._retry}/{self.config.input.max_move_retries}"
            )
            self._retry_after = now + 0.35
            return

        self._stall("the board shows an unexpected position after our move")

    def _resync(self, reading: BoardReading) -> None:
        if self._tracker is None:
            return
        if not reading.valid:
            log.warning("resync skipped: no clean board read")
            return
        if self._tracker.placement_matches(reading.board):
            log.info("resync: the tracker already matches the board")
            return

        move = self._tracker.infer_move(reading.board, tolerance=1)
        if move is not None:
            try:
                self._tracker.push(move)
                log.info("resync: applied %s", move.uci())
            except TrackerError as exc:
                log.warning("resync failed: %s", exc)
            return

        if self._tracker.rewind_to(reading.placement):
            log.info("resync: rewound to the observed position")
            return

        if self._tracker.undo():
            if self._tracker.placement_matches(reading.board):
                log.info("resync: rolled back a pending move")
                return
            move = self._tracker.infer_move(reading.board, tolerance=1)
            if move is not None:
                try:
                    self._tracker.push(move)
                    log.info("resync: applied %s after rollback", move.uci())
                except TrackerError as exc:
                    log.warning("resync failed: %s", exc)
                return
            if self._tracker.rewind_to(reading.placement):
                log.info("resync: rewound after rollback")
                return

        if self._reset_to_observed(reading):
            log.warning("resync: tracker reset to the observed board")
            return
        log.error("resync failed; restart with --fen or start a new game")
        self._web_state.update(message="Синхронизация не удалась; нажмите F7 или начните новую партию")

    @staticmethod
    def _infer_turn(board: chess.Board, our_color: chess.Color) -> chess.Color:
        white_king = board.king(chess.WHITE)
        black_king = board.king(chess.BLACK)
        if white_king is None or black_king is None:
            return our_color
        white_check = board.is_attacked_by(chess.BLACK, white_king)
        black_check = board.is_attacked_by(chess.WHITE, black_king)
        if white_check and not black_check:
            return chess.WHITE
        if black_check and not white_check:
            return chess.BLACK
        return our_color

    def _home_castling_rights(self, board: chess.Board) -> int:
        rights = 0
        if board.piece_at(chess.E1) == chess.Piece(chess.KING, chess.WHITE):
            if board.piece_at(chess.H1) == chess.Piece(chess.ROOK, chess.WHITE):
                rights |= chess.BB_H1
            if board.piece_at(chess.A1) == chess.Piece(chess.ROOK, chess.WHITE):
                rights |= chess.BB_A1
        if board.piece_at(chess.E8) == chess.Piece(chess.KING, chess.BLACK):
            if board.piece_at(chess.H8) == chess.Piece(chess.ROOK, chess.BLACK):
                rights |= chess.BB_H8
            if board.piece_at(chess.A8) == chess.Piece(chess.ROOK, chess.BLACK):
                rights |= chess.BB_A8
        return rights

    def _adopt_board(self, board: chess.Board, turn: chess.Color, message: str) -> bool:
        if self._our_color is None:
            return False
        board = board.copy()
        board.turn = turn
        board.castling_rights = self._home_castling_rights(board)
        board.ep_square = None
        board.halfmove_clock = 0
        board.fullmove_number = 1
        if not board.is_valid():
            log.warning("cannot adopt the visible board: not a legal position")
            return False
        self._tracker = GameTracker(board, self._our_color)
        self._pending = None
        self._stalled = False
        self._finished = False
        self._resync_requested = False
        self._mismatch = 0
        self._retry = 0
        self._retry_after = 0.0
        self._stable = 0
        self._last_key = None
        self._recover_at = 0.0
        log.warning("tracker adopted the visible board (%s to move)", _color_name(board.turn))
        self._web_state.update(
            status="playing",
            message=message,
            fen=board.fen(),
            ascii=str(board),
            turn=_color_name(board.turn),
            our_color=_color_name(self._our_color),
            pending=False,
        )
        return True

    def _reset_to_observed(self, reading: BoardReading) -> bool:
        """Last-resort resync: adopt the visible position as the tracker."""
        if self._our_color is None:
            return False
        turn = self._infer_turn(reading.board, self._our_color)
        return self._adopt_board(reading.board, turn, "Синхронизация по доске")

    def _pick_promotion(self, move: chess.Move) -> bool:
        if not move.promotion or self._mouse is None:
            return False
        key = {
            chess.QUEEN: "q",
            chess.ROOK: "r",
            chess.BISHOP: "b",
            chess.KNIGHT: "n",
        }.get(move.promotion)
        if key is None:
            return False
        self._mouse.press_key(key)
        log.info("promotion selected by key %s: %s", key, move.uci())
        return True

    # --------------------------------------------------------- browser panel

    def _process_web_commands(self) -> None:
        for request in self._web_state.drain_start_requests():
            self._start_from_fen(
                str(request.get("fen", "")),
                str(request.get("color", "white")),
                bool(request.get("flipped", False)),
            )
        for request in self._web_state.drain_start_current_requests():
            self._start_from_current(
                str(request.get("color", "white")),
                bool(request.get("flipped", False)),
                bool(request.get("my_turn", True)),
            )
        for command in self._web_state.drain_commands():
            self._handle_command(command)

    def _start_from_fen(self, fen: str, color: str, flipped: bool = False) -> None:
        try:
            board = chess.Board(fen)
        except ValueError as exc:
            log.warning("invalid FEN from panel: %s", exc)
            self._web_state.update(message=f"Неверный FEN: {exc}")
            return
        if board.king(chess.WHITE) is None or board.king(chess.BLACK) is None:
            self._web_state.update(message="FEN без одного из королей")
            return

        our = chess.WHITE if color == "white" else chess.BLACK
        orientation = (not our) if flipped else our
        self._startup_board = board
        self._fen_verified = False
        self._forced_color = our
        self._our_color = our
        self._orientation = orientation
        self._orientation_locked = True
        self._tracker = GameTracker(board.copy(), our)
        self._pending = None
        self._stalled = False
        self._finished = False
        self._recover_at = 0.0
        self._mismatch = 0
        self._retry = 0
        self._retry_after = 0.0
        self._stable = 0
        self._last_key = None
        self._resync_requested = False
        log.info(
            "panel FEN start: %s (we play %s, bottom %s)",
            board.fen(),
            _color_name(our),
            _color_name(orientation),
        )
        self._web_state.update(
            status="playing",
            our_color=_color_name(our),
            message="FEN принят, сверяю доску…",
            last_move=None,
            eval=None,
            fen=board.fen(),
            ascii=str(board),
            pending=False,
            paused=self._paused.is_set(),
            games=1,
        )

    def _start_from_current(
        self, color: str, flipped: bool = False, my_turn: bool = True
    ) -> None:
        selected = chess.WHITE if color == "white" else chess.BLACK
        try:
            frame = self._capture.grab()
        except CaptureError as exc:
            log.warning("current-position start: %s", exc)
            self._web_state.update(message=f"Не удалось снять экран: {exc}")
            return
        geometry = self._ensure_geometry(frame)
        if geometry is None:
            self._web_state.update(message="Доска не найдена — старт с текущей позиции невозможен")
            return
        try:
            visual = self._reader.visual(frame, geometry)
        except Exception as exc:
            log.warning("current-position start vision failed: %s", exc)
            self._web_state.update(message="Не удалось прочитать доску")
            return
        bottom = infer_bottom_color(visual)
        if bottom is not None:
            our = bottom
            orientation = bottom
            if bottom != selected:
                log.warning(
                    "current-position start: selected %s differs from the board bottom %s; "
                    "using the bottom (our colour is always at the bottom)",
                    _color_name(selected),
                    _color_name(bottom),
                )
        else:
            our = selected
            orientation = (not our) if flipped else our
            log.info(
                "current-position start: board bottom unreadable; using selected %s",
                _color_name(our),
            )
        clock_turn = detect_turn(frame, geometry, orientation)
        turn = our if my_turn else (not our)
        if clock_turn is not None and clock_turn != turn:
            log.warning(
                "current-position start: clocks suggest %s to move, but the selected turn is %s",
                _color_name(clock_turn),
                _color_name(turn),
            )
        reading = self._reader.board_reading(visual, orientation)
        if not reading.valid:
            self._web_state.update(
                message=(
                    f"Доска читается неуверенно (confidence {reading.confidence:.2f}); "
                    "попробуйте ещё раз"
                )
            )
            return
        self._our_color = our
        self._forced_color = our
        self._orientation = orientation
        self._orientation_locked = True
        self._startup_board = None
        self._fen_verified = True
        if not self._adopt_board(reading.board, turn, "Старт с текущей позиции"):
            self._web_state.update(message="Позиция на экране не является легальной")
            return
        self._web_state.increment("games")
        self._web_state.update(paused=self._paused.is_set())
        log.info(
            "panel current-position start: we play %s, bottom %s, %s to move",
            _color_name(our),
            _color_name(orientation),
            _color_name(turn),
        )

    def _handle_command(self, command: str) -> None:
        if command.startswith("set-elo:"):
            try:
                elo = int(command.split(":", 1)[1])
            except ValueError:
                return
            if not (1320 <= elo <= 3190):
                return
            if self._engine is not None:
                self._engine.set_elo(elo)
            self.config = replace(
                self.config,
                engine=replace(self.config.engine, uci_elo=elo),
            )
            self._web_state.update(
                config=self._config_summary(),
                elo=elo,
                message=f"Elo: {elo}",
            )
            log.info("web: elo=%d", elo)
            return
        if command == "stop":
            self._stop.set()
            self._web_state.update(status="stopped", message="Остановлено из панели")
            return
        if command in ("toggle-pause", "pause", "resume"):
            if command == "pause":
                self._paused.set()
            elif command == "resume":
                self._paused.clear()
            elif self._paused.is_set():
                self._paused.clear()
            else:
                self._paused.set()
            paused = self._paused.is_set()
            self._web_state.update(paused=paused, message="Пауза" if paused else "Продолжение")
            log.info("web: %s", "paused" if paused else "resumed")
            return
        if command == "redetect":
            self._geometry = None
            self._stalled = False
            self._mismatch = 0
            self._resync_requested = True
            self._web_state.update(message="Пересканирование доски…")
            log.info("web: re-detect")
            return
        if command == "calibrate":
            self._calibrate_from_web()
            return
        if command == "check":
            self._dump_debug("web-check")
            self._web_state.update(message="Проверка зрения: кадр сохранён в debug/")
            return

    def _calibrate_from_web(self) -> None:
        if self._geometry is None:
            self._web_state.update(message="Калибровка: доска не найдена")
            return
        try:
            frame = self._capture.grab()
            visual = self._reader.visual(frame, self._geometry)
            built = build_start_library(
                visual.signatures,
                threshold=self.config.vision.confidence_threshold,
                bottom_color=self._orientation,
            )
        except Exception as exc:
            log.warning("web calibration failed: %s", exc)
            self._web_state.update(message=f"Калибровка не удалась: {exc}")
            return
        if built is None:
            self._web_state.update(message="Калибровка: поставьте стартовую позицию")
            log.warning("web calibration needs the starting position")
            return

        library, bottom = built
        self._library = library
        self._reader.library = library
        self._library_source = "screen capture"
        if not self._orientation_locked:
            self._orientation = bottom
        if self.config.vision.auto_save_templates:
            try:
                save_library(
                    self._templates_dir,
                    library.samples,
                    source="web calibration at start position",
                    threshold=self.config.vision.confidence_threshold,
                )
            except OSError as exc:
                log.warning("could not save templates: %s", exc)
        self._web_state.update(
            templates="screen capture",
            message=f"Калибровка: {len(library.samples)} шаблонов",
        )
        log.info("web calibration: %d templates", len(library.samples))

    def _publish(self, frame: Frame, geometry: BoardGeometry, visual: VisualReading) -> None:
        now = time.monotonic()
        if now - self._last_state_publish >= 0.25:
            self._last_state_publish = now
            values: dict = {
                "confidence": round(float(visual.confidence), 3),
                "pending": self._pending is not None,
                "paused": self._paused.is_set(),
            }
            if self._tracker is not None:
                values.update(
                    fen=self._tracker.board.fen(),
                    ascii=str(self._tracker.board),
                    turn=_color_name(self._tracker.board.turn),
                    our_color=_color_name(self._our_color),
                    moves=len(self._tracker.board.move_stack),
                )
            self._web_state.update(**values)
        self._publish_frame(frame, geometry, visual)

    def _publish_frame(
        self,
        frame: Frame,
        geometry: Optional[BoardGeometry],
        visual: Optional[VisualReading],
    ) -> None:
        now = time.monotonic()
        if now - self._last_frame_publish < 1.0:
            return
        self._last_frame_publish = now

        if geometry is None or visual is None:
            preview = np.full((480, 480, 3), (12, 16, 22), dtype=np.uint8)
            cv2.putText(
                preview,
                "NO BOARD",
                (168, 232),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (90, 90, 255),
                2,
                cv2.LINE_AA,
            )
            cv2.putText(
                preview,
                "waiting for the chessboard",
                (118, 262),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (120, 140, 160),
                1,
                cv2.LINE_AA,
            )
        else:
            preview = geometry.warp(frame.image)
            step = preview.shape[0] / 8.0
            threshold = self.config.vision.confidence_threshold
            for row in range(8):
                for col in range(8):
                    piece = visual.cells[row][col]
                    score = visual.scores[row][col]
                    ok = piece is not None and score >= threshold
                    color = (0, 220, 120) if ok else (90, 90, 255)
                    label = piece.symbol() if piece is not None else "."
                    x = int(col * step + 6)
                    y = int(row * step + 26)
                    cv2.putText(
                        preview,
                        label,
                        (x, y),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.62,
                        color,
                        2,
                        cv2.LINE_AA,
                    )
                    if piece is not None:
                        cv2.putText(
                            preview,
                            f"{score:.2f}",
                            (x, y + 18),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.4,
                            color,
                            1,
                            cv2.LINE_AA,
                        )
            for index in range(1, 8):
                position = int(index * step)
                cv2.line(
                    preview,
                    (position, 0),
                    (position, preview.shape[0] - 1),
                    (40, 60, 55),
                    1,
                )
                cv2.line(
                    preview,
                    (0, position),
                    (preview.shape[1] - 1, position),
                    (40, 60, 55),
                    1,
                )
            preview = cv2.resize(preview, (480, 480), interpolation=cv2.INTER_AREA)

        ok, buffer = cv2.imencode(
            ".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), 78]
        )
        if ok:
            self._web_state.set_frame(buffer.tobytes())

    # --------------------------------------------------------------- failures

    def _mismatch_event(self, reading: BoardReading, reason: str) -> None:
        self._mismatch += 1
        if self._mismatch == 1:
            log.warning("%s (observed %s)", reason, reading.placement)
            self._web_state.update(message=f"Расхождение: {reason}")
            self._dump_debug("mismatch")
        if self._mismatch >= 60:
            self._stall(reason)

    def _stall(self, reason: str) -> None:
        if self._stalled:
            return
        self._stalled = True
        self._finished = False
        self._recover_at = time.monotonic() + 2.5
        self._pending = None
        self._web_state.update(
            status="stalled",
            message=f"{reason} · пересканирую доску…",
            pending=False,
        )
        log.error("STALLED: %s (auto-recovery in 2.5 s; F7 now, F9 stop)", reason)
        if self._mouse is not None and self._geometry is not None:
            self._mouse.park(self._geometry)
        self._dump_debug("stall")

    def _recover(self) -> None:
        self._stalled = False
        self._finished = False
        self._pending = None
        self._geometry = None
        self._last_geometry_scan = 0.0
        self._resync_requested = True
        self._stable = 0
        self._last_key = None
        self._mismatch = 0
        self._retry = 0
        self._retry_after = 0.0
        self._recover_at = 0.0
        log.warning("stalled: re-detecting the board and resyncing")
        self._web_state.update(
            status="playing",
            message="Восстановление: пересканирую доску…",
            pending=False,
        )

    def _dump_debug(self, reason: str) -> None:
        if self._geometry is None:
            return
        try:
            frame = self._capture.grab()
            visual = self._reader.visual(frame, self._geometry)
            path = self._save_debug(frame, self._geometry, visual, reason)
            if path is not None:
                log.info("debug frame: %s", path)
            if self._orientation is not None:
                reading = self._reader.board_reading(visual, self._orientation)
                try:
                    board = chess.Board(reading.placement + " w - - 0 1")
                    log.info("observed board:\n%s", board)
                except ValueError:
                    log.info("observed placement: %s", reading.placement)
        except Exception as exc:
            log.debug("debug dump failed: %s", exc)

    def _save_debug(
        self,
        frame: Frame,
        geometry: BoardGeometry,
        visual: VisualReading,
        reason: str,
    ) -> Optional[Path]:
        try:
            from .diagnostics import annotate_frame

            self._debug_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            path = self._debug_dir / f"{stamp}_{reason}.png"
            image = annotate_frame(
                frame,
                geometry,
                visual,
                self._orientation,
                self.config.vision.confidence_threshold,
            )
            from .imgio import imwrite

            imwrite(path, image)
            return path
        except Exception as exc:
            log.debug("could not save debug frame: %s", exc)
            return None

    def _log_throttled(self, key: str, message: str) -> None:
        now = time.monotonic()
        if now - self._last_log.get(key, 0.0) >= 5.0:
            self._last_log[key] = now
            log.info(message)

    # ---------------------------------------------------------------- cleanup

    def close(self) -> None:
        self._stop.set()
        self._web_state.update(status="stopped", message="Остановлено")
        logging.getLogger().removeHandler(self._log_handler)
        if self._hotkeys is not None:
            self._hotkeys.close()
        if self._engine is not None:
            self._engine.close()
        self._capture.close()
