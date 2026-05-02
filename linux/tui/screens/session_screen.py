from __future__ import annotations

from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer
from textual.screen import Screen
from textual.widgets import Button, Header, Footer, Label, ListItem, ListView, Static


class SessionScreen(Screen):
    def __init__(self) -> None:
        super().__init__()
        self._sessions: List[Dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Label("Saved Sessions", classes="section-title")
        yield ListView(id="session-list")
        yield Horizontal(
            Button("Load", id="load-btn", variant="primary"),
            Button("Delete", id="delete-btn", variant="error"),
            Button("Refresh", id="refresh-btn"),
            Button("Back", id="back-btn"),
            id="session-buttons",
        )
        yield Static(id="session-status")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        self.call_after_refresh(self._do_refresh)

    async def _do_refresh(self) -> None:
        self._update_status("[yellow]Loading sessions...[/yellow]")
        try:
            self._sessions = await self.app.client.list_sessions()
        except Exception as e:
            self._update_status(f"[red]Error: {e}[/red]")
            return
        lv = self.query_one("#session-list", ListView)
        lv.clear()
        if not self._sessions:
            lv.append(ListItem(Label("[dim]No saved sessions[/dim]")))
            self._update_status("[dim]No sessions found[/dim]")
            return
        for s in self._sessions:
            name: str = s.get("name", "?")[:60]
            ts: str = (s.get("updated_at") or s.get("created_at") or "?")[:19]
            lv.append(
                ListItem(
                    Label(f"[bold]{name}[/bold]"),
                    Label(f"[dim]{ts}[/dim]"),
                )
            )
        self._update_status(f"[green]{len(self._sessions)} sessions[/green]")

    def _update_status(self, text: str) -> None:
        self.query_one("#session-status", Static).update(text)

    def _selected_session(self) -> Optional[Dict[str, Any]]:
        lv = self.query_one("#session-list", ListView)
        if lv.index is None or not self._sessions:
            return None
        idx = lv.index
        if idx < 0 or idx >= len(self._sessions):
            return None
        return self._sessions[idx]

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id: Optional[str] = event.button.id
        if btn_id == "back-btn":
            self.app.pop_screen()
        elif btn_id == "refresh-btn":
            self._refresh()
        elif btn_id == "load-btn":
            await self._load_session()
        elif btn_id == "delete-btn":
            await self._delete_session()

    async def _load_session(self) -> None:
        s = self._selected_session()
        if s is None:
            self._update_status("[yellow]Select a session first[/yellow]")
            return
        self._update_status(f"[yellow]Loading '{s['name']}'...[/yellow]")
        try:
            result = await self.app.client.load_session(s["id"])
        except Exception as e:
            self._update_status(f"[red]Error: {e}[/red]")
            return
        if result.get("status") != "ok":
            self._update_status(
                f"[red]Failed: {result.get('error', 'unknown')}[/red]"
            )
            return
        self.dismiss(result)

    async def _delete_session(self) -> None:
        s = self._selected_session()
        if s is None:
            self._update_status("[yellow]Select a session first[/yellow]")
            return
        self._update_status(f"[yellow]Deleting '{s['name']}'...[/yellow]")
        try:
            result = await self.app.client.delete_session(s["id"])
        except Exception as e:
            self._update_status(f"[red]Error: {e}[/red]")
            return
        if result.get("status") == "ok":
            self._update_status("[green]Deleted[/green]")
            self._refresh()
        else:
            self._update_status(
                f"[red]Failed: {result.get('error', 'unknown')}[/red]"
            )
