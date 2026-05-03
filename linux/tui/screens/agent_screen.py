from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer
from textual.screen import Screen
from textual.widgets import (
    Button,
    Header,
    Footer,
    Input,
    Label,
    RichLog,
    Static,
)

from tui.client import GrokWSClient
from tui.screens.file_picker import FilePicker
from tui.screens.session_screen import SessionScreen


class AgentScreen(Screen):
    def __init__(self) -> None:
        super().__init__()
        self._active_tools: Set[str] = set()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ScrollableContainer(
            Label("Agent Mode — Tool-Calling Interface", classes="section-title"),
            Horizontal(
                Label("Tools:", classes="label"),
                Button("Calculator", id="tool-calculator", variant="primary"),
                Button("Web Search", id="tool-web_search", variant="primary"),
                Button("File Read", id="tool-file_read", variant="primary"),
                id="tool-bar",
            ),
            Horizontal(
                Input(id="file-path", placeholder="Path to file..."),
                Button("Browse", id="browse-btn"),
                id="file-section",
            ),
            Horizontal(
                Label("Max Steps:", classes="label"),
                Input(id="max-steps", value="10"),
                id="max-steps-bar",
            ),
            id="agent-config",
        )
        yield RichLog(id="agent-output", highlight=True, wrap=True, markup=True)
        yield Horizontal(
            Input(
                id="agent-prompt",
                placeholder="Enter your agent prompt...",
            ),
            Button("Run Agent", id="run-btn", variant="primary"),
            Button("Back", id="back-btn"),
            id="agent-input-bar",
        )
        yield Horizontal(
            Button("Sessions", id="agent-sessions-btn"),
            id="agent-session-bar",
        )
        yield Static(id="agent-status")
        yield Footer()

    def on_mount(self) -> None:
        self._active_tools = {"calculator", "web_search", "file_read"}
        self._update_file_section()
        self.query_one("#agent-output", RichLog).write(
            "[bold cyan]Agent ready[/bold cyan]\n"
        )

    def _update_file_section(self) -> None:
        section = self.query_one("#file-section")
        section.display = "file_read" in self._active_tools

    def _toggle_tool(self, btn_id: str) -> None:
        btn = self.query_one(f"#{btn_id}", Button)
        tool_name: str = btn_id.replace("tool-", "")
        if tool_name in self._active_tools:
            self._active_tools.discard(tool_name)
            btn.variant = "default"
        else:
            self._active_tools.add(tool_name)
            btn.variant = "primary"
        self._update_file_section()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id: str | None = event.button.id
        if btn_id == "back-btn":
            self.app.pop_screen()
        elif btn_id == "run-btn":
            await self._run_agent()
        elif btn_id and btn_id.startswith("tool-"):
            self._toggle_tool(btn_id)
        elif btn_id == "browse-btn":
            await self._browse_file()
        elif btn_id == "agent-sessions-btn":
            self._show_sessions()

    async def _browse_file(self) -> None:
        self.app.push_screen(FilePicker(), self._on_file_picked)

    def _on_file_picked(self, path: str | None) -> None:
        if path:
            self.query_one("#file-path", Input).value = path

    def _show_sessions(self) -> None:
        self.app.push_screen(SessionScreen(), self._on_session_result)

    def _on_session_result(self, result: Optional[Dict[str, Any]]) -> None:
        if result is None:
            return
        session: Dict[str, Any] = result.get("session", {})
        messages: List[Dict[str, str]] = result.get("messages", [])
        if not messages:
            self._log(
                f"[bold yellow]Session:[/bold yellow] {session.get('name', '?')}"
            )
            return
        output = self.query_one("#agent-output", RichLog)
        output.clear()
        self._log(
            f"[bold yellow]--- Loaded session: {session.get('name', '?')} ---[/bold yellow]"
        )
        for msg in messages:
            role: str = msg.get("role", "?")
            content: str = msg.get("content", "")
            if role == "user":
                self._log(f"\n[bold cyan]You:[/bold cyan] {content}")
            else:
                self._log(f"\n[bold green]Grok:[/bold green] {content}")
        self._update_status(
            f"[green]Session loaded[/green] ({len(messages)} messages)"
        )
        self.query_one("#agent-prompt", Input).focus()

    def _log(self, text: str) -> None:
        self.query_one("#agent-output", RichLog).write(text)

    def _update_status(self, text: str) -> None:
        self.query_one("#agent-status", Static).update(text)

    async def _run_agent(self) -> None:
        prompt: str = self.query_one("#agent-prompt", Input).value.strip()
        if not prompt:
            self._update_status("[red]Prompt is required[/red]")
            return

        run_btn = self.query_one("#run-btn", Button)
        run_btn.disabled = True

        if self._active_tools:
            tools: List[str] = list(self._active_tools)
        else:
            tools = ["calculator", "web_search", "file_read"]

        max_steps_input = self.query_one("#max-steps", Input)
        try:
            max_steps: int = int(max_steps_input.value or "10")
        except ValueError:
            max_steps = 10

        self._log(f"\n[bold yellow]Running agent:[/bold yellow] {prompt[:80]}...")
        self._log(f"[dim]Tools: {tools} | Max steps: {max_steps}[/dim]\n")
        self._update_status("[yellow]Agent running...[/yellow]")

        use_ws: bool = self.app.config.get("use_websocket", False)

        file_path: str = self.query_one("#file-path", Input).value.strip()
        files: List[str] = [file_path] if file_path else []

        try:
            if use_ws:
                await self._run_ws(prompt, tools, max_steps, files)
            else:
                await self._run_rest(prompt, tools, max_steps, files)
        finally:
            run_btn.disabled = False
            self.query_one("#agent-prompt", Input).clear()

    async def _run_rest(
        self, prompt: str, tools: List[str], max_steps: int, files: List[str]
    ) -> None:
        try:
            result: Dict[str, Any] = await self.app.client.agent(
                prompt=prompt,
                timeout=self.app.config.get("agent_timeout", 120),
                tools=tools,
                max_steps=max_steps,
            )

            resp_status: str = result.get("status", "error")
            response: str = result.get("response", "")
            agent_steps: List[Dict[str, Any]] = result.get("steps", [])
            step_count: int = result.get("step_count", 0)

            self._log(
                f"[bold]Status:[/bold] {resp_status} | Steps: {step_count}"
            )

            if agent_steps:
                self._log("\n[bold underline]Tool Calls:[/bold underline]")
                for s in agent_steps:
                    step_num: int = s.get("step", "?")
                    tool_name: str = s.get("tool", "?")
                    args: Any = s.get("args", {})
                    tool_result: str = s.get("result", "")
                    self._log(
                        f"\n[bold cyan]Step {step_num}:[/bold cyan] "
                        f"[green]{tool_name}[/green]"
                    )
                    self._log(f"  Args: {args}")
                    preview: str = tool_result[:200]
                    if len(tool_result) > 200:
                        preview += "..."
                    self._log(f"  Result: {preview}")

            if response:
                self._log(
                    f"\n[bold green]Final Response:[/bold green]\n{response}"
                )

            self._update_status(
                f"[green]Agent finished[/green] ({resp_status})"
            )

        except Exception as e:
            self._log(f"\n[bold red]Agent error:[/bold red] {e}")
            self._update_status("[red]Agent failed[/red]")

    async def _run_ws(
        self, prompt: str, tools: List[str], max_steps: int, files: List[str]
    ) -> None:
        ws = GrokWSClient(
            self.app.config.get("server_url", "http://localhost:19998")
        )
        try:
            async for event in ws.run_prompt(
                prompt=prompt,
                mode="agent",
                tools=tools,
                files=files or None,
            ):
                t: str = event.get("type", "")
                if t == "partial":
                    self._log(f"[dim]{event.get('content', '')}[/dim]")
                elif t == "tool_call":
                    self._log(
                        f"\n[bold cyan]Calling tool:[/bold cyan] "
                        f"[green]{event.get('tool')}[/green]"
                        f" {event.get('arguments', {})}"
                    )
                elif t == "tool_result":
                    r: str = event.get("result", "")
                    preview: str = r[:200]
                    if len(r) > 200:
                        preview += "..."
                    self._log(f"  [dim]Result: {preview}[/dim]")
                elif t == "message":
                    self._log(
                        f"\n[bold green]Final Response:[/bold green]\n"
                        f"{event.get('content', '')}"
                    )
                elif t == "status":
                    state: str = event.get("state", "")
                    if state == "done":
                        self._update_status("[green]Agent finished[/green]")
                    elif state == "max_steps":
                        self._update_status(
                            "[yellow]Max steps reached[/yellow]"
                        )
                    else:
                        self._update_status(f"[yellow]{state}[/yellow]")
                elif t == "error":
                    self._log(
                        f"\n[bold red]Error:[/bold red] {event.get('content')}"
                    )
                    self._update_status("[red]Agent failed[/red]")
        except Exception as e:
            self._log(f"\n[bold red]WS error:[/bold red] {e}")
            self._update_status("[red]WS failed[/red]")
