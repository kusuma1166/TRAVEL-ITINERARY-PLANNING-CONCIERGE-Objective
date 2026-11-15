from __future__ import annotations

from typing import Any
from semantic_kernel.functions import kernel_function

from .state import TripState


class BudgetWorker:
    """The sole authority that may add items to the shared trip state."""

    def __init__(self, state: TripState) -> None:
        self.state = state

    @kernel_function(description="Approve an item only when it fits the remaining trip budget.")
    def approve_addition(self, item: dict[str, Any]) -> bool:
        cost = float(item["cost"])
        if cost < 0:
            raise ValueError("An itinerary item cannot have a negative cost.")
        approved = cost <= self.state.budget_remaining
        self.state.record(
            "budget_worker",
            "approve_addition",
            item=item["name"],
            cost=cost,
            approved=approved,
            remaining_before=self.state.budget_remaining,
        )
        if approved:
            self.state.add_approved_item(item)
        return approved

    @kernel_function(description="Summarize the shared trip budget.")
    def get_budget_report(self) -> dict[str, float]:
        report = {
            "budget": round(self.state.budget, 2),
            "spent": self.state.total,
            "remaining": self.state.budget_remaining,
        }
        self.state.record("budget_worker", "get_budget_report", **report)
        return report
