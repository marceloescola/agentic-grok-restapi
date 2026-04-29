Good. Based on your answers, here's the enhanced implementation plan.
---
Enhanced Plan: Tool Calling for Grok Bridge
Problems with the original plan
Issue	Detail
Broken response extraction	Plan sends full history as prompt; engine's _extract() returns all text after marker, re-feeding prior responses
No conversation state	Plan invents conversation_id but bridge has one shared browser page, no session tracking
Unnecessary dual-server	Plan proposes port 19999 wrapper calling back to 19998 — circular, wasteful
Unsafe eval()	Calculator uses raw eval() — injectable
No error recovery	Malformed tool_calls, tool timeouts, tool server down — all unhandled
Enhanced architecture
┌──────────────┐    POST /agent     ┌───────────────────┐    POST /tools/run    ┌──────────────────┐
│  HTTP Client │ ─────────────────→ │  Grok Bridge       │ ────────────────────→ │  Tool Server      │
│              │                    │  (port 19998)      │ ←──────────────────── │  (port 19997)     │
└──────────────┘                    │                    │     {"result": "4"}   │                   │
                                    │  Playwright ↔      │                       │  Calculator       │
                                    │  grok.com          │                       │  Web Search       │
                                    └───────────────────┘                       │  (later: CodeRAG) │
                                                                                 └──────────────────┘
Flow: Bridge opens new conversation on grok.com → sends system prompt (tool format instruction) → sends user prompt → enters ReAct loop on the same grok.com page → each tool_call gets forwarded to Tool Server → tool result sent back to Grok as new message → loop until final answer or max steps.
File changes
New files
File	Purpose
tools/__init__.py	Package init
tools/base.py	ToolDef dataclass + Tool protocol
tools/registry.py	Shared tool registry (imported by both bridge & server)
tools/calculator.py	Safe CalculatorTool using ast.literal_eval + operator whitelist
tools/web_search.py	WebSearchTool using duckduckgo-search
tools/tool_server.py	Standalone FastAPI app exposing POST /tools/run + GET /tools/list (port 19997)
linux/agent.py	GrokAgent — orchestrates the ReAct loop, calls bridge engine + tool server
Modified files
File	Change
linux/grok_engine_l.py	Add send_message() method (type + submit without extraction); add start_conversation_with_system_prompt(); add tool_call parser utilities
linux/grok_bridge_l.py	Add POST /agent endpoint; add --tool-server-url CLI arg; integrate GrokAgent
pyproject.toml	Add duckduckgo-search, httpx deps
Implementation phases
Phase 1: Tool server + shared registry (tools/)
tools/
├── __init__.py
├── base.py          # ToolDef dataclass, Tool protocol
├── registry.py      # TOOL_REGISTRY: Dict[str, ToolDef]
├── calculator.py    # CalculatorTool — safe math evaluation
├── web_search.py    # WebSearchTool — DuckDuckGo
└── tool_server.py   # FastAPI app on port 19997
- ToolDef(name, description, parameters: dict[str,str]) 
- Tool protocol: async def run(self, **kwargs) -> str
- Registry is shared: bridge reads it for system prompt generation; server reads it for tool dispatch
- Calculator uses ast.parse + safe node visitor (only +, -, *, /, **, math functions, numbers)
- Tool server: POST /tools/run {"tool":"calculator", "args":{"expression":"2+2"}} → {"result":"4"}
Phase 2: Engine changes (linux/grok_engine_l.py)
Add to GrokPlaywrightEngine:
async def send_message(self, prompt: str) -> None:
    """Type prompt into grok.com and click Send. Don't wait for response."""
    input_sel = await self.ensure_grok()
    await self._type_and_send(prompt, input_sel)
async def wait_for_response(self, timeout: int = 120) -> Dict[str, Any]:
    """Wait for grok.com to respond to the last sent message."""
    # Existing polling logic from chat(), but returns raw response
async def start_tool_session(self, system_prompt: str) -> None:
    """New conversation + send system prompt as first message."""
    await self.new_conversation()
    await self.send_message(system_prompt)
Also add standalone parser utilities (not class methods):
TOOL_CALL_RE = re.compile(r'```tool_call\s*(.*?)\s*```', re.DOTALL | re.IGNORECASE)
def extract_tool_call(text: str) -> Optional[dict]:
    """Parse ```tool_call {...}``` from Grok response."""
    ...
def format_tool_result(tool_name: str, result: str) -> str:
    """Format tool output as a message to send back to Grok."""
    return f"Tool result from {tool_name}:\n{result}\n\nContinue your response."
Phase 3: Agent orchestration (linux/agent.py)
class GrokAgent:
    def __init__(self, engine: GrokPlaywrightEngine, tool_server_url: str, max_steps: int = 10):
        ...
    async def run(self, user_prompt: str, tools: list[str] | None = None) -> dict:
        """
        1. Build system prompt from tool registry
        2. Start new conversation, send system prompt
        3. Send user prompt
        4. Enter ReAct loop:
           a. Wait for Grok response
           b. Parse for tool_call
           c. If found: call tool server → send result to Grok → goto 4a
           d. If not found: return final response
        5. Max steps guard; error handling for tool failures
        """
Key behaviors:
- If tool server returns error, it's formatted and sent back to Grok so it can self-correct
- Parsed tool_call is validated against registry before calling server (catch bad names early)
- Each step logs to stdout for observability
- Timeout per step: inherited from timeout param
Phase 4: Bridge integration (linux/grok_bridge_l.py)
class AgentRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    timeout: int = Field(default=120, ge=5, le=900)
    tools: list[str] = Field(default_factory=list)  # optional tool filter
    max_steps: int = Field(default=10, ge=1, le=20)
# In create_app():
@app.post("/agent")
async def agent(req: AgentRequest):
    return await manager.agent_chat(
        prompt=req.prompt,
        timeout=req.timeout,
        tools=req.tools,
        max_steps=req.max_steps,
    )
New CLI arg: --tool-server-url (default http://localhost:19997)
System prompt (auto-generated from registry)
def build_system_prompt(tools: list[ToolDef]) -> str:
    tool_list = "\n".join(
        f"- {t.name}: {t.description}. Parameters: {json.dumps(t.parameters)}"
        for t in tools
    )
    return f"""You are an AI assistant with access to tools. When you need to use a tool, respond EXACTLY in this format and nothing else:
```tool_call
{{"tool": "tool_name", "args": {{"param": "value"}}}}
After you see the tool result, continue your response. Never invent tool results.
Available tools:
{tool_list}"""
### Error handling matrix
| Scenario | Behavior |
|----------|----------|
| Tool server unreachable | Return error to Grok: "Tool server unavailable. Try a different approach." |
| Tool returns error | Send error message to Grok so it can revise |
| Malformed tool_call JSON | Send parse error to Grok so it can re-format |
| Unknown tool name | Send error with available tool list |
| Max steps reached | Return partial response + warning |
| Grok doesn't respond | Same timeout handling as current `/chat` |
| Tool times out | Configurable per-tool timeout (default 30s); error sent to Grok |
### Dependencies to add (`pyproject.toml`)
```toml
"duckduckgo-search>=7.0.0",
"httpx>=0.28.0",
Startup (2 processes)
# Terminal 1: Tool server
python tools/tool_server.py --port 19997 &
# Terminal 2: Bridge with agent
python linux/grok_bridge_l.py --port 19998 --tool-server-url http://localhost:19997
Testing curl
# Regular chat (no tools)
curl -X POST http://localhost:19998/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Whats 15 * 37?"}'
# Agent with tools
curl -X POST http://localhost:19998/agent \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Whats the square root of 144 and who is the current president of Brazil?"}'
Future: code-access tools
When you want Grok to access your codebase, add a new tool to the tool server:
- code_search: grep the codebase for patterns
- file_read: return a file's contents (path-validated, size-limited)
- directory_list: list files in a directory
The tool server would need read-only access to the project directory. The bridge architecture stays the same — just new tool implementations in tools/.