from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer
from textual.screen import Screen
from textual.widgets import Button, Header, Footer, Input, Label, Static, Switch


class SettingsScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ScrollableContainer(
            Label("Connection", classes="section-title"),
            Label("Server URL:", classes="label"),
            Input(id="s-server-url", placeholder="http://localhost:19998", classes="input"),
            Label("Defaults", classes="section-title"),
            Label("Chat Timeout (s):", classes="label"),
            Input(id="s-timeout", classes="input"),
            Label("Agent Timeout (s):", classes="label"),
            Input(id="s-agent-timeout", classes="input"),
            Label("Agent Max Steps:", classes="label"),
            Input(id="s-max-steps", classes="input"),
            Label("WebSocket", classes="section-title"),
            Label("Use WebSocket for real-time streaming (connect per prompt):", classes="label"),
            Horizontal(
                Label("WebSocket Mode:", classes="label"),
                Switch(id="s-websocket"),
                classes="horizontal",
            ),
            Horizontal(
                Button("Save", id="save-btn", variant="primary"),
                Button("Reset", id="reset-btn"),
                Button("Back", id="back-btn"),
                classes="button-row",
            ),
            Static(id="settings-status"),
            id="settings-scroll",
        )
        yield Footer()

    def on_mount(self) -> None:
        cfg = self.app.config
        self.query_one("#s-server-url", Input).value = cfg.get("server_url", "")
        self.query_one("#s-timeout", Input).value = str(cfg.get("timeout", 120))
        self.query_one("#s-agent-timeout", Input).value = str(
            cfg.get("agent_timeout", 120)
        )
        self.query_one("#s-max-steps", Input).value = str(cfg.get("max_steps", 10))
        self.query_one("#s-websocket", Switch).value = bool(
            cfg.get("use_websocket", False)
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
        elif event.button.id == "save-btn":
            await self._save()
        elif event.button.id == "reset-btn":
            self._reset()
        elif event.button.id == "reconnect-btn":
            await self._reconnect()

    async def _save(self) -> None:
        cfg = self.app.config
        cfg["server_url"] = self.query_one("#s-server-url", Input).value.strip()
        try:
            cfg["timeout"] = int(
                self.query_one("#s-timeout", Input).value or "120"
            )
        except ValueError:
            pass
        try:
            cfg["agent_timeout"] = int(
                self.query_one("#s-agent-timeout", Input).value or "120"
            )
        except ValueError:
            pass
        try:
            cfg["max_steps"] = int(
                self.query_one("#s-max-steps", Input).value or "10"
            )
        except ValueError:
            pass

        cfg["use_websocket"] = bool(
            self.query_one("#s-websocket", Switch).value
        )

        from tui.config import save_config

        save_config(cfg)

        # Reconnect client with new URL
        await self.app.client.close()
        from tui.client import GrokClient

        self.app.client = GrokClient(cfg["server_url"])

        self.query_one("#settings-status", Static).update(
            "[green]Settings saved. Client reconnected.[/green]"
        )

    def _reset(self) -> None:
        from tui.config import DEFAULT_CONFIG

        self.app.config["server_url"] = DEFAULT_CONFIG["server_url"]
        self.app.config["timeout"] = DEFAULT_CONFIG["timeout"]
        self.app.config["agent_timeout"] = DEFAULT_CONFIG["agent_timeout"]
        self.app.config["max_steps"] = DEFAULT_CONFIG["max_steps"]
        self.app.config["use_websocket"] = DEFAULT_CONFIG["use_websocket"]
        self.on_mount()
        self.query_one("#settings-status", Static).update(
            "[yellow]Defaults restored (click Save to persist)[/yellow]"
        )
