from __future__ import annotations

import json
import os
from typing import Any, Dict, List

DEFAULT_CONFIG: Dict[str, Any] = {
    "server_url": "http://localhost:19998",
    "timeout": 120,
    "agent_timeout": 120,
    "max_steps": 10,
    "tools": ["calculator", "web_search", "file_read"],
    "use_websocket": False,
}

CONFIG_DIR = os.path.expanduser("~/.grok-bridge")
CONFIG_PATH = os.path.join(CONFIG_DIR, "tui-config.json")


def load_config() -> Dict[str, Any]:
    cfg = DEFAULT_CONFIG.copy()
    try:
        if os.path.isfile(CONFIG_PATH):
            with open(CONFIG_PATH) as f:
                cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
