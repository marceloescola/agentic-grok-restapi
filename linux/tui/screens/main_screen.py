from __future__ import annotations

from typing import Any, Dict, List, Optional

from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Header, Footer, Input, RichLog, Static

from tui.client import GrokWSClient
from tui.screens.session_screen import SessionScreen


class MainScreen(Screen):
    def __init__(self) -> None:
        super().__init__()
        self._streaming: bool = False

    def compose(self):
        yield Header(show_clock=True)
        yield RichLog(id="chat-log", highlight=True, wrap=True, markup=True)
        yield Static(id="streaming-area", markup=True)
        yield Horizontal(
            Input(
                id="files-input",
                placeholder="File paths (comma-separated, optional)",
            ),
            id="files-bar",
        )
        yield Input(id="prompt-input", placeholder="Type a message and press Enter...")
        yield Horizontal(
            Button("Send", id="send-btn", variant="primary"),
            Button("New", id="new-btn"),
            Button("Sessions", id="sessions-btn"),
            Button("Health", id="health-btn"),
            Button("History", id="history-btn"),
            Button("Menu", id="menu-btn"),
            id="button-bar",
        )
        yield Static(id="status-bar")
        yield Footer()

    def on_mount(self):
        self._log("[bold green]Grok Bridge TUI[/bold green]")
        self._log("Type a message and press Enter or click Send.")
        self._log("Press Ctrl+Shift+Y or click Menu for options.\n")
        self._update_status("Ready")
        self.call_after_refresh(self._check_health_quiet)

    def _log(self, text: str):
        self.query_one("#chat-log", RichLog).write(text)

    def _update_status(self, text: str):
        self.query_one("#status-bar", Static).update(text)

    def _update_streaming(self, content: str):
        self.query_one("#streaming-area", Static).update(
            f"[bold green]Grok:[/bold green] {content}"
        )

    def _clear_streaming(self):
        self.query_one("#streaming-area", Static).update("")

    async def _check_health_quiet(self):
        try:
            info = await self.app.client.health()
            status = info.get("status", "unknown")
            url = info.get("url", "?")
            engine = info.get("active_engine", "?")
            on_grok = info.get("on_grok", False)
            grok_str = "on grok.com" if on_grok else "off-site"
            use_ws = self.app.config.get("use_websocket", False)
            ws_str = " [cyan]WS[/cyan]" if use_ws else ""
            self._update_status(
                f"[green]Connected[/green]{ws_str} | {grok_str} | "
                f"engine: {engine} | {url[:60]}"
            )
        except Exception:
            self._update_status(
                "[red]Disconnected[/red] - is the bridge server running? "
                f"(http://localhost:19998)"
            )

    async def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "prompt-input" and event.value.strip():
            await self._send_prompt(event.value.strip())

    async def on_button_pressed(self, event: Button.Pressed):
        btn_id = event.button.id
        if btn_id == "send-btn":
            inp = self.query_one("#prompt-input", Input)
            if inp.value.strip():
                await self._send_prompt(inp.value.strip())
                inp.clear()
        elif btn_id == "new-btn":
            await self._new_conversation()
        elif btn_id == "health-btn":
            await self._check_health()
        elif btn_id == "sessions-btn":
            self._show_sessions()
        elif btn_id == "history-btn":
            await self._fetch_history()
        elif btn_id == "menu-btn":
            self.app.action_show_menu()

    async def _send_prompt(self, prompt: str):
        if self._streaming:
            return

        files_input = self.query_one("#files-input", Input)
        files = (
            [f.strip() for f in files_input.value.split(",") if f.strip()]
            if files_input.value.strip()
            else []
        )

        self._log(f"\n[bold cyan]You:[/bold cyan] {prompt}")
        if files:
            self._log(f"[dim]Files: {', '.join(files)}[/dim]")

        use_ws: bool = self.app.config.get("use_websocket", False)

        if use_ws:
            await self._send_ws(prompt, files)
        else:
            await self._send_rest(prompt, files)

    async def _send_rest(self, prompt: str, files):
        self._update_status("[yellow]Sending...[/yellow]")
        self._set_sending(True)
        try:
            result = await self.app.client.chat(
                prompt=prompt,
                timeout=self.app.config.get("timeout", 120),
                files=files or None,
            )
            status = result.get("status", "error")
            resp = result.get("response") or result.get("error", "No response")
            elapsed = result.get("elapsed", "?")
            if status == "ok":
                self._log(f"[bold green]Grok:[/bold green] {resp}")
                self._update_status(f"[green]OK[/green] ({elapsed}s)")
            else:
                self._log(f"[bold red]Error ({status}):[/bold red] {resp}")
                self._update_status(f"[red]{status}[/red] ({elapsed}s)")
        except Exception as e:
            self._log(f"\n[bold red]Connection error:[/bold red] {e}")
            self._update_status("[red]Connection failed[/red]")
        finally:
            self._set_sending(False)

    async def _send_ws(self, prompt: str, files):
        self._update_status("[yellow]Streaming...[/yellow]")
        self._streaming = True
        self._set_sending(True)
        ws = GrokWSClient(self.app.config.get("server_url", "http://localhost:19998"))
        try:
            async for event in ws.run_prompt(
                prompt=prompt, mode="chat", files=files or None
            ):
                t: str = event.get("type", "")
                if t == "partial":
                    self._update_streaming(event.get("content", ""))
                elif t == "done":
                    content: str = event.get("content", "")
                    self._log(f"[bold green]Grok:[/bold green] {content}")
                    self._clear_streaming()
                    self._update_status("[green]Done[/green]")
                elif t == "tool_call":
                    self._log(
                        f"[bold cyan]Calling tool: {event.get('tool')}"
                        f"({event.get('arguments', {})})[/bold cyan]"
                    )
                elif t == "tool_result":
                    self._log(
                        f"[dim]Tool result ({len(event.get('result', ''))} chars)[/dim]"
                    )
                elif t == "error":
                    self._log(f"[bold red]Error:[/bold red] {event.get('content')}")
                    self._update_status("[red]Error[/red]")
                elif t == "status":
                    state: str = event.get("state", "")
                    if state == "done":
                        self._update_status("[green]Done[/green]")
                    else:
                        self._update_status(f"[yellow]{state}[/yellow]")
        except Exception as e:
            self._log(f"\n[bold red]WS error:[/bold red] {e}")
            self._update_status("[red]WS failed[/red]")
        finally:
            self._streaming = False
            self._clear_streaming()
            self._set_sending(False)

    def _set_sending(self, busy: bool):
        self.query_one("#send-btn", Button).disabled = busy
        self.query_one("#prompt-input", Input).disabled = busy

    async def _new_conversation(self):
        self._update_status("[yellow]Starting new conversation...[/yellow]")
        try:
            result = await self.app.client.new_conversation()
            if result.get("status") == "ok":
                self.query_one("#chat-log", RichLog).clear()
                self._log("[bold yellow]--- New conversation started ---[/bold yellow]")
                self._log("Type a message and press Enter or click Send.\n")
                self._update_status("[green]New conversation[/green]")
            else:
                self._log(
                    f"[bold red]Error:[/bold red] "
                )
        except Exception as e:
            self._log(f"\n[bold red]Connection error:[/bold red] {e}")
            self._update_status("[red]Connection failed[/red]")

    async def _check_health(self):
        try:
            info = await self.app.client.health()
            status = info.get("status", "unknown")
            url = info.get("url", "?")
            engine = info.get("active_engine", "?")
            version = info.get("version", "?")
            on_grok = info.get("on_grok", False)
            grok_str = "yes" if on_grok else "no"
            available = info.get("available_engines", {})
            use_ws = self.app.config.get("use_websocket", False)
            ws_str = "WS on" if use_ws else "WS off"
            msg = (
                f"\n[bold]Health Check:[/bold]\n"
                f"  Status: [green]{status}[/green]\n"
                f"  Version: {version}\n"
                f"  Engine: {engine}\n"
                f"  On grok.com: {grok_str}\n"
                f"  WebSocket: {ws_str}\n"
                f"  URL: {url}\n"
                f"  Available: {available}"
            )
            self._log(msg)
            self._update_status(
                f"[green]Healthy[/green] | on grok.com: {grok_str}"
            )
        except Exception as e:
            self._log(f"\n[bold red]Health check failed:[/bold red] {e}")
            self._update_status("[red]Unreachable[/red]")

    async def _fetch_history(self):
        self._update_status("[yellow]Fetching history...[/yellow]")
        try:
            result = await self.app.client.history()
            if result.get("status") == "ok":
                content = result.get("content", "")
                raw_len = result.get("raw_length", 0)
                max_display = 3000
                display = content[:max_display]
                if len(content) > max_display:
                    display += (
                        f"\n\n... [truncated, full length: {raw_len} chars]"
                    )
                self._log(
                    f"\n[bold]--- History ({raw_len} chars) ---[/bold]\n"
                    f"{display}\n"
                )
                self._update_status(
                    f"[green]History loaded[/green] ({raw_len} chars)"
                )
            else:
                self._log(
                    f"[bold red]History error:[/bold red] "
                    f"{result.get('error', 'unknown')}"
                )
        except Exception as e:
            self._log(f"\n[bold red]Connection error:[/bold red] {e}")
            self._update_status("[red]Connection failed[/red]")

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
            self._log("[dim]No messages in this session[/dim]")
            return
        chat_log = self.query_one("#chat-log", RichLog)
        chat_log.clear()
        self._log(
            f"[bold yellow]--- Loaded session: {session.get('name', '?')} ---[/bold yellow]"
        )
        for msg in messages:
            role: str = msg.get("role", "?")
            content: str = msg.get("content", "")
            if role == "user":
                self._log(f"\n[bold cyan]You:[/bold cyan] {content}")
            elif role == "assistant":
                self._log(f"\n[bold green]Grok:[/bold green] {content}")
            else:
                self._log(f"\n[{role}] {content}")
        self._update_status(
            f"[green]Session loaded[/green] ({len(messages)} messages)"
        )
