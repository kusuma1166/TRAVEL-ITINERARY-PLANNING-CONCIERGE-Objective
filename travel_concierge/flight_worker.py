from __future__ import annotations

from typing import Any
from semantic_kernel.functions import kernel_function

from .state import TripState


class FlightWorker:
    """Finds round-trip flight estimates and cheaper alternatives."""

    def __init__(self, state: TripState) -> None:
        self.state = state

    @kernel_function(description="Find estimated round-trip flight options.")
    def search_flights(self, origin: str, destination: str, travelers: int) -> list[dict[str, Any]]:
        catalog = [
            ("Premium direct", 900.0),
            ("Standard one-stop", 480.0),
            ("Economy advance fare", 280.0),
        ]
        options = [
            {
                "kind": "flight",
                "name": f"{label} flight: {origin} to {destination} (round trip)",
                "cost": price * travelers,
                "unit_price": price,
            }
            for label, price in catalog
        ]
        self.state.options["flights"] = options
        self.state.record("flight_worker", "search_flights", options=len(options))
        return options

    @kernel_function(description="Return flight options cheaper than the rejected option.")
    def find_cheaper_flights(self, rejected_cost: float) -> list[dict[str, Any]]:
        options = [
            item for item in self.state.options.get("flights", [])
            if item["cost"] < rejected_cost
        ]
        self.state.record("flight_worker", "find_cheaper_flights", options=len(options))
        return options
