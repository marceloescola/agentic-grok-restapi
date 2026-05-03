(function () {
  "use strict";

  const toggleBtn = document.getElementById("toggleBtn");
  const scanBtn = document.getElementById("scanBtn");
  const resetBtn = document.getElementById("resetBtn");
  const callCount = document.getElementById("callCount");
  const toolStatus = document.getElementById("toolStatus");
  const logContainer = document.getElementById("logContainer");

  /* ------------------------------------------------------------------ */
  /*  Get content script bridge reference                                */
  /* ------------------------------------------------------------------ */
  async function bridge() {
    const tabs = await browser.tabs.query({ url: "https://grok.com/*" });
    if (!tabs.length) return null;
    // We use executeScript to read the exposed window.__GROK_TOOL_BRIDGE__
    // Actually, content script can't be directly accessed from popup in MV2.
    // Use sendMessage to content script via tabs.sendMessage
    return tabs[0];
  }

  async function execOnContent(action, payload) {
    const tabs = await browser.tabs.query({ url: "https://grok.com/*" });
    if (!tabs.length) return null;
    try {
      const resp = await browser.tabs.sendMessage(tabs[0].id, { action, payload });
      return resp;
    } catch (_) {
      return null;
    }
  }

  /* ------------------------------------------------------------------ */
  /*  State                                                              */
  /* ------------------------------------------------------------------ */
  let logCache = [];

  function renderLog(entries) {
    logContainer.innerHTML = "";
    if (!entries || entries.length === 0) {
      logContainer.innerHTML = '<div class="empty">Waiting for tool calls...</div>';
      return;
    }
    for (const e of entries) {
      const div = document.createElement("div");
      div.className = "log-entry";
      if (e.msg === "Executing tool") div.classList.add("executing");
      else if (e.msg.startsWith("Tool result") || e.msg.startsWith("Injecting")) div.classList.add("result");
      else if (e.msg.includes("error") || e.msg.includes("fail")) div.classList.add("error");

      const time = document.createElement("span");
      time.className = "time";
      time.textContent = new Date(e.ts).toLocaleTimeString();

      const msg = document.createElement("span");
      msg.className = "msg";
      msg.textContent = e.msg;

      div.appendChild(time);
      div.appendChild(msg);

      if (e.data !== undefined) {
        const data = document.createElement("div");
        data.className = "data";
        data.textContent =
          typeof e.data === "string" ? e.data : JSON.stringify(e.data, null, 2);
        div.appendChild(data);
      }

      logContainer.appendChild(div);
    }
    logContainer.scrollTop = logContainer.scrollHeight;
  }

  async function refreshUI() {
    const resp = await execOnContent("get_state");
    if (!resp) {
      toggleBtn.textContent = "No page";
      toggleBtn.className = "inactive";
      return;
    }
    toggleBtn.textContent = resp.enabled ? "Active" : "Paused";
    toggleBtn.className = resp.enabled ? "active" : "inactive";
    callCount.textContent = `${resp.processedCallsCount} calls`;
    logCache = resp.debugLog || [];
    renderLog(logCache);
  }

  /* ------------------------------------------------------------------ */
  /*  Tool server health                                                 */
  /* ------------------------------------------------------------------ */
  async function checkToolServer() {
    try {
      const res = await fetch("http://localhost:19997/health");
      if (res.ok) {
        const data = await res.json();
        toolStatus.textContent = `tools: ${(data.tools || []).join(", ")}`;
        toolStatus.style.color = "#27ae60";
      } else {
        toolStatus.textContent = "tool server: error";
        toolStatus.style.color = "#e74c3c";
      }
    } catch (_) {
      toolStatus.textContent = "tool server: unreachable";
      toolStatus.style.color = "#e74c3c";
    }
  }

  /* ------------------------------------------------------------------ */
  /*  Events                                                             */
  /* ------------------------------------------------------------------ */
  toggleBtn.addEventListener("click", async () => {
    const resp = await execOnContent("toggle");
    if (resp) refreshUI();
  });

  scanBtn.addEventListener("click", async () => {
    await execOnContent("scan");
    setTimeout(refreshUI, 1000);
  });

  resetBtn.addEventListener("click", async () => {
    await execOnContent("reset");
    refreshUI();
  });

  /* ------------------------------------------------------------------ */
  /*  Init                                                               */
  /* ------------------------------------------------------------------ */
  async function init() {
    await checkToolServer();
    await refreshUI();
    setInterval(refreshUI, 2000);
    setInterval(checkToolServer, 10000);
  }

  init();
})();
