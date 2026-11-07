"""Local browser control panel for the vision bot."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

COMMANDS = {
    "toggle-pause",
    "pause",
    "resume",
    "redetect",
    "stop",
    "calibrate",
    "check",
}


class BotState:
    """Thread-safe state shared by the bot loop and the HTTP server."""

    def __init__(self, config_summary: Optional[dict[str, Any]] = None):
        self._lock = threading.Lock()
        self._config = dict(config_summary or {})
        self._started = time.time()
        self._data: dict[str, Any] = {
            "status": "starting",
            "message": "Запуск…",
            "our_color": None,
            "turn": None,
            "last_move": None,
            "eval": None,
            "confidence": None,
            "fen": None,
            "ascii": None,
            "pending": False,
            "paused": False,
            "moves": 0,
            "games": 0,
            "engine": None,
            "templates": None,
            "panel_url": None,
            "frame_seq": 0,
        }
        self._logs: deque[str] = deque(maxlen=300)
        self._frame: Optional[bytes] = None
        self._commands: queue.Queue[str] = queue.Queue()
        self._start_requests: queue.Queue[dict[str, Any]] = queue.Queue()
        self._start_current_requests: queue.Queue[dict[str, Any]] = queue.Queue()

    def update(self, **values: Any) -> None:
        with self._lock:
            if isinstance(values.get("config"), dict):
                self._config.update(values["config"])
            self._data.update(values)

    def increment(self, key: str, by: int = 1) -> None:
        with self._lock:
            self._data[key] = int(self._data.get(key, 0)) + by

    def add_log(self, line: str) -> None:
        with self._lock:
            self._logs.append(line)

    def command(self, name: str) -> None:
        self._commands.put(name)

    def drain_commands(self) -> list[str]:
        items: list[str] = []
        while True:
            try:
                items.append(self._commands.get_nowait())
            except queue.Empty:
                break
        return items

    def request_start(self, fen: str, color: str, flipped: bool) -> None:
        self._start_requests.put({"fen": fen, "color": color, "flipped": flipped})

    def drain_start_requests(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        while True:
            try:
                items.append(self._start_requests.get_nowait())
            except queue.Empty:
                break
        return items

    def request_start_current(self, color: str, flipped: bool, my_turn: bool = True) -> None:
        self._start_current_requests.put(
            {"color": color, "flipped": flipped, "my_turn": my_turn}
        )

    def drain_start_current_requests(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        while True:
            try:
                items.append(self._start_current_requests.get_nowait())
            except queue.Empty:
                break
        return items

    def set_frame(self, jpeg: bytes) -> None:
        with self._lock:
            self._frame = jpeg
            self._data["frame_seq"] = int(self._data.get("frame_seq", 0)) + 1

    def frame(self) -> Optional[bytes]:
        with self._lock:
            return self._frame

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            data = dict(self._data)
            data["uptime_s"] = int(time.time() - self._started)
            data["log"] = list(self._logs)
            data["config"] = dict(self._config)
            data["paused"] = bool(data.get("paused"))
        return data


class StateLogHandler(logging.Handler):
    def __init__(self, state: BotState):
        super().__init__()
        self.state = state

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.state.add_log(self.format(record))
        except Exception:
            pass


def _origin_allowed(origin: Optional[str], host: str) -> bool:
    if not origin:
        return False
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    if parts.scheme in ("http", "https") and parts.netloc == host:
        return True
    if parts.scheme == "chrome-extension":
        return True
    if parts.scheme == "https" and parts.netloc in ("lichess.org", "www.lichess.org"):
        return True
    return False


def _same_origin(origin: Optional[str], host: str) -> bool:
    if not origin:
        return True
    return _origin_allowed(origin, host)


class _Handler(BaseHTTPRequestHandler):
    server_version = "LunarBot/1.0"
    protocol_version = "HTTP/1.0"

    def _cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        if origin and _origin_allowed(origin, host):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def _send(self, code: int, content_type: str, body: bytes) -> None:
        try:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._cors_headers()
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self) -> None:  # noqa: N802
        try:
            self.send_response(204)
            self._cors_headers()
            self.send_header("Content-Length", "0")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        state: BotState = self.server.state  # type: ignore[attr-defined]
        if path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", HTML.encode("utf-8"))
        elif path == "/api/state":
            body = json.dumps(state.snapshot(), ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
        elif path == "/api/frame.jpg":
            frame = state.frame()
            if frame is None:
                self._send(404, "text/plain; charset=utf-8", b"no frame")
            else:
                self._send(200, "image/jpeg", frame)
        elif path == "/health":
            self._send(200, "text/plain; charset=utf-8", b"ok")
        elif path == "/favicon.ico":
            self._send(204, "text/plain; charset=utf-8", b"")
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found")

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path != "/api/command":
            self._send(404, "text/plain; charset=utf-8", b"not found")
            return
        if not _same_origin(self.headers.get("Origin"), self.headers.get("Host", "")):
            self._send(403, "text/plain; charset=utf-8", b"forbidden origin")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > 4096:
            self._send(413, "text/plain; charset=utf-8", b"too large")
            return
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(400, "application/json; charset=utf-8", b'{"ok":false,"error":"bad json"}')
            return
        command = payload.get("command") if isinstance(payload, dict) else None
        state: BotState = self.server.state  # type: ignore[attr-defined]
        if command == "start-fen":
            fen = payload.get("fen") if isinstance(payload, dict) else None
            color = payload.get("color") if isinstance(payload, dict) else None
            flipped = bool(payload.get("flipped", False)) if isinstance(payload, dict) else False
            if (
                not isinstance(fen, str)
                or not fen.strip()
                or len(fen) > 500
                or color not in ("white", "black")
            ):
                self._send(
                    400,
                    "application/json; charset=utf-8",
                    b'{"ok":false,"error":"invalid fen or color"}',
                )
                return
            state.request_start(fen.strip(), color, flipped)
            self._send(200, "application/json; charset=utf-8", b'{"ok":true}')
            return
        if command == "start-current":
            color = payload.get("color") if isinstance(payload, dict) else None
            flipped = bool(payload.get("flipped", False)) if isinstance(payload, dict) else False
            my_turn = bool(payload.get("my_turn", True)) if isinstance(payload, dict) else True
            if color not in ("white", "black"):
                self._send(
                    400,
                    "application/json; charset=utf-8",
                    b'{"ok":false,"error":"invalid color"}',
                )
                return
            state.request_start_current(color, flipped, my_turn)
            self._send(200, "application/json; charset=utf-8", b'{"ok":true}')
            return
        if command == "set-elo":
            elo = payload.get("elo") if isinstance(payload, dict) else None
            if type(elo) is not int or not (1320 <= elo <= 3190):
                self._send(
                    400,
                    "application/json; charset=utf-8",
                    b'{"ok":false,"error":"invalid elo"}',
                )
                return
            state.command(f"set-elo:{elo}")
            self._send(200, "application/json; charset=utf-8", b'{"ok":true}')
            return
        if command not in COMMANDS:
            self._send(400, "application/json; charset=utf-8", b'{"ok":false,"error":"unknown command"}')
            return
        state.command(command)
        self._send(200, "application/json; charset=utf-8", b'{"ok":true}')

    def log_message(self, fmt: str, *args: Any) -> None:
        log.debug("web: " + fmt, *args)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class WebServer:
    def __init__(self, state: BotState, host: str = "127.0.0.1", port: int = 8765):
        self._state = state
        self._host = host
        self._port = port
        self._server: Optional[_Server] = None
        self._thread: Optional[threading.Thread] = None
        self._url: Optional[str] = None

    def start(self) -> Optional[str]:
        if self._port == 0:
            ports = [0]
        else:
            ports = list(range(self._port, min(65535, self._port + 10) + 1))
        for port in ports:
            try:
                server = _Server((self._host, port), _Handler)
            except OSError:
                continue
            server.state = self._state  # type: ignore[attr-defined]
            self._server = server
            actual = int(server.server_address[1])
            self._thread = threading.Thread(
                target=server.serve_forever, name="bot-webui", daemon=True
            )
            self._thread.start()
            display_host = "127.0.0.1" if self._host in ("0.0.0.0", "::") else self._host
            self._url = f"http://{display_host}:{actual}/"
            return self._url
        return None

    @property
    def url(self) -> Optional[str]:
        return self._url

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None


HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lunar · Lichess Bot</title>
<style>
:root{
  --bg:#07090c; --panel:#0f141b; --panel2:#131a23; --line:#222d3a;
  --text:#e8eff7; --muted:#8b99aa; --teal:#48e2c2; --amber:#f1b45c;
  --red:#ff6572; --blue:#6fa9ff; --mono:ui-monospace,SFMono-Regular,Consolas,monospace;
}
*{box-sizing:border-box}
html,body{margin:0}
body{
  min-height:100vh; background:
    radial-gradient(1000px 700px at 12% -10%, #10242c 0%, transparent 55%),
    radial-gradient(900px 600px at 110% 10%, #1a1530 0%, transparent 50%),
    var(--bg);
  color:var(--text); font-family:ui-sans-serif,system-ui,"Segoe UI",Roboto,Arial,sans-serif;
}
header{
  max-width:1500px; margin:0 auto; padding:26px 34px 18px;
  display:flex; align-items:center; justify-content:space-between; gap:16px;
}
.brand{display:flex; align-items:center; gap:12px}
.mark{
  width:42px; height:42px; border-radius:12px; display:grid; place-items:center;
  background:linear-gradient(145deg,#48e2c2,#1d8f84); color:#03110e;
  font-weight:800; font-size:22px; box-shadow:0 0 30px rgba(72,226,194,.18);
}
h1{font-size:18px; margin:0; letter-spacing:.22em; font-weight:700}
.brand p{margin:2px 0 0; color:var(--muted); font-size:12px; letter-spacing:.08em}
.pill{
  display:flex; align-items:center; gap:9px; padding:8px 14px; border-radius:999px;
  border:1px solid var(--line); background:#0a0f14; font-size:13px; color:var(--text);
  white-space:nowrap;
}
.pill .dot{width:9px; height:9px; border-radius:50%; background:var(--muted)}
.pill.playing .dot,.pill.thinking .dot{background:var(--teal); animation:pulse 1.5s infinite}
.pill.waiting .dot,.pill.starting .dot{background:var(--amber)}
.pill.paused .dot{background:var(--blue)}
.pill.stalled .dot,.pill.error .dot{background:var(--red); animation:pulse 1.2s infinite}
.pill.finished .dot,.pill.stopped .dot{background:var(--muted)}
@keyframes pulse{
  0%{box-shadow:0 0 0 0 rgba(72,226,194,.45)}
  70%{box-shadow:0 0 0 8px rgba(72,226,194,0)}
  100%{box-shadow:0 0 0 0 rgba(72,226,194,0)}
}
main{
  max-width:1500px; margin:0 auto; padding:0 34px 26px;
  display:grid; gap:16px;
  grid-template-columns:minmax(0,1.06fr) minmax(0,.94fr);
  grid-template-areas:"status preview" "details log" "config config";
}
@media (max-width:980px){
  main{grid-template-columns:1fr; grid-template-areas:"status" "preview" "details" "log" "config"}
  header{padding:20px}
  main{padding:0 20px 20px}
}
.card{
  background:linear-gradient(180deg,var(--panel2),var(--panel));
  border:1px solid var(--line); border-radius:16px; padding:18px;
  box-shadow:0 18px 50px rgba(0,0,0,.18);
}
.status{grid-area:status}
.preview{grid-area:preview}
.details{grid-area:details}
.log{grid-area:log}
.config{grid-area:config}
.label{
  font-size:10px; letter-spacing:.18em; text-transform:uppercase;
  color:var(--muted); margin-bottom:10px; font-weight:600;
}
.big{font-size:27px; line-height:1.15; font-weight:650; letter-spacing:-.02em}
.message{color:var(--muted); font-size:13px; margin-top:7px; min-height:19px}
.stats{display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:9px; margin-top:18px}
@media (max-width:620px){.stats{grid-template-columns:repeat(2,minmax(0,1fr))}}
.stat{background:#0a0e13; border:1px solid var(--line); border-radius:10px; padding:9px 10px}
.stat .k{font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:.08em}
.stat .v{font-size:14px; margin-top:4px; font-weight:600; font-variant-numeric:tabular-nums; overflow:hidden; text-overflow:ellipsis}
.buttons{display:flex; flex-wrap:wrap; gap:8px; margin-top:18px}
.startbox{margin-top:18px; padding-top:14px; border-top:1px solid var(--line)}
.startlabel{font-size:10px; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); font-weight:600; margin-bottom:8px}
#fenInput{
  width:100%; padding:9px 10px; border:1px solid var(--line); border-radius:8px;
  background:#0a0e13; color:var(--text); font-family:var(--mono); font-size:11px;
}
#fenInput::placeholder{color:#5b6878}
.startrow{display:flex; align-items:center; flex-wrap:wrap; gap:8px; margin-top:8px}
#fenColor,#eloSelect,#fenTurn{
  padding:8px 9px; border:1px solid var(--line); border-radius:8px;
  background:#0b1016; color:var(--text); font:inherit; font-size:12px;
}
.check{display:flex; align-items:center; gap:6px; color:var(--muted); font-size:12px; white-space:nowrap}
.check input{accent-color:var(--teal); width:14px; height:14px}
#fenStart{padding:8px 12px; font-size:12px}
button{
  border:1px solid var(--line); background:#0b1016; color:var(--text);
  padding:9px 13px; border-radius:9px; font:inherit; font-size:13px; cursor:pointer;
  transition:border-color .15s, background .15s, transform .05s;
}
button:hover{border-color:#35465a; background:#101722}
button:active{transform:translateY(1px)}
button.primary{border-color:#237d70; background:#0c2a26; color:#bff6ea}
button.primary:hover{background:#10342f}
button.danger{border-color:#5a2a30; background:#230e12; color:#ffc8ce}
button.danger:hover{background:#301218}
button:disabled{opacity:.45; cursor:not-allowed}
.frame{
  aspect-ratio:1/1; border-radius:12px; overflow:hidden; border:1px solid var(--line);
  background:#05070a; display:flex; align-items:center; justify-content:center;
}
.frame img{width:100%; height:100%; object-fit:contain; display:none}
.frame-hint{color:var(--muted); font-size:12px; text-align:center; padding:20px}
.fen{display:flex; gap:8px; align-items:center}
.fen code{
  flex:1; background:#0a0e13; border:1px solid var(--line); border-radius:8px;
  padding:9px 10px; font-family:var(--mono); font-size:11px; color:#bcd3c9;
  overflow:auto; white-space:nowrap;
}
.fen button{padding:7px 10px; font-size:12px}
#ascii{
  margin:12px 0 0; padding:12px; background:#0a0e13; border:1px solid var(--line);
  border-radius:8px; color:#cfe8dd; font-family:var(--mono); font-size:14px;
  line-height:1.35; overflow:auto;
}
#log{
  margin:0; height:246px; overflow:auto; padding:12px; background:#0a0e13;
  border:1px solid var(--line); border-radius:8px; color:#9fb3c4;
  font-family:var(--mono); font-size:11.5px; line-height:1.55; white-space:pre-wrap;
}
.kv{display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:9px}
.kv .item{background:#0a0e13; border:1px solid var(--line); border-radius:9px; padding:9px 10px}
.kv .item span{display:block; color:var(--muted); font-size:10px; text-transform:uppercase; letter-spacing:.08em}
.kv .item b{display:block; margin-top:4px; font-size:12.5px; font-weight:600; color:#d8e6f0; overflow:hidden; text-overflow:ellipsis}
footer{
  max-width:1500px; margin:0 auto; padding:0 34px 34px; color:var(--muted);
  font-size:11.5px; line-height:1.6;
}
@media (max-width:980px){footer{padding:0 20px 26px}}
</style>
</head>
<body>
<header>
  <div class="brand">
    <div class="mark">L</div>
    <div><h1>LUNAR</h1><p>LICHESS VISION BOT</p></div>
  </div>
  <div class="pill starting" id="pill"><span class="dot"></span><span id="pillText">Запуск…</span></div>
</header>

<main>
  <section class="card status">
    <div class="label">Статус</div>
    <div class="big" id="statusText">Запуск…</div>
    <div class="message" id="message">Подключение к боту…</div>
    <div class="stats">
      <div class="stat"><div class="k">Ход</div><div class="v" id="turn">—</div></div>
      <div class="stat"><div class="k">Цвет</div><div class="v" id="color">—</div></div>
      <div class="stat"><div class="k">Последний ход</div><div class="v" id="lastMove">—</div></div>
      <div class="stat"><div class="k">Оценка</div><div class="v" id="eval">—</div></div>
      <div class="stat"><div class="k">Уверенность</div><div class="v" id="confidence">—</div></div>
      <div class="stat"><div class="k">Ходы</div><div class="v" id="moves">0</div></div>
      <div class="stat"><div class="k">Игры</div><div class="v" id="games">0</div></div>
      <div class="stat"><div class="k">Аптайм</div><div class="v" id="uptime">—</div></div>
    </div>
    <div class="buttons">
      <button class="primary" id="pauseBtn" data-cmd="toggle-pause">Пауза</button>
      <button data-cmd="redetect">Пересканировать</button>
      <button data-cmd="calibrate" title="Поставьте стартовую позицию">Калибровать</button>
      <button data-cmd="check">Проверить зрение</button>
      <button class="danger" id="stopBtn" data-cmd="stop">Стоп</button>
    </div>
    <div class="startbox">
      <div class="startlabel">Сила Stockfish</div>
      <div class="startrow">
        <select id="eloSelect">
          <option value="1320">1320</option>
          <option value="1500">1500</option>
          <option value="1700">1700</option>
          <option value="1900">1900</option>
          <option value="2100">2100</option>
          <option value="2300">2300</option>
          <option value="2500">2500</option>
          <option value="2700">2700</option>
          <option value="2900">2900</option>
          <option value="3190">3190 — максимум</option>
        </select>
        <span class="check">UCI Elo, меняется на лету</span>
      </div>
    </div>
    <div class="startbox">
      <div class="startlabel">Старт с середины</div>
      <input id="fenInput" type="text" autocomplete="off" spellcheck="false"
             placeholder="Вставьте FEN из Lichess → Share → FEN">
      <div class="startrow">
        <select id="fenColor">
          <option value="white">белые</option>
          <option value="black">чёрные</option>
        </select>
        <select id="fenTurn">
          <option value="yes">Да, мой ход</option>
          <option value="no">Нет, ход соперника</option>
        </select>
        <label class="check"><input type="checkbox" id="fenFlipped"> доска перевёрнута</label>
        <button class="primary" id="fenStart">Старт по FEN</button>
      </div>
      <div class="startrow">
        <button class="primary" id="currentStart"
                title="Бот прочитает доску и использует выбранные цвет и очередь хода">Старт с текущей позиции</button>
      </div>
    </div>
  </section>

  <section class="card preview">
    <div class="label">Доска</div>
    <div class="frame">
      <img id="frame" alt="превью доски">
      <div class="frame-hint" id="frameHint">Кадр появится, когда бот найдёт доску.</div>
    </div>
  </section>

  <section class="card details">
    <div class="label">Позиция</div>
    <div class="fen"><code id="fen">—</code><button id="copyFen">Копировать FEN</button></div>
    <pre id="ascii">—</pre>
  </section>

  <section class="card log">
    <div class="label">Журнал</div>
    <pre id="log"></pre>
  </section>

  <section class="card config">
    <div class="label">Конфигурация</div>
    <div class="kv" id="config"></div>
  </section>
</main>

<footer>
  Панель локальная. Вкладка Lichess должна быть активной, а доска — не перекрыта.
  Клавиши: <b>F8</b> пауза · <b>F7</b> пересканировать · <b>F9</b> стоп.
</footer>

<script>
const STATUS = {
  starting: "Запуск…",
  waiting: "Ожидание стартовой позиции",
  playing: "Играет",
  thinking: "Думает Stockfish…",
  finished: "Партия окончена",
  stalled: "Нужна помощь",
  stopped: "Остановлен",
  error: "Ошибка"
};
const CFG_LABELS = {
  engine: "Stockfish",
  move_time_s: "Время хода, с",
  skill_level: "Skill Level",
  uci_elo: "Elo",
  monitor: "Монитор",
  board_rect: "Область доски",
  templates: "Шаблоны",
  hotkeys: "Клавиши"
};
const ui = { seq: -1, logText: null, configText: null };

function $(id) { return document.getElementById(id); }
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function colorName(value) {
  return value === "white" ? "белые" : value === "black" ? "чёрные" : "—";
}
function uptime(seconds) {
  if (seconds == null) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return h ? `${h}ч ${m}м` : m ? `${m}м ${s}с` : `${s}с`;
}
function setPill(status, paused) {
  const pill = $("pill");
  const key = paused ? "paused" : (status || "error");
  pill.className = "pill " + key;
  $("pillText").textContent = paused ? "Пауза" : (STATUS[status] || "Ошибка");
}
function render(s) {
  setPill(s.status, s.paused);
  $("statusText").textContent = s.paused ? "Пауза" : (STATUS[s.status] || s.status || "—");
  $("message").textContent = s.message || "";
  $("turn").textContent = s.turn ? (s.turn === s.our_color ? "ваш ход" : "ход соперника") : "—";
  $("color").textContent = colorName(s.our_color);
  $("lastMove").textContent = s.last_move || "—";
  $("eval").textContent = s.eval || "—";
  $("confidence").textContent = s.confidence == null ? "—" : (s.confidence * 100).toFixed(1) + "%";
  $("moves").textContent = s.moves ?? 0;
  $("games").textContent = s.games ?? 0;
  $("uptime").textContent = uptime(s.uptime_s);
  $("pauseBtn").textContent = s.paused ? "Продолжить" : "Пауза";
  $("fen").textContent = s.fen || "—";
  $("ascii").textContent = s.ascii || "—";
  const elo = s.config && s.config.uci_elo != null ? String(s.config.uci_elo) : "3190";
  if ($("eloSelect").value !== elo) $("eloSelect").value = elo;

  if (s.frame_seq && s.frame_seq !== ui.seq) {
    ui.seq = s.frame_seq;
    const img = $("frame");
    img.src = "/api/frame.jpg?v=" + s.frame_seq;
    img.style.display = "block";
    $("frameHint").style.display = "none";
  }

  const logText = (s.log || []).join("\n");
  if (logText !== ui.logText) {
    const log = $("log");
    const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    log.textContent = logText;
    if (nearBottom) log.scrollTop = log.scrollHeight;
    ui.logText = logText;
  }

  const config = Object.assign({}, s.config || {});
  config.engine = s.engine || config.engine;
  config.templates = s.templates || config.templates;
  const configText = JSON.stringify(config);
  if (configText !== ui.configText) {
    $("config").innerHTML = Object.entries(CFG_LABELS)
      .filter(([key]) => config[key] !== undefined && config[key] !== null && config[key] !== "")
      .map(([key, label]) =>
        `<div class="item"><span>${label}</span><b>${escapeHtml(config[key])}</b></div>`)
      .join("");
    ui.configText = configText;
  }
}
async function poll() {
  try {
    const response = await fetch("/api/state", { cache: "no-store" });
    if (!response.ok) throw new Error("http " + response.status);
    render(await response.json());
  } catch (error) {
    setPill("error", false);
    $("statusText").textContent = "Нет связи с ботом";
    $("message").textContent = "Процесс остановлен или панель недоступна.";
  }
}
async function command(name, extra = {}) {
  if (name === "stop" && !confirm("Остановить бота?")) return;
  try {
    await fetch("/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: name, ...extra })
    });
    setTimeout(poll, 120);
  } catch (error) {
    $("message").textContent = "Команда не отправлена.";
  }
}
document.querySelectorAll("[data-cmd]").forEach(button => {
  button.addEventListener("click", () => command(button.dataset.cmd));
});
$("fenStart").addEventListener("click", () => {
  const fen = $("fenInput").value.trim();
  if (!fen) {
    $("message").textContent = "Вставьте FEN из Lichess.";
    return;
  }
  command("start-fen", {
    fen,
    color: $("fenColor").value,
    flipped: $("fenFlipped").checked
  });
});
$("currentStart").addEventListener("click", () => {
  command("start-current", {
    color: $("fenColor").value,
    flipped: $("fenFlipped").checked,
    my_turn: $("fenTurn").value === "yes"
  });
});
$("eloSelect").addEventListener("change", () => {
  command("set-elo", { elo: Number($("eloSelect").value) });
});
$("copyFen").addEventListener("click", async () => {
  const text = $("fen").textContent;
  if (!text || text === "—") return;
  try { await navigator.clipboard.writeText(text); $("copyFen").textContent = "Скопировано"; }
  catch (_) { $("copyFen").textContent = "Ошибка"; }
  setTimeout(() => { $("copyFen").textContent = "Копировать FEN"; }, 1200);
});
$("frame").addEventListener("error", () => {
  $("frame").style.display = "none";
  $("frameHint").style.display = "block";
});
poll();
setInterval(poll, 600);
</script>
</body>
</html>
"""
