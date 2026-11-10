(() => {
  const WIDGET_ID = "lunar-bot-widget";

  const STATUS = {
    starting: "запуск",
    waiting: "ожидание",
    playing: "играет",
    thinking: "думает",
    finished: "партия окончена",
    stalled: "нужна помощь",
    stopped: "остановлен",
    error: "ошибка"
  };

  function ask(type, extra = {}) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage({ type, ...extra }, (response) => {
          if (chrome.runtime.lastError) {
            resolve({ error: chrome.runtime.lastError.message });
          } else {
            resolve(response || { error: "нет ответа" });
          }
        });
      } catch (error) {
        resolve({ error: String(error) });
      }
    });
  }

  function colorName(value) {
    return value === "white" ? "белые" : value === "black" ? "чёрные" : "—";
  }

  const PIECE_TYPES = {
    pawn: "p", knight: "n", bishop: "b", rook: "r", queen: "q", king: "k"
  };

  function squareFromTransform(style, blackBottom, cellW, cellH) {
    const text = String(style || "");
    let col = null;
    let row = null;
    const pct = /translate\(\s*(-?[\d.]+)%\s*,\s*(-?[\d.]+)%\s*\)/.exec(text);
    if (pct) {
      col = Math.round(Number(pct[1]) / 100);
      row = Math.round(Number(pct[2]) / 100);
    } else {
      const px = /translate\(\s*(-?[\d.]+)px(?:\s*,\s*(-?[\d.]+)px)?\s*\)/.exec(text);
      if (px && cellW && cellH) {
        col = Math.round(Number(px[1]) / cellW);
        row = Math.round((px[2] ? Number(px[2]) : 0) / cellH);
      }
    }
    if (col === null || row === null || col < 0 || col > 7 || row < 0 || row > 7) return null;
    const file = blackBottom ? 7 - col : col;
    const fenRow = blackBottom ? 7 - row : row;
    return { file, fenRow, square: String.fromCharCode(97 + file) + (8 - fenRow) };
  }

  function parseUserColor(bottom) {
    const bottomClock = document.querySelector(".rclock-bottom, .clock-bottom");
    if (bottomClock) {
      if (bottomClock.classList.contains("rclock-white") || bottomClock.classList.contains("white")) return "white";
      if (bottomClock.classList.contains("rclock-black") || bottomClock.classList.contains("black")) return "black";
    }
    return bottom;
  }

  function parseTurn(bottom, boardEl) {
    const app = document.querySelector(".round__app, .round, .main-board");
    if (app) {
      const direct = app.getAttribute("data-turn") || app.dataset.turn;
      if (direct === "white" || direct === "black") return direct;
      if (direct === "w") return "white";
      if (direct === "b") return "black";
    }
    const active = document.querySelector(".clock-player-turn, .rclock-turn, .rclock-running");
    if (!active) return null;
    if (active.closest(".rclock-bottom, .clock-bottom, .bottom")) return bottom;
    if (active.closest(".rclock-top, .clock-top, .top")) return bottom === "white" ? "black" : "white";
    const activeRect = active.getBoundingClientRect();
    const boardRect = boardEl.getBoundingClientRect();
    return activeRect.top < boardRect.top + boardRect.height / 2
      ? (bottom === "white" ? "black" : "white")
      : bottom;
  }

  function measureBoard(boardEl) {
    const rect = boardEl.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const chromeX = Math.max(0, (window.outerWidth - window.innerWidth) / 2);
    const chromeY = Math.max(0, window.outerHeight - window.innerHeight);
    return {
      x: Math.round((window.screenX + chromeX + rect.left) * dpr),
      y: Math.round((window.screenY + chromeY + rect.top) * dpr),
      width: Math.round(rect.width * dpr),
      height: Math.round(rect.height * dpr)
    };
  }

  function parseBoard() {
    if (!document.querySelector(".round__app, .round")) return null;
    const boardEl = document.querySelector("cg-board");
    if (!boardEl) return null;
    const wrap = boardEl.closest(".cg-wrap") || document.querySelector(".cg-wrap");
    const bottom = wrap && wrap.classList.contains("orientation-black") ? "black" : "white";
    const blackBottom = bottom === "black";
    const grid = Array.from({ length: 8 }, () => Array(8).fill(null));
    const scope = boardEl.shadowRoot || boardEl;
    const boardRect = boardEl.getBoundingClientRect();
    const cellW = boardRect.width / 8;
    const cellH = boardRect.height / 8;
    const pieceEls = Array.from(scope.querySelectorAll("piece"));
    for (const el of pieceEls) {
      const color = el.classList.contains("white") ? "white"
        : el.classList.contains("black") ? "black" : null;
      const type = Object.keys(PIECE_TYPES).find(name => el.classList.contains(name));
      if (!color || !type) continue;
      const square = squareFromTransform(el.style.transform, blackBottom, cellW, cellH);
      if (!square) continue;
      grid[square.fenRow][square.file] = color === "white"
        ? PIECE_TYPES[type].toUpperCase()
        : PIECE_TYPES[type];
    }
    const placement = grid.map(row => {
      let out = "";
      let empty = 0;
      for (const piece of row) {
        if (piece) {
          if (empty) { out += empty; empty = 0; }
          out += piece;
        } else {
          empty++;
        }
      }
      return out + (empty ? empty : "");
    }).join("/");
    const turn = parseTurn(bottom, boardEl);
    const lastSquares = Array.from(scope.querySelectorAll("square.last-move"))
      .map(el => squareFromTransform(el.style.transform, blackBottom, cellW, cellH))
      .filter(Boolean)
      .map(item => item.square);
    return {
      fen: `${placement} ${turn === "black" ? "b" : "w"} - - 0 1`,
      turn,
      orientation: bottom,
      color: parseUserColor(bottom),
      rect: measureBoard(boardEl),
      last_move: lastSquares.length === 2 ? lastSquares.join("") : null
    };
  }

  function startDomFeed() {
    let lastKey = "";
    let lastPostAt = 0;
    let posting = false;
    async function post() {
      if (posting) return;
      const payload = parseBoard();
      if (!payload) return;
      const key = JSON.stringify(payload);
      const now = Date.now();
      if (key === lastKey && now - lastPostAt < 2000) return;
      posting = true;
      try {
        const response = await ask("lunar-dom", { payload });
        if (response && response.ok) {
          lastKey = key;
          lastPostAt = now;
        }
      } finally {
        posting = false;
      }
    }
    window.setInterval(post, 350);
    window.addEventListener("resize", post);
    window.addEventListener("scroll", post, true);
    window.setTimeout(post, 600);
  }

  function boot() {
    if (document.getElementById(WIDGET_ID) || !document.documentElement) return;

    const host = document.createElement("div");
    host.id = WIDGET_ID;
    host.innerHTML = `
      <div class="lunar-card">
        <button class="lunar-head" type="button" id="lunar-toggle" title="Свернуть / развернуть">
          <span class="lunar-brand"><span class="lunar-mark">L</span><span>LUNAR</span></span>
          <span class="lunar-right">
            <span class="lunar-dot"></span>
            <span class="lunar-pill" id="lunar-pill">офлайн</span>
            <span class="lunar-chev" id="lunar-chev">−</span>
          </span>
        </button>
        <div class="lunar-body">
          <div class="lunar-status" id="lunar-status">Бот не запущен</div>
          <div class="lunar-message" id="lunar-message">Запустите run.py</div>
          <div class="lunar-grid">
            <div><span>Ход</span><b id="lunar-turn">—</b></div>
            <div><span>Цвет</span><b id="lunar-color">—</b></div>
            <div><span>Шанс</span><b id="lunar-win">—</b></div>
            <div><span>Перевес</span><b id="lunar-adv">—</b></div>
            <div><span>Ходы</span><b id="lunar-moves">0</b></div>
            <div><span>Игры</span><b id="lunar-games">0</b></div>
          </div>
          <div class="lunar-actions">
            <button type="button" id="lunar-pause">Пауза</button>
            <button type="button" id="lunar-scan">Скан</button>
            <a href="http://127.0.0.1:8765/" target="_blank" rel="noreferrer" id="lunar-open">Панель</a>
          </div>
        </div>
      </div>`;
    document.documentElement.appendChild(host);

    const $ = (id) => host.querySelector("#" + id);
    const toggle = $("lunar-toggle");
    const pause = $("lunar-pause");
    const scan = $("lunar-scan");
    const open = $("lunar-open");
    let collapsed = false;

    toggle.addEventListener("click", () => {
      collapsed = !collapsed;
      host.classList.toggle("lunar-collapsed", collapsed);
      $("lunar-chev").textContent = collapsed ? "+" : "−";
    });

    async function send(command) {
      await ask("lunar-command", { command });
      window.setTimeout(poll, 140);
    }

    pause.addEventListener("click", () => send("toggle-pause"));
    scan.addEventListener("click", () => send("redetect"));

    function offline() {
      host.dataset.state = "offline";
      $("lunar-pill").textContent = "офлайн";
      $("lunar-status").textContent = "Бот не запущен";
      $("lunar-message").textContent = "Запустите run.py или проверьте порт в настройках расширения.";
      $("lunar-turn").textContent = "—";
      $("lunar-color").textContent = "—";
      $("lunar-win").textContent = "—";
      $("lunar-adv").textContent = "—";
      $("lunar-moves").textContent = "0";
      $("lunar-games").textContent = "0";
      pause.disabled = true;
      scan.disabled = true;
    }

    function render(state) {
      const paused = Boolean(state.paused);
      const status = state.status || "error";
      host.dataset.state = paused ? "paused" : status;
      $("lunar-pill").textContent = paused ? "пауза" : (STATUS[status] || status);
      $("lunar-status").textContent = paused ? "Пауза" : (STATUS[status] || status);
      $("lunar-message").textContent = state.message || "";
      $("lunar-message").title = state.message || "";
      $("lunar-turn").textContent = state.turn
        ? (state.turn === state.our_color ? "ваш ход" : "ход соперника")
        : "—";
      $("lunar-color").textContent = colorName(state.our_color);
      $("lunar-win").textContent = state.win_prob == null
        ? "—"
        : `${Math.round(state.win_prob)}%`;
      $("lunar-adv").textContent = state.advantage || "—";
      $("lunar-moves").textContent = state.moves ?? 0;
      $("lunar-games").textContent = state.games ?? 0;
      pause.textContent = paused ? "Продолжить" : "Пауза";
      pause.disabled = false;
      scan.disabled = false;
      if (state.panel_url) open.href = state.panel_url;
    }

    async function poll() {
      const state = await ask("lunar-state");
      if (!state || state.error) {
        offline();
        return;
      }
      render(state);
    }

    poll();
    window.setInterval(poll, 800);

    window.setInterval(() => {
      if (!document.getElementById(WIDGET_ID)) boot();
    }, 4000);
  }

  function start() {
    boot();
    startDomFeed();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
