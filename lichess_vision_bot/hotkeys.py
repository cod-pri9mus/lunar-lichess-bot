"""Global hotkeys (pause / stop / re-detect)."""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)


class Hotkeys:
    def __init__(
        self,
        pause_key: str = "f8",
        stop_key: str = "f9",
        redetect_key: str = "f7",
        paused: threading.Event | None = None,
    ):
        self.paused = paused if paused is not None else threading.Event()
        self.stop_requested = threading.Event()
        self.redetect_requested = threading.Event()
        self._pause_name = pause_key
        self._stop_name = stop_key
        self._redetect_name = redetect_key
        self._listener = None

    def start(self) -> bool:
        try:
            from pynput import keyboard

            pause = getattr(keyboard.Key, self._pause_name.lower())
            stop = getattr(keyboard.Key, self._stop_name.lower())
            redetect = getattr(keyboard.Key, self._redetect_name.lower())

            def on_press(key):
                if key == pause:
                    if self.paused.is_set():
                        self.paused.clear()
                        log.info("resumed (F8)")
                    else:
                        self.paused.set()
                        log.info("paused (F8)")
                elif key == redetect:
                    self.redetect_requested.set()
                    log.info("re-detect requested (F7)")
                elif key == stop:
                    log.info("stop requested (F9)")
                    self.stop_requested.set()
                    return False
                return None

            self._listener = keyboard.Listener(on_press=on_press)
            self._listener.daemon = True
            self._listener.start()
            return True
        except Exception as exc:
            log.warning("global hotkeys unavailable: %s", exc)
            return False

    def close(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
