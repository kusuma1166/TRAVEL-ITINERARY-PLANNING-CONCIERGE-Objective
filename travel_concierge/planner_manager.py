from __future__ import annotations

from typing import Any
from semantic_kernel import Kernel
from semantic_kernel.functions import kernel_function

from .activity_worker import ActivityWorker
from .budget_worker import BudgetWorker
from .flight_worker import FlightWorker
from .hotel_worker import HotelWorker
from .state import AppendOnlyRunLog, TripState


class PlannerManager:
    """Coordinates specialist workers and ensures all choices pass the budget gate."""

    def __init__(self, run_log: AppendOnlyRunLog | None = None) -> None:
        self.run_log = run_log
        self.kernel = Kernel()

    @kernel_function(description="Validate and normalize a travel planning request.")
    def parse_request(self, request: dict[str, Any]) -> dict[str, Any]:
        required = ("origin", "destination", "days", "budget", "interests")
        missing = [key for key in required if key not in request]
        if missing:
            raise ValueError(f"Missing required request fields: {', '.join(missing)}")
        days = int(request["days"])
        travelers = int(request.get("travelers", 1))
        budget = float(request["budget"])
        if days < 1 or travelers < 1 or budget < 0:
            raise ValueError("Days and travelers must be positive; budget cannot be negative.")
        interests = request["interests"]
        if isinstance(interests, str):
            interests = [interest.strip() for interest in interests.split(",") if interest.strip()]
        if not isinstance(interests, list) or not all(isinstance(item, str) for item in interests):
            raise ValueError("Interests must be a list of strings or a comma-separated string.")
        normalized = {
            "origin": str(request["origin"]),
            "destination": str(request["destination"]),
            "days": days,
            "budget": budget,
            "interests": interests,
            "travelers": travelers,
        }
        return normalized

    @kernel_function(description="Build a day-by-day trip plan using the specialist workers.")
    def build_itinerary(self, request: dict[str, Any]) -> dict[str, Any]:
        normalized = self.parse_request(request)
        state = TripState(request=normalized, budget=normalized["budget"])
        state.record("planner_manager", "request_accepted", request=normalized)
        flight_worker = FlightWorker(state)
        hotel_worker = HotelWorker(state)
        activity_worker = ActivityWorker(state)
        budget_worker = BudgetWorker(state)

        # Register every worker's real Python tools with Semantic Kernel; execution is
        # deterministic and offline, so no model credentials or network calls are needed.
        self.kernel.add_plugin(self, plugin_name="planner_manager")
        self.kernel.add_plugin(flight_worker, plugin_name="flight_worker")
        self.kernel.add_plugin(hotel_worker, plugin_name="hotel_worker")
        self.kernel.add_plugin(activity_worker, plugin_name="activity_worker")
        self.kernel.add_plugin(budget_worker, plugin_name="budget_worker")

        self._choose_with_replan(
            flight_worker.search_flights(
                normalized["origin"], normalized["destination"], normalized["travelers"]
            ),
            flight_worker.find_cheaper_flights,
            budget_worker,
            state,
            category="flight",
        )
        self._choose_with_replan(
            hotel_worker.search_hotels(normalized["destination"], normalized["days"]),
            hotel_worker.find_cheaper_hotels,
            budget_worker,
            state,
            category="hotel",
        )
        for day in range(1, normalized["days"] + 1):
            options = activity_worker.suggest_for_day(
                day, normalized["destination"], normalized["interests"], normalized["travelers"]
            )
            self._choose_with_replan(
                options,
                lambda rejected, day=day: activity_worker.find_cheaper_activities(day, rejected),
                budget_worker,
                state,
                category=f"activity_day_{day}",
                day=day,
            )

        report = budget_worker.get_budget_report()
        itinerary = self._format_itinerary(state, report)
        state.record("planner_manager", "itinerary_built", total=report["spent"])
        if self.run_log is not None:
            self.run_log.append_events(state.events)
        return itinerary

    def _choose_with_replan(
        self,
        options: list[dict[str, Any]],
        cheaper_options: Any,
        budget_worker: BudgetWorker,
        state: TripState,
        category: str,
        day: int | None = None,
    ) -> None:
        pending = list(options)
        seen: set[str] = set()
        while pending:
            candidate = pending.pop(0)
            if candidate["name"] in seen:
                continue
            seen.add(candidate["name"])
            if budget_worker.approve_addition(candidate):
                return
            state.replans += 1
            state.record("planner_manager", "replan_requested", category=category, day=day)
            pending.extend(cheaper_options(candidate["cost"]))
        state.record("planner_manager", "no_affordable_option", category=category, day=day)

    def _format_itinerary(self, state: TripState, budget: dict[str, float]) -> dict[str, Any]:
        days = state.request["days"]
        itinerary = [
            {"day": day, "items": []}
            for day in range(1, days + 1)
        ]
        for item in state.chosen_items:
            if item["kind"] == "flight":
                itinerary[0]["items"].append({**item, "schedule": "Arrival / round trip"})
                itinerary[-1]["items"].append({
                    **item,
                    "cost": 0.0,
                    "schedule": "Return flight (fare included above)",
                })
            elif item["kind"] == "hotel":
                nights = max(1, days - 1)
                nightly_cost = round(item["cost"] / nights, 2)
                for day in itinerary[:nights]:
                    day["items"].append({
                        **item,
                        "cost": nightly_cost,
                        "schedule": "Overnight stay (per-night estimate)",
                    })
            else:
                itinerary[item["day"] - 1]["items"].append(item)
        return {
            "destination": state.request["destination"],
            "travelers": state.request["travelers"],
            "interests": state.request["interests"],
            "days": itinerary,
            "budget": budget,
            "replans": state.replans,
            "trace": state.events,
        }
