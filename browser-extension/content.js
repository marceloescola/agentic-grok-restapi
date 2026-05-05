(function () {
  "use strict";

  /* ------------------------------------------------------------------ */
  /*  Config                                                             */
  /* ------------------------------------------------------------------ */
  const RESPONSE_SELECTORS = [
    '[data-message-author-role="assistant"]',
    '[data-testid="assistant-message"]',
    ".message-assistant",
    ".assistant-message",
    '[class*="assistant-message"]',
    '[class*="AssistantMessage"]',
    '[class*="response-text"]',
    '[class*="message-content"]',
    '[class*="grok-response"]',
    ".grok-message",
    ".prose",
    'article[class*="message"]',
  ];

  const INPUT_SELECTORS = [
    'div[contenteditable="true"]',
    '[data-testid="text-input"]',
    '[role="textbox"]',
    "textarea",
  ];

  const SEND_SELECTORS = [
    'button[aria-label="Send"]',
    '[data-testid="send-button"]',
    '[data-testid="send-button"] button',
    'button[type="submit"]',
    'button svg[class*="send"]',
    'button svg[class*="arrow"]',
  ];

  /* ------------------------------------------------------------------ */
  /*  State                                                              */
  /* ------------------------------------------------------------------ */
  let processedCalls = new Set();
  let enabled = true;
  let attachFiles = true;
  let debugLog = [];
  const MAX_LOG = 200;

  // Load settings from storage
  browser.storage.local.get("attachFiles").then((r) => {
    if (r.attachFiles !== undefined) attachFiles = r.attachFiles;
  });

  /* ------------------------------------------------------------------ */
  /*  Debug helpers                                                      */
  /* ------------------------------------------------------------------ */
  function debug(msg, data) {
    const entry = { ts: Date.now(), msg, data };
    debugLog.push(entry);
    if (debugLog.length > MAX_LOG) debugLog.shift();
    console.log("[GrokToolBridge]", msg, data || "");
  }

  /* ------------------------------------------------------------------ */
  /*  Helpers                                                            */
  /* ------------------------------------------------------------------ */
  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  /* ------------------------------------------------------------------ */
  /*  DOM helpers                                                        */
  /* ------------------------------------------------------------------ */
  function getLatestAssistantText() {
    for (const sel of RESPONSE_SELECTORS) {
      const els = document.querySelectorAll(sel);
      if (els.length > 0) {
        const t = els[els.length - 1].innerText;
        if (t && t.trim()) return t;
      }
    }
    return "";
  }

  function getTextAllAssistants() {
    const texts = [];
    for (const sel of RESPONSE_SELECTORS) {
      const els = document.querySelectorAll(sel);
      els.forEach((el) => {
        const t = el.innerText;
        if (t && t.trim()) texts.push(t);
      });
      if (texts.length) break;
    }
    return texts;
  }

  /* ------------------------------------------------------------------ */
  /*  TOOL_CALL parsing                                                  */
  /* ------------------------------------------------------------------ */
  function findToolCalls(text) {
    const calls = [];
    let searchFrom = 0;
    while (true) {
      const idx = text.indexOf("TOOL_CALL", searchFrom);
      if (idx === -1) break;

      const jsonStart = text.indexOf("{", idx);
      if (jsonStart === -1) {
        searchFrom = idx + 9;
        continue;
      }

      let depth = 0;
      let jsonEnd = -1;
      for (let i = jsonStart; i < text.length; i++) {
        if (text[i] === "{") depth++;
        else if (text[i] === "}") {
          depth--;
          if (depth === 0) {
            jsonEnd = i;
            break;
          }
        }
      }

      if (jsonEnd === -1) {
        searchFrom = idx + 9;
        continue;
      }

      const jsonStr = text.slice(jsonStart, jsonEnd + 1);
      try {
        const parsed = JSON.parse(jsonStr);
        if (parsed && parsed.name) {
          const hash = jsonStr;
          if (!processedCalls.has(hash)) {
            processedCalls.add(hash);
            calls.push({ name: parsed.name, args: parsed.arguments || {} });
          }
        }
      } catch (_) {}

      searchFrom = jsonEnd + 1;
    }
    return calls;
  }

  /* ------------------------------------------------------------------ */
  /*  Tool execution via background                                      */
  /* ------------------------------------------------------------------ */
  async function executeToolCall(toolCall) {
    debug("Executing tool", toolCall);
    try {
      const resp = await browser.runtime.sendMessage({
        action: "run_tool",
        tool: toolCall.name,
        args: toolCall.args,
      });
      if (resp && resp.error) {
        debug("Tool error", resp.error);
        return { toolName: toolCall.name, result: `Tool error: ${resp.error}` };
      }
      const result = resp && resp.result !== undefined ? resp.result : "(no result)";
      debug("Tool result", `${result.substring(0, 200)}... (${result.length} chars)`);
      return { toolName: toolCall.name, result };
    } catch (err) {
      debug("Tool execution failed", err.message);
      return { toolName: toolCall.name, result: `Tool call failed: ${err.message}` };
    }
  }

  /* ------------------------------------------------------------------ */
  /*  Inject result into chat input                                      */
  /* ------------------------------------------------------------------ */

  /** Upload result as a file via hidden input[type=file], then send short message. */
  async function sendResultAsFile(toolName, result) {
    const file = new File([result], `tool_result_${toolName}.txt`, { type: "text/plain" });

    // Find or reveal the file input
    let fileInput = document.querySelector('input[type="file"]');
    if (!fileInput) {
      // Click attach button to make the input appear
      for (const sel of ['button[aria-label*="Attach"]', 'button[aria-label*="Upload"]', '[data-testid*="attach"] button']) {
        const btn = document.querySelector(sel);
        if (btn) { btn.click(); await sleep(300); break; }
      }
      fileInput = document.querySelector('input[type="file"]');
    }

    if (!fileInput) {
      debug("No file input found on page");
      return false;
    }

    // Set files via DataTransfer (standard browser API — works in content scripts)
    const dt = new DataTransfer();
    dt.items.add(file);
    fileInput.files = dt.files;
    fileInput.dispatchEvent(new Event("change", { bubbles: true }));
    fileInput.dispatchEvent(new Event("input", { bubbles: true }));

    // Wait for grok's UI to register the file
    await sleep(600);

    injectText(`Tool result (${toolName}) — see attached file`);
    return true;
  }

  /** Decide whether to attach as file or inject as text, then send. */
  async function injectResult(toolName, result, useFiles) {
    if (useFiles) {
      const sent = await sendResultAsFile(toolName, result);
      if (sent) return;
    }
    // Fallback: text injection (current behavior)
    const msg = `Here's the tool result (${toolName}): ${result}`;
    injectText(msg);
  }
  function findInput() {
    for (const sel of INPUT_SELECTORS) {
      const el = document.querySelector(sel);
      if (el) return el;
    }
    return null;
  }

  function clickSend() {
    for (const sel of SEND_SELECTORS) {
      const btn = document.querySelector(sel);
      if (btn) {
        btn.click();
        return true;
      }
    }
    return false;
  }

  function injectText(text) {
    const el = findInput();
    if (!el) {
      debug("Input element not found");
      return false;
    }

    el.focus();
    el.click();
    if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {
      el.value = "";
    } else {
      el.textContent = "";
    }

    let inserted = false;
    try {
      document.execCommand("selectAll", false, null);
      document.execCommand("delete", false, null);
    } catch (_) {}

    try {
      inserted = document.execCommand("insertText", false, text) || inserted;
    } catch (_) {}

    if (!inserted) {
      if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {
        el.value = text;
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      } else {
        el.textContent = text;
        el.dispatchEvent(
          new InputEvent("input", { bubbles: true, data: text, inputType: "insertText" })
        );
      }
    }

    setTimeout(() => {
      if (!clickSend()) {
        el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true }));
        el.dispatchEvent(new KeyboardEvent("keyup", { key: "Enter", code: "Enter", bubbles: true }));
      }
    }, 150);

    return true;
  }

  /* ------------------------------------------------------------------ */
  /*  Main loop: detect and handle                                       */
  /* ------------------------------------------------------------------ */
  let processing = false;

  async function scanAndExecute() {
    if (!enabled || processing) return;
    processing = true;

    try {
      const texts = getTextAllAssistants();
      for (const text of texts) {
        const calls = findToolCalls(text);
        for (const call of calls) {
          const { toolName, result } = await executeToolCall(call);
          debug("Injecting result", `${result.substring(0, 120)}...`);
          await injectResult(toolName, result, attachFiles);
        }
      }
    } finally {
      processing = false;
    }
  }

  /* ------------------------------------------------------------------ */
  /*  MutationObserver                                                   */
  /* ------------------------------------------------------------------ */
  let debounceTimer = null;

  function onDomChange() {
    if (!enabled) return;
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(scanAndExecute, 500);
  }

  const observer = new MutationObserver(onDomChange);
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    characterData: true,
  });

  scanAndExecute();

  /* ------------------------------------------------------------------ */
  /*  Expose for popup                                                   */
  /* ------------------------------------------------------------------ */
  window.__GROK_TOOL_BRIDGE__ = {
    get enabled() {
      return enabled;
    },
    set enabled(v) {
      enabled = v;
      debug(v ? "Enabled" : "Disabled");
    },
    get attachFiles() {
      return attachFiles;
    },
    set attachFiles(v) {
      attachFiles = !!v;
      browser.storage.local.set({ attachFiles });
      debug(attachFiles ? "File attachment ON" : "File attachment OFF");
    },
    get debugLog() {
      return debugLog;
    },
    get processedCallsCount() {
      return processedCalls.size;
    },
    resetProcessed() {
      processedCalls.clear();
      debug("Processed calls reset");
    },
    scanNow() {
      scanAndExecute();
    },
  };

  /* ------------------------------------------------------------------ */
  /*  Popup message handler                                              */
  /* ------------------------------------------------------------------ */
  browser.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    const bridge = window.__GROK_TOOL_BRIDGE__;
    if (!bridge) return;

    switch (msg.action) {
      case "get_state":
        sendResponse({
          enabled: bridge.enabled,
          attachFiles: bridge.attachFiles,
          processedCallsCount: bridge.processedCallsCount,
          debugLog: bridge.debugLog.slice(-50),
        });
        break;
      case "toggle":
        bridge.enabled = !bridge.enabled;
        sendResponse({ enabled: bridge.enabled });
        break;
      case "toggle_files":
        bridge.attachFiles = !bridge.attachFiles;
        sendResponse({ attachFiles: bridge.attachFiles });
        break;
      case "reset":
        bridge.resetProcessed();
        sendResponse({ ok: true });
        break;
      case "scan":
        bridge.scanNow();
        sendResponse({ ok: true });
        break;
    }
  });

  debug("Content script loaded");
})();
