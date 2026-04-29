from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Protocol, runtime_checkable


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, str | dict[str, str]]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@runtime_checkable
class Tool(Protocol):
    @property
    def definition(self) -> ToolDef: ...

    async def run(self, **kwargs: str) -> str: ...
