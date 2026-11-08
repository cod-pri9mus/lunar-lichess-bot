const DEFAULT_PORT = 8765;

async function apiBase() {
  const stored = await new Promise((resolve) => {
    try {
      chrome.storage.local.get({ apiPort: DEFAULT_PORT }, (value) => {
        if (chrome.runtime.lastError) {
          resolve({ apiPort: DEFAULT_PORT });
        } else {
          resolve(value || { apiPort: DEFAULT_PORT });
        }
      });
    } catch (error) {
      resolve({ apiPort: DEFAULT_PORT });
    }
  });
  const port = Number(stored.apiPort) || DEFAULT_PORT;
  return `http://127.0.0.1:${port}`;
}

async function getState() {
  const response = await fetch(`${await apiBase()}/api/state`, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return await response.json();
}

async function sendCommand(command) {
  const response = await fetch(`${await apiBase()}/api/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command })
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return await response.json();
}

async function postDom(payload) {
  const response = await fetch(`${await apiBase()}/api/dom`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return await response.json();
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    try {
      if (message?.type === "lunar-state") {
        sendResponse(await getState());
      } else if (message?.type === "lunar-command") {
        sendResponse(await sendCommand(message.command));
      } else if (message?.type === "lunar-dom") {
        sendResponse(await postDom(message.payload));
      } else {
        sendResponse({ error: "unknown message" });
      }
    } catch (error) {
      sendResponse({ error: String(error?.message || error) });
    }
  })();
  return true;
});
