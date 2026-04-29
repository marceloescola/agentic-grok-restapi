from __future__ import annotations

from typing import Any, Dict, Optional

from textual.app import App
from textual.binding import Binding

from tui.client import GrokClient
from tui.config import load_config
from tui.screens.agent_screen import AgentScreen
from tui.screens.main_screen import MainScreen
from tui.screens.menu_screen import MenuScreen
from tui.screens.settings_screen import SettingsScreen


class GrokTUI(App):
    CSS_PATH = "styles/app.tcss"

    BINDINGS = [
        Binding("ctrl+shift+y", "show_menu", "Menu", priority=True),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.config: Dict[str, Any] = load_config()
        self.client: GrokClient = GrokClient(
            self.config.get("server_url", "http://localhost:19998")
        )

    def on_mount(self) -> None:
        self.push_screen(MainScreen())

    def action_show_menu(self) -> None:
        if isinstance(self.screen, MenuScreen):
            return
        self.push_screen(MenuScreen(), self._handle_menu)

    def _handle_menu(self, action: Optional[str]) -> None:
        if action is None:
            return
        if action == "agent":
            self.push_screen(AgentScreen())
        elif action == "settings":
            self.push_screen(SettingsScreen())
        elif action == "exit":
            self.exit()


if __name__ == "__main__":
    app = GrokTUI()
    app.run()
