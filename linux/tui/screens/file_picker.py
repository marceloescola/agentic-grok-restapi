from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, DirectoryTree


class FilePicker(Screen[Optional[str]]):
    def __init__(self, start_path: str = ".") -> None:
        super().__init__()
        self._start: str = os.path.abspath(os.path.expanduser(start_path))

    def compose(self) -> ComposeResult:
        yield DirectoryTree(self._start, id="file-tree")
        yield Horizontal(
            Button("Select", id="select-btn", variant="primary"),
            Button("Cancel", id="cancel-btn"),
            id="fp-buttons",
        )

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self.dismiss(str(event.path))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "select-btn":
            tree = self.query_one("#file-tree", DirectoryTree)
            node = tree.cursor_node
            if node and node.data:
                p: Path = Path(str(node.data))
                if p.is_file():
                    self.dismiss(str(p))
