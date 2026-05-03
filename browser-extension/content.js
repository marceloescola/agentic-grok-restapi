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
  let debugLog = [];
  const MAX_LOG = 200;

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
        return `Tool error (${toolCall.name}): ${resp.error}`;
      }
      const result = resp && resp.result !== undefined ? resp.result : "(no result)";
      debug("Tool result", result);
      return `Here's the tool result (${toolCall.name}): ${result}`;
    } catch (err) {
      debug("Tool execution failed", err.message);
      return `Tool call failed (${toolCall.name}): ${err.message}`;
    }
  }

  /* ------------------------------------------------------------------ */
  /*  Inject result into chat input                                      */
  /* ------------------------------------------------------------------ */
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
          const resultMsg = await executeToolCall(call);
          debug("Injecting result", resultMsg);
          injectText(resultMsg);
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
          processedCallsCount: bridge.processedCallsCount,
          debugLog: bridge.debugLog.slice(-50),
        });
        break;
      case "toggle":
        bridge.enabled = !bridge.enabled;
        sendResponse({ enabled: bridge.enabled });
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
