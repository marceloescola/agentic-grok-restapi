const TOOL_SERVER_URL = "http://localhost:19997";

browser.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === "run_tool") {
    run_tool(msg.tool, msg.args)
      .then(sendResponse)
      .catch((err) => sendResponse({ error: String(err) }));
    return true;
  }
  if (msg.action === "list_tools") {
    list_tools()
      .then(sendResponse)
      .catch((err) => sendResponse({ error: String(err) }));
    return true;
  }
});

async function run_tool(tool, args) {
  const res = await fetch(`${TOOL_SERVER_URL}/tools/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tool, args }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Tool server ${res.status}: ${text}`);
  }
  return res.json();
}

async function list_tools() {
  const res = await fetch(`${TOOL_SERVER_URL}/tools/list`);
  if (!res.ok) throw new Error(`Tool server ${res.status}`);
  return res.json();
}
