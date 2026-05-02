from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class MessageInfo:
    role: str
    content: str


@dataclass
class SessionInfo:
    id: int
    name: str
    url: str
    created_at: str
    updated_at: str
