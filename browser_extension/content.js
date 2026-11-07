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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
