# Lunar — Lichess Bot

A fully automatic Lichess player. The main mode reads the position from the Lichess DOM through the bundled browser extension: the extension sends the FEN, the side to move, the board rectangle, and the last move; the bot tracks the game with `python-chess`, asks Stockfish, and plays the move with human-like mouse input. No Lichess API token and no bot flag — it drives the normal web client on a normal account.

The screen-vision reader is kept as a fallback (`vision.source: "screen"`) and is documented at the bottom of this file.

## How it works (DOM mode)

```
Lichess tab (DOM)
  cg-board: pieces, orientation, clock, last move, board rectangle
        │  extension: POST /api/dom
        ▼
 FEN + rect ──▶ chess.Board tracker ──▶ Stockfish ──▶ UCI move
        │                                                │
        └── panel simulation ◀── state ◀─────────────────┘
                                    │
                       human-like drag (screen rect)
```

- The extension reads the `cg-board` pieces (classes + `translate` positions), the board orientation, the active clock, the last move, and the board rectangle in physical screen pixels.
- It posts `{fen, turn, orientation, color, rect, last_move}` to `http://127.0.0.1:8765/api/dom`.
- The bot adopts the current position on the first payload, including a mid-game start. It does not need a starting position or a screenshot.
- The local panel draws the board from the FEN as a simulation. The Lichess board may be covered or off-screen; it is not scanned.
- The tracker handles castling, en passant, promotions, takebacks, and a new game from the starting position.
- Stockfish returns a UCI move; the bot maps it through the board rectangle to screen coordinates and drags the piece. The cursor stays on the target square after the move.
- The panel has a **move-time selector** (0.1 / 0.3 / 0.6 / 1.0 s) and the **LUNAR** widget shows the win chance and the point advantage.
- The extension is a thin client: the bot must be running.

## Быстрый старт (RU)

1. Зависимости уже стоят в `.venv`. Если начинаете с нуля:
   ```powershell
   cd <project folder>
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
2. Запустите бота:
   ```powershell
   .\.venv\Scripts\python.exe run.py
   ```
   Локальная панель: **http://127.0.0.1:8765/** (откроется в браузере).
3. Загрузите расширение — оно присылает боту позицию из HTML:
   - **Chrome / Edge:** `chrome://extensions` (или `edge://extensions`) → включите **Режим разработчика** → **Загрузить распакованное** → папка `browser_extension`;
   - **Firefox:** `about:debugging#/runtime/this-firefox` → **Load Temporary Add-on…** → `browser_extension/firefox/manifest.json`;
   - обновите вкладку Lichess. Временное Firefox-расширение живёт до перезапуска Firefox; после перезапуска загрузите его снова.
   В правом нижнем углу появится плавающая панель **LUNAR**.
4. Откройте партию. Расширение присылает FEN и координаты доски, бот стартует автоматически с текущей позиции. Панель рисует симуляцию; экран не сканируется.

Вкладка Lichess должна быть открыта, расширение — загружено. Доска может быть перекрыта: в DOM-режиме экран не сканируется. `F8` — пауза, `F7` — пересканировать, `F9` — стоп.

## Requirements

- Windows 10/11 (the vision fallback is Windows-first; the DOM mode itself is portable).
- Python 3.10+ (3.13 tested).
- Stockfish (`stockfish.exe` is included in this project, Stockfish 17.1).
- A Chromium browser (Chrome/Edge) or Firefox with the extension loaded, and the Lichess game tab open.
- For the vision fallback only: the board visible, unobstructed, on the same monitor.

## Install

```powershell
cd <project folder>

# the virtual environment is already here; if starting fresh:
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`config.json` is already created from `config.example.json`. If it is missing:

```powershell
copy config.example.json config.json
```

Check the engine:

```powershell
.\.venv\Scripts\python.exe run.py --check-engine
```

Expected: `engine: Stockfish 17.1` and `engine self-test passed (mate in one found)`.

## Quick start

1. Open your Lichess game in a browser and load the extension.
2. Start the bot:

```powershell
.\.venv\Scripts\python.exe run.py
```

The first DOM payload starts the game immediately. If the bot is started mid-game, it adopts the current position and the side at the bottom of the board.

The FEN form in the panel also works:

```powershell
.\.venv\Scripts\python.exe run.py --fen "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3" --color white
```

`--fen` must include the full position (side to move, castling, en passant). Copy it from Lichess's **Share → FEN**.

## Browser panel

The bot serves a local HTTP server (default `http://127.0.0.1:8765/`) and opens it in a browser. The panel shows:

- status: waiting, playing, thinking, paused, stalled;
- the board simulated from the FEN;
- FEN, ASCII board, log;
- move, colour, last move, evaluation, win chance, advantage, number of moves and games;
- move-time selector **0.1 / 0.3 / 0.6 / 1.0 s**;
- buttons **Пауза/Продолжить**, **Пересканировать**, **Калибровать**, **Проверить зрение**, **Стоп**.

Flags:

| Flag | Action |
|---|---|
| `--no-web` | do not start the local panel |
| `--web-host` | bind address (default `127.0.0.1`) |
| `--web-port` | port (default `8765`) |
| `--no-browser` | do not open the panel in a browser |

**The LUNAR widget on lichess.org.** The `browser_extension/` folder is a Manifest V3 extension. It shows a floating **LUNAR** panel in the bottom-right corner on all Lichess pages, including the menu before a game. The widget shows status, turn, colour, **win chance**, **point advantage**, moves, and games; the buttons **Пауза** and **Скан** send commands; **Панель** opens the full dashboard.

Install: `chrome://extensions` → Developer mode → Load unpacked → `browser_extension`. For Firefox use `about:debugging#/runtime/this-firefox` → Load Temporary Add-on → `browser_extension/firefox/manifest.json`.

The extension is a thin client: the bot must be running. The local server listens on `127.0.0.1` only.

## Controls

| Key | Action |
|---|---|
| `F8` | pause / resume |
| `F7` | re-detect and resync the tracker |
| `F9` | stop |
| `Ctrl+C` (terminal) | stop |
| mouse to top-left corner | PyAutoGUI failsafe; aborts input |

The bot controls the mouse. Do not use the mouse while it is moving; press `F8` first if you need to interact.

## Configuration

`config.json` (all keys optional; see `config.example.json`):

| Key | Default | Meaning |
|---|---|---|
| `engine.path` | `stockfish.exe` | Stockfish executable; relative to the config file |
| `engine.threads` | 2 | Stockfish threads |
| `engine.hash_mb` | 256 | transposition table MB |
| `engine.skill_level` | 20 | Stockfish Skill Level 0–20 |
| `engine.uci_elo` | null | strength limit 1320–3190 |
| `engine.move_time_s` | 0.6 | thinking time per move; the panel selector changes it live |
| `engine.depth` | null | optional depth cap (time still applies) |
| `vision.source` | `dom` | `dom` = Lichess DOM via the extension; `screen` = the old computer vision |
| `vision.monitor` | 1 | mss monitor index (vision fallback) |
| `vision.board_rect` | null | `[x, y, width, height]` in physical screen pixels (vision fallback) |
| `vision.ignore_window_title` | `Lichess Bot` | exclude this window from board detection |
| `vision.orientation` | auto | colour at the bottom: `auto`, `white`, `black` |
| `vision.color` | auto | side the bot plays; defaults to the bottom colour |
| `vision.capture_fps` | 15 | screen sampling rate (vision fallback) |
| `vision.stable_reads` | 2 | identical frames required before acting |
| `vision.confidence_threshold` | 0.60 | minimum piece score |
| `vision.cell_crop_pct` | 6.0 | border crop, removes coordinate labels |
| `vision.board_inset_pct` | 1.0 | shrink the board to avoid its border |
| `vision.redetect_interval_s` | 15 | re-scan while idle |
| `vision.templates_dir` | `templates` | calibrated piece templates |
| `vision.auto_save_templates` | true | save auto-calibration at game start |
| `vision.debug_dir` | `debug` | annotated frames |
| `input.enabled` | true | false = dry run |
| `input.mode` | drag | `drag` or `click` |
| `input.human_like` | true | curved path, pauses, jitter |
| `input.move_duration_s` | [0.08, 0.16] | drag duration range |
| `input.jitter_pct` | 9.0 | cursor offset within a square |
| `input.post_move_wait_s` | 0.20 | settle time after a move |
| `input.confirm_timeout_s` | 2.0 | time allowed for the move to appear |
| `input.max_move_retries` | 3 | retries when a move does not register |
| `input.promotion_mode` | auto | `auto`, `auto_queen`, `dialog` |
| `input.focus_window` | null | substring of the browser window title |
| `logging.file` | `logs/bot.log` | rotating log file |

### Recommended settings

- **Rapid / classical:** defaults are fine.
- **Blitz:** `move_time_s: 0.3`, `post_move_wait_s: 0.15`. Bullet is borderline.
- **Weaker play:** `skill_level: 8` or `uci_elo: 1800`.
- **Vision fallback:** see the vision section below.

## Machine vision (fallback)

Set `vision.source: "screen"` to use the original screen reader. It captures the screen, finds the board, classifies the 64 squares from templates, tracks the game, and confirms every move by re-reading the board. The rest of the bot — engine, tracker, mouse, panel, hotkeys — is shared.

To read the board without playing:

```powershell
.\.venv\Scripts\python.exe run.py --check-vision
```

It prints the orientation, confidence, ASCII board, every square's confidence, and writes an annotated frame to `debug/`. The green quad is the detected board.

Suggest one move without touching the mouse:

```powershell
.\.venv\Scripts\python.exe run.py --dry-run --once
```

Calibrate manually (the usual case is auto-calibration; this helps with a non-default piece set or a mid-game start):

```powershell
# board must show the standard starting position
.\.venv\Scripts\python.exe run.py --calibrate
```

This stores the current piece set/theme in `templates/`. The bot auto-calibrates at the start of every new game anyway.

### Board detection

`find_board` looks for a large square region using two independent methods:

- **Contours + checkerboard score.** Candidate quadrilaterals are warped and split into 8×8 cells. Square colours are sampled from each cell's border; a real board has high contrast between adjacent cells and low contrast between cells two apart. The score is `adjacent_contrast / (two_apart_contrast + 10)`.
- **Saturation fallback.** The board is usually the largest saturated square on the page. A saturation mask, morphological close, and bounding box give a candidate; the checkerboard score validates it.

The winner is warped to 800×800 with a perspective transform. Screen coordinates for mouse input come from the inverse transform.

### Piece recognition

Each cell is cropped (6% border), its background is estimated from the border ring, and a background-subtracted mask isolates the piece. The mask bounding box is resized to 64×64. A template library stores the mask, RGB, and masked mean luminance for each piece.

Classification combines:

- **Mask IoU** (70%) — the piece silhouette.
- **Masked mean value** (30%) — separates white and black pieces with the same silhouette. The value is the minimum RGB channel, which is not fooled by red/yellow/green UI overlays.
- **Red suppression** before masking neutralises the red check glow; the checked king's square is also treated as authoritative by the tracker.

Templates come from `templates/`, the bundled cburnett set, or auto-capture at the standard starting position.

### Legal game tracking and move execution

The bot maintains a real `chess.Board` from the initial position or the supplied FEN. On every stable frame it compares the observed placement to the tracked board. The opponent's move is the unique legal move whose resulting placement matches. Castling, en passant, and promotions are handled without OCR. A placement that is not reachable by any legal move is treated as a vision error. Takebacks are detected by rewinding through the move history.

Stockfish returns a UCI move. The bot maps the from/to squares through the board orientation and the inverse perspective transform, then drags with a curved path, random offsets, and short pauses. Promotion moves trigger the promotion picker. After the drag, the move is pushed onto the tracker and the bot waits for the visual board to match. If it does not, the move is retried.

### Vision diagnostics

```powershell
# inspect a live screen
.\.venv\Scripts\python.exe run.py --check-vision

# inspect a saved screenshot
.\.venv\Scripts\python.exe run.py --check-vision --image debug\page.png

# calibrate from a saved screenshot
.\.venv\Scripts\python.exe run.py --calibrate --image debug\start.png

# dry-run on a saved screenshot
.\.venv\Scripts\python.exe run.py --image debug\start.png --once

# engine sanity check
.\.venv\Scripts\python.exe run.py --check-engine
```

### Vision troubleshooting

| Symptom | Fix |
|---|---|
| `board not found` | Use `--check-vision`; the board may be covered or off-screen. Set `vision.board_rect`. |
| Board detected at the wrong place | Set `vision.board_rect`; check the green quad in the debug image. |
| Correct board, low confidence | Run `--calibrate` on the start position. |
| Wrong side / bot never moves | Set `--color white` or `--color black`; set `--orientation` if the board is flipped. |
| Moves do not register | Focus the browser; try `input.mode: "click"`; raise `post_move_wait_s`. |
| Promotion fails | Enable Lichess **Always promote to queen** and use `promotion_mode: "auto_queen"`. |
| Bot stalls after a misread | Press `F7`; if that fails, restart with the current FEN. |

## Troubleshooting (DOM mode)

| Symptom | Fix |
|---|---|
| Panel says «Ожидание позиции из расширения» | Load/reload the extension; open the Lichess game tab. |
| Extension is gone after a Firefox restart | The Firefox add-on is temporary: load `browser_extension/firefox/manifest.json` again. |
| `DOM feed is stale` | The Lichess tab must stay open. Reload the extensions and the tab. |
| Bot plays the wrong side | The side is taken from the bottom clock/board; use the FEN/current-position form to override. |
| Move time does not change | Pick a value in the panel's move-time selector; it is applied live. |

## Limits

- Standard chess is the target. Chess960 works with `--fen` and a calibrated template library.
- The DOM mode needs the Lichess tab and the extension, but the board can be covered.
- The vision fallback needs the board visible and unobstructed; analysis arrows, drawing tools, or overlapping windows break the read.
- Rapid and classical are comfortable. Blitz is possible with reduced timings; bullet is not practical.
- The bot does not read clocks; it uses a fixed budget per move.
- Draw offers, takebacks, rematch buttons, and result dialogs are not clicked.
- The machine is under mouse control while the bot runs.

## Project layout

```
lunar-lichess-bot/
├── run.py                         launcher
├── config.example.json            documented defaults
├── config.json                    local config (created, gitignored)
├── requirements.txt
├── requirements-dev.txt
├── start_bot.bat                  double-click / Task Scheduler launcher
├── stockfish.exe                  Stockfish 17.1
├── browser_extension/             Chromium extension + LUNAR widget
│   ├── manifest.json
│   ├── background.js              localhost API client
│   ├── content.js                 DOM parser + floating widget
│   ├── content.css
│   ├── options.html / options.js  panel port
│   ├── icons/
│   └── firefox/                   Firefox build
├── lichess_vision_bot/
│   ├── bot.py                     main state machine
│   ├── vision.py                  screen -> placement (fallback)
│   ├── pieces.py                  signatures, templates, classifier
│   ├── board_detect.py            board location + perspective mapping
│   ├── capture.py                 mss / static-image capture
│   ├── tracker.py                 legal move tracking
│   ├── engine.py                  Stockfish UCI wrapper
│   ├── mouse.py                   human-like drag / click
│   ├── hotkeys.py                 F7 / F8 / F9
│   ├── diagnostics.py             --check-vision / --calibrate
│   ├── webui.py                   local dashboard + HTTP API
│   ├── config.py                  config loading + validation
│   ├── coords.py                  square <-> screen grid
│   ├── imgio.py                   Unicode-safe image I/O
│   ├── cli.py                     command line
│   └── assets/cburnett/           bundled piece templates
├── templates/                     calibrated templates (generated)
├── logs/                          bot.log (generated)
├── debug/                         annotated frames (generated)
├── tools/generate_cburnett.py     regenerate bundled templates
└── tests/                         vision, DOM, tracker, web and config tests
```

## Development

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

The tests render synthetic boards from the bundled piece assets and do not need a screen or Stockfish. The engine check is separate:

```powershell
.\.venv\Scripts\python.exe run.py --check-engine
```

Regenerate the bundled templates (needs `resvg-py`):

```powershell
.\.venv\Scripts\python.exe tools\generate_cburnett.py
```
