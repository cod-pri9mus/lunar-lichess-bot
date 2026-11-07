# Lichess Vision Bot

A fully automatic Lichess player that reads the board from the screen with computer vision, feeds the position to Stockfish, and plays the move with human-like mouse input. No Lichess API token and no bot flag — it drives the normal web client on a normal account. A small optional Chrome/Edge extension adds a live status panel directly on `lichess.org`.

```
screen ──▶ board detection ──▶ 64 cells ──▶ piece classifier ──▶ placement
                                                                   │
                                                            legal-move tracker
                                                                   │
                                                              chess.Board
                                                                   │
                                                               Stockfish
                                                                   │
             human-like drag ◀── screen coordinates ◀── UCI move ◀──┘
                     │
              re-read board ──▶ confirm / retry
```

## What it does

- Finds the chessboard anywhere on the screen and perspective-warps it to a square.
- Classifies all 64 squares from background-normalised piece templates.
- Tracks the game legally: side to move, castling rights, en passant, promotions, takebacks.
- Uses Stockfish (UCI) for the move.
- Drags the piece with a randomised Bézier path and confirms the move by reading the board again.
- Auto-calibrates its piece templates from the starting position, so any piece set and board theme works.
- Continues across games: when the starting position appears again, it resets and plays the next game.
- Runs dry, prints the board and suggested move, and never touches the mouse (`--dry-run`).
- Serves a local browser dashboard and, with the optional extension, shows a floating **LUNAR** panel on Lichess itself before the game starts.

Verified against Lichess's default board render at 0.93–0.97 classifier confidence with all 32 pieces recognised.

## Быстрый старт (RU)

1. Зависимости уже стоят в `.venv`. Если начинаете с нуля:
   ```powershell
   cd C:\Users\user\Documents\chess1
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
2. Запустите бота:
   ```powershell
   .\.venv\Scripts\python.exe run.py
   ```
   Локальная панель: **http://127.0.0.1:8765/** (откроется в браузере).
3. Чтобы панель была **на самом lichess.org** (видна ещё в меню, до партии):
   - `chrome://extensions` (или `edge://extensions`);
   - включите **Режим разработчика**;
   - **Загрузить распакованное** → выберите папку `browser_extension`;
   - обновите вкладку Lichess.
   В правом нижнем углу появится плавающая панель **LUNAR**.
4. Откройте партию. Бот ждёт стартовую позицию и играет за цвет внизу.
   Если бот запущен посреди партии — передайте `--fen` и `--color`.

Вкладка Lichess должна быть активной, а доска — не перекрыта (панель можно
свернуть в маленькую пилюлю). `F8` — пауза, `F7` — пересканировать, `F9` — стоп.

## Requirements

- Windows 10/11 (screen capture and DPI handling are Windows-first; the vision code itself is portable).
- Python 3.10+ (3.13 tested).
- Stockfish (`stockfish.exe` is included in this project, Stockfish 17.1).
- A browser with the Lichess game visible and the board unobstructed.
- Chrome or Edge, only if you want the floating panel on `lichess.org`.

## Install

```powershell
cd C:\Users\user\Documents\chess1

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

1. Open your Lichess game in a browser. Make the whole board visible. Do not cover it with windows, arrows, or drawing tools.
2. Start the bot **before** the first move of the game:

```powershell
.\.venv\Scripts\python.exe run.py
```

On the first frame it finds the board, captures templates from the starting position, works out which colour is at the bottom, and starts playing for that side.

If the bot is started mid-game, it waits for a standard starting position. To join immediately, pass the current FEN and your colour:

```powershell
.\.venv\Scripts\python.exe run.py --fen "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3" --color white
```

`--fen` must include the full position (side to move, castling, en passant). Copy it from Lichess's **Share → FEN**.

## Браузерная панель

Бот поднимает локальный HTTP-сервер (по умолчанию `http://127.0.0.1:8765/`) и
открывает его в браузере. Панель показывает:

- статус: ожидание стартовой позиции, играет, думает, пауза, нужна помощь;
- живой превью доски с распознанными фигурами и уверенностью;
- FEN, ASCII-доску, журнал;
- ход, цвет, последний ход, оценку, число ходов и партий;
- кнопки **Пауза/Продолжить**, **Пересканировать**, **Калибровать**,
  **Проверить зрение**, **Стоп**.

 Флаги:

| Флаг | Действие |
|---|---|
| `--no-web` | не запускать локальную панель |
| `--web-host` | адрес (по умолчанию `127.0.0.1`) |
| `--web-port` | порт (по умолчанию `8765`) |
| `--no-browser` | не открывать панель в браузере |

**Панель на lichess.org.** Папка `browser_extension/` — расширение Chrome/Edge
(Manifest V3). Оно показывает плавающую панель **LUNAR** в правом нижнем углу
на всех страницах Lichess, включая меню до партии. Статус берётся из локального
API бота; кнопки «Пауза» и «Скан» отправляют команды. Полная панель открывается
ссылкой «Панель».

Установка: `chrome://extensions` → Режим разработчика → Загрузить
распакованное → `browser_extension`. Если порт изменён, откройте «Параметры
расширения» и укажите тот же порт.

Расширение — тонкий клиент: сам бот должен быть запущен. Локальная панель и
расширение работают только на этой машине; сервер слушает `127.0.0.1`.

## First-run checks

Read the board without playing:

```powershell
.\.venv\Scripts\python.exe run.py --check-vision
```

It prints the detected orientation, confidence, ASCII board, every square's confidence, and writes an annotated frame to `debug/`. The green quad is the detected board.

Suggest one move without touching the mouse:

```powershell
.\.venv\Scripts\python.exe run.py --dry-run --once
```

Calibrate manually (the usual case is auto-calibration, but this helps with a non-default piece set or a mid-game start):

```powershell
# board must show the standard starting position
.\.venv\Scripts\python.exe run.py --calibrate
```

This stores the current piece set/theme in `templates/`. The bot auto-calibrates at the start of every new game anyway, so manual calibration is mainly for starting mid-game with a custom set.

## Controls

| Key | Action |
|---|---|
| `F8` | pause / resume |
| `F7` | re-detect the board and resync the tracker |
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
| `engine.uci_elo` | null | strength limit 1320–3190 (sets `UCI_LimitStrength`) |
| `engine.move_time_s` | 0.6 | thinking time per move |
| `engine.depth` | null | optional depth cap (time still applies) |
| `vision.monitor` | 1 | mss monitor index: 1 = primary, 2 = second, … |
| `vision.board_rect` | null | `[x, y, width, height]` in physical screen pixels; skips auto-detection |
| `vision.ignore_window_title` | `Lichess Bot` | exclude this window (the local panel) from board detection |
| `vision.orientation` | auto | colour at the bottom: `auto`, `white`, `black` |
| `vision.color` | auto | side the bot plays; defaults to the bottom colour |
| `vision.capture_fps` | 15 | screen sampling rate |
| `vision.stable_reads` | 2 | identical frames required before acting |
| `vision.confidence_threshold` | 0.60 | minimum piece score; lower means more risk |
| `vision.cell_crop_pct` | 6.0 | border crop, removes Lichess coordinate labels |
| `vision.board_inset_pct` | 1.0 | shrink detected board to avoid its border |
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
| `input.promotion_mode` | auto | `auto` (vision dialog handling), `auto_queen` (Lichess must auto-queen), `dialog` |
| `input.focus_window` | null | substring of the browser window title; focuses it at startup |
| `logging.file` | `logs/bot.log` | rotating log file |

### Recommended settings

- **Rapid / classical:** defaults are fine. `move_time_s: 0.6` gives a strong game with fast replies.
- **Blitz:** `move_time_s: 0.25`, `capture_fps: 15`, `stable_reads: 2`, `post_move_wait_s: 0.15`. Vision and engine latency still make bullet borderline; 3+0 and slower are safer.
- **Weaker play:** `skill_level: 8` or `uci_elo: 1800`.
- **Non-default piece set:** the automatic start-position calibration handles it. For a mid-game start, run `--calibrate` once on a start position in that set.
- **Board not found:** set `vision.board_rect`. Use `--check-vision` to save the annotated frame first; the green quad shows the detected area.

## How it works

### 1. Board detection

`find_board` looks for a large square region using two independent methods:

- **Contours + checkerboard score.** Candidate quadrilaterals are warped and split into 8×8 cells. Square colours are sampled from each cell's border; a real board has high contrast between adjacent cells and low contrast between cells two apart. The score is `adjacent_contrast / (two_apart_contrast + 10)`.
- **Saturation fallback.** The board is usually the largest saturated square on the page. A saturation mask, morphological close, and bounding box give a candidate; the checkerboard score validates it. This is what makes the Lichess light theme detectable even when the board's outer edge is low-contrast.

The winner is warped to 800×800 with a perspective transform. Screen coordinates for mouse input come from the inverse transform.

### 2. Piece recognition

Each cell is cropped (6% border), its background is estimated from the border ring, and a background-subtracted mask isolates the piece. The mask bounding box is resized to 64×64. A template library stores the mask, RGB, and masked mean luminance for each piece.

Classification combines:

- **Mask IoU** (70%) — the piece silhouette.
- **Masked mean value** (30%) — separates white and black pieces with the same silhouette. The value is the minimum RGB channel, which is not fooled by red/yellow/green UI overlays.
- **Red suppression** before masking neutralises the red check glow; the checked king's square is also treated as authoritative by the tracker, so a tinted king can never stall the game.

Templates come from one of:

1. `templates/` (manual or auto calibration).
2. The bundled cburnett set (`lichess_vision_bot/assets/cburnett`).
3. Auto-capture at the standard starting position: the 8×8 occupancy pattern identifies the start, the brighter back rank identifies White, and the 12 piece types are captured from their known squares. This adapts to any piece set and theme.

### 3. Legal game tracking

A board image contains the piece placement but not the side to move, castling rights, en passant, or move history. The bot therefore starts from the initial position (or a supplied FEN) and maintains a real `chess.Board`.

On every stable frame it compares the observed placement to the tracked board. The opponent's move is the unique legal move whose resulting placement matches. This handles castling, en passant, and promotions without OCR. A placement that is not reachable by any legal move is treated as a vision error; the bot waits instead of guessing. Takebacks are detected by rewinding through the move history.

### 4. Move execution and confirmation

Stockfish returns a UCI move. The bot maps the from/to squares through the board orientation and the inverse perspective transform, then drags with a curved path, random offsets, and short pauses. Promotion moves trigger an optional dialog picker that scans the four promotion-choice cells and clicks the requested piece.

After the drag, the move is pushed onto the tracker and the bot waits for the visual board to match the expected placement. If it does not, the move is retried up to `max_move_retries` times. If the opponent premoves, the reply is recognized immediately and applied.

## Diagnostics

```powershell
# inspect a live screen
.\.venv\Scripts\python.exe run.py --check-vision

# inspect a saved screenshot
.\.venv\Scripts\python.exe run.py --check-vision --image debug\page.png

# calibrate from a saved screenshot
.\.venv\Scripts\python.exe run.py --calibrate --image debug\start.png

# dry-run the whole bot on a saved screenshot (start position, no FEN needed)
.\.venv\Scripts\python.exe run.py --image debug\start.png --once

# dry-run a mid-game screenshot
.\.venv\Scripts\python.exe run.py --image debug\mid.png ^
  --fen "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3" ^
  --color white --once

# engine sanity check
.\.venv\Scripts\python.exe run.py --check-engine
```

Debug output:

- `logs/bot.log` — moves, confirmations, warnings.
- `debug/*.png` — annotated frames (green board quad, per-square piece and score).
- `templates/` — captured piece templates.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `board not found` | Use `--check-vision`; the board may be covered or off-screen. Set `--rect x,y,w,h`. |
| Board detected at the wrong place | Set `vision.board_rect`. Coordinates are physical pixels; check the green quad in the debug image. |
| Half-screen / panel next to Lichess | Keep the panel in its own window; the bot excludes it via `vision.ignore_window_title` (default `Lichess Bot`) so its own board preview is not mistaken for the game. |
| Correct board, low confidence | Run `--calibrate` on the start position; check that the piece set/theme is visible and unobstructed. |
| Wrong side / bot never moves | Set `--color white` or `--color black`. If the board is manually flipped, also set `--orientation`. |
| Moves do not register | Focus the browser (`input.focus_window` or click it once before starting). Check the annotated board; try `input.mode: "click"`; raise `post_move_wait_s`. |
| Promotion fails | Enable Lichess **Always promote to queen** and use `promotion_mode: "auto_queen"`, or keep `auto` and check the debug frame. |
| Losing on time | Lower `engine.move_time_s`; the bot does not read clocks. |
| Window moved mid-game | Press `F7` to re-detect and resync. |
| Bot stalls after a misread | Press `F7`; if that fails, restart with the current FEN. |

## Limits

- Standard chess is the target. Chess960 works with `--fen` and a calibrated template library.
- The board must be visible and unobstructed. Analysis arrows, drawing tools, or overlapping windows break the read.
- Rapid and classical are comfortable. Blitz is possible with reduced timings. Bullet/ultrabullet is not practical because of screen sampling and engine latency.
- The bot does not read clocks; it uses a fixed budget per move.
- Draw offers, takebacks, rematch buttons, and result dialogs are not clicked. The bot keeps playing moves; use the Lichess UI for those.
- The machine is under mouse control while the bot runs.
- The browser must stay on the same monitor and position; `F7` recovers after a move.

## Project layout

```
chess1/
├── run.py                         launcher
├── config.example.json            documented defaults
├── config.json                    local config (created, gitignored)
├── requirements.txt
├── requirements-dev.txt
├── start_bot.bat                  double-click / Task Scheduler launcher
├── stockfish.exe                  Stockfish 17.1
├── browser_extension/             Chrome/Edge panel for lichess.org
│   ├── manifest.json
│   ├── background.js              localhost API client
│   ├── content.js                 injects the floating LUNAR widget
│   ├── content.css
│   ├── options.html / options.js  panel port
│   └── icons/
├── lichess_vision_bot/
│   ├── bot.py                     main state machine
│   ├── vision.py                  frame -> placement
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
└── tests/                         vision, tracker, web and config tests
```

## Development

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

The vision tests render synthetic boards from the bundled piece assets and do not need a screen or Stockfish. The engine check is separate:

```powershell
.\.venv\Scripts\python.exe run.py --check-engine
```

Regenerate the bundled templates (needs `resvg-py`):

```powershell
.\.venv\Scripts\python.exe tools\generate_cburnett.py
```
