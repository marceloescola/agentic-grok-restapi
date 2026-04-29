from __future__ import annotations

from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Header, Footer, Input, RichLog, Static


class MainScreen(Screen):
    def compose(self):
        yield Header(show_clock=True)
        yield RichLog(id="chat-log", highlight=True, wrap=True, markup=True)
        yield Input(id="prompt-input", placeholder="Type a message and press Enter...")
        yield Horizontal(
            Input(
                id="files-input",
                placeholder="File paths (comma-separated, optional)",
            ),
            id="files-bar",
        )
        yield Horizontal(
            Button("Send", id="send-btn", variant="primary"),
            Button("New", id="new-btn"),
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

    async def _check_health_quiet(self):
        try:
            info = await self.app.client.health()
            status = info.get("status", "unknown")
            url = info.get("url", "?")
            engine = info.get("active_engine", "?")
            on_grok = info.get("on_grok", False)
            grok_str = "on grok.com" if on_grok else "off-site"
            self._update_status(
                f"[green]Connected[/green] | {grok_str} | "
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
        elif btn_id == "history-btn":
            await self._fetch_history()
        elif btn_id == "menu-btn":
            self.app.action_show_menu()

    async def _send_prompt(self, prompt: str):
        files_input = self.query_one("#files-input", Input)
        files = (
            [f.strip() for f in files_input.value.split(",") if f.strip()]
            if files_input.value.strip()
            else []
        )

        self._log(f"\n[bold cyan]You:[/bold cyan] {prompt}")
        if files:
            self._log(f"[dim]Files: {', '.join(files)}[/dim]")
        self._update_status("[yellow]Sending...[/yellow]")
        self.query_one("#send-btn", Button).disabled = True
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
            self.query_one("#send-btn", Button).disabled = False

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
            msg = (
                f"\n[bold]Health Check:[/bold]\n"
                f"  Status: [green]{status}[/green]\n"
                f"  Version: {version}\n"
                f"  Engine: {engine}\n"
                f"  On grok.com: {grok_str}\n"
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
