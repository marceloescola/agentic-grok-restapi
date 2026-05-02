from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Label


class MenuScreen(Screen[Optional[str]]):
    def compose(self) -> ComposeResult:
        with Container(id="menu-container"):
            yield Label("Menu", classes="menu-title")
            yield Button("Agent Mode", id="agent", variant="primary")
            yield Button("Sessions", id="sessions")
            yield Button("Settings", id="settings")
            yield Button("Exit App", id="exit")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id)

    def key_escape(self) -> None:
        self.dismiss(None)
