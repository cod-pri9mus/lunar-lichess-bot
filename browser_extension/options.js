const DEFAULT_PORT = 8765;

function portValue() {
  const value = Number(document.getElementById("port").value);
  return Number.isInteger(value) && value >= 1 && value <= 65535 ? value : DEFAULT_PORT;
}

async function probe(port) {
  const status = document.getElementById("status");
  status.className = "";
  status.textContent = "Проверка…";
  try {
    const response = await fetch(`http://127.0.0.1:${port}/health`, { cache: "no-store" });
    if (response.ok) {
      status.className = "ok";
      status.textContent = `Подключено: http://127.0.0.1:${port}/`;
      return true;
    }
    status.className = "bad";
    status.textContent = `Панель ответила HTTP ${response.status}`;
    return false;
  } catch (_error) {
    status.className = "bad";
    status.textContent = "Нет связи. Запустите run.py и проверьте порт.";
    return false;
  }
}

async function load() {
  const stored = await chrome.storage.local.get({ apiPort: DEFAULT_PORT });
  const port = Number(stored.apiPort) || DEFAULT_PORT;
  document.getElementById("port").value = port;
  await probe(port);
}

document.getElementById("save").addEventListener("click", async () => {
  const port = portValue();
  await chrome.storage.local.set({ apiPort: port });
  await probe(port);
});

document.getElementById("open").addEventListener("click", () => {
  const port = portValue();
  window.open(`http://127.0.0.1:${port}/`, "_blank", "noopener");
});

load();
