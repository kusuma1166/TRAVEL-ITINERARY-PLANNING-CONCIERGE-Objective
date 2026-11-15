from __future__ import annotations

from typing import Any
from semantic_kernel.functions import kernel_function

from .state import TripState


class ActivityWorker:
    """Suggests daily activities that reflect the traveler's interests."""

    def __init__(self, state: TripState) -> None:
        self.state = state

    @kernel_function(description="Suggest activities for a trip day and stated interests.")
    def suggest_for_day(
        self, day: int, destination: str, interests: list[str], travelers: int
    ) -> list[dict[str, Any]]:
        interest_text = " ".join(interests).lower()
        if any(word in interest_text for word in ("food", "cuisine", "restaurant")):
            theme = "local food walk"
        elif any(word in interest_text for word in ("nature", "hike", "outdoor")):
            theme = "scenic nature trail"
        elif any(word in interest_text for word in ("art", "history", "culture", "museum")):
            theme = "historic district and museum"
        else:
            theme = "city highlights walk"
        options = [
            {"kind": "activity", "day": day, "name": f"{theme.title()} in {destination}",
             "cost": 45.0 * travelers, "time": "09:00"},
            {"kind": "activity", "day": day, "name": f"Small-group {theme} in {destination}",
             "cost": 15.0 * travelers, "time": "10:00"},
            {"kind": "activity", "day": day, "name": f"Self-guided {theme} in {destination}",
             "cost": 5.0 * travelers, "time": "10:00"},
            {"kind": "activity", "day": day, "name": f"Free public walk in {destination}",
             "cost": 0.0, "time": "10:00"},
        ]
        self.state.options[f"activities_day_{day}"] = options
        self.state.record("activity_worker", "suggest_for_day", day=day, options=len(options))
        return options

    @kernel_function(description="Return daily activity options cheaper than the rejected option.")
    def find_cheaper_activities(self, day: int, rejected_cost: float) -> list[dict[str, Any]]:
        options = [
            item for item in self.state.options.get(f"activities_day_{day}", [])
            if item["cost"] < rejected_cost
        ]
        self.state.record("activity_worker", "find_cheaper_activities", day=day, options=len(options))
        return options
