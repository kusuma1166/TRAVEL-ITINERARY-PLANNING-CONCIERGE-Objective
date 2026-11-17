from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json


@dataclass
class TripState:
    request: dict[str, Any]
    budget: float
    budget_remaining: float = field(init=False)
    chosen_items: list[dict[str, Any]] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    replans: int = 0

    def __post_init__(self) -> None:
        self.budget_remaining = self.budget

    @property
    def total(self) -> float:
        return round(
            sum(item["cost"] for item in self.chosen_items if item.get("cost") is not None),
            2,
        )

    def record(self, agent: str, action: str, **details: Any) -> None:
        self.events.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "action": action,
            **details,
        })

    def add_approved_item(self, item: dict[str, Any]) -> None:
        self.chosen_items.append(item)
        self.budget_remaining = round(self.budget - self.total, 2)


class AppendOnlyRunLog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")

    def append_events(self, events: list[dict[str, Any]]) -> None:
        for event in events:
            self.append(event)
