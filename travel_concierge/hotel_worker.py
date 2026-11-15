from __future__ import annotations

from typing import Any
from semantic_kernel.functions import kernel_function

from .state import TripState


class HotelWorker:
    """Finds hotels in the destination and prices the full stay."""

    def __init__(self, state: TripState) -> None:
        self.state = state

    @kernel_function(description="Find hotel estimates for the requested stay.")
    def search_hotels(self, destination: str, days: int) -> list[dict[str, Any]]:
        nights = max(1, days - 1)
        catalog = [
            ("Central comfort hotel", 240.0),
            ("Neighborhood guesthouse", 130.0),
            ("Budget hostel", 80.0),
        ]
        options = [
            {
                "kind": "hotel",
                "name": f"{label} in {destination} ({nights} night{'s' if nights != 1 else ''})",
                "cost": nightly_rate * nights,
                "nightly_rate": nightly_rate,
            }
            for label, nightly_rate in catalog
        ]
        self.state.options["hotels"] = options
        self.state.record("hotel_worker", "search_hotels", options=len(options))
        return options

    @kernel_function(description="Return hotel options cheaper than the rejected option.")
    def find_cheaper_hotels(self, rejected_cost: float) -> list[dict[str, Any]]:
        options = [
            item for item in self.state.options.get("hotels", [])
            if item["cost"] < rejected_cost
        ]
        self.state.record("hotel_worker", "find_cheaper_hotels", options=len(options))
        return options
