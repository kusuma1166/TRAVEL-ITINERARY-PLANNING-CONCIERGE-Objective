from __future__ import annotations

from datetime import date
import math
import re
from typing import Any
from semantic_kernel import Kernel
from semantic_kernel.functions import kernel_function

from .activity_worker import ActivityWorker, MAX_INTERESTS
from .budget_worker import BudgetWorker
from .flight_worker import FlightWorker
from .hotel_worker import HotelWorker
from .live_search import SerpApiClient
from .state import AppendOnlyRunLog, TripState


class PlannerManager:
    """Coordinates specialist workers and ensures all choices pass the budget gate."""

    def __init__(
        self,
        run_log: AppendOnlyRunLog | None = None,
        search_client: SerpApiClient | None = None,
    ) -> None:
        self.run_log = run_log
        self.search_client = search_client if search_client is not None else SerpApiClient()
        self.kernel = Kernel()

    @kernel_function(description="Validate and normalize a travel planning request.")
    def parse_request(self, request: dict[str, Any]) -> dict[str, Any]:
        required = (
            "origin",
            "origin_airport",
            "destination",
            "destination_airport",
            "budget",
            "interests",
            "departure_date",
            "return_date",
            "hotel_check_in",
            "hotel_check_out",
        )
        missing = [key for key in required if key not in request]
        if missing:
            raise ValueError(f"Missing required request fields: {', '.join(missing)}")
        travelers = int(request.get("travelers", 1))
        budget = float(request["budget"])
        if travelers < 1 or not math.isfinite(budget) or budget < 0:
            raise ValueError("Travelers must be positive; budget cannot be negative.")
        interests = request["interests"]
        if isinstance(interests, str):
            interests = [interest.strip() for interest in interests.split(",") if interest.strip()]
        if not isinstance(interests, list) or not all(isinstance(item, str) for item in interests):
            raise ValueError("Interests must be a list of strings or a comma-separated string.")
        unique_interests = []
        seen_interests = set()
        for value in interests:
            interest = value.strip()
            key = interest.casefold()
            if interest and key not in seen_interests:
                unique_interests.append(interest)
                seen_interests.add(key)
        if not unique_interests:
            raise ValueError("At least one activity interest is required.")
        if len(unique_interests) > MAX_INTERESTS:
            raise ValueError(f"Choose no more than {MAX_INTERESTS} interests per search.")
        parsed_dates = {}
        for field in ("departure_date", "return_date", "hotel_check_in", "hotel_check_out"):
            try:
                parsed_dates[field] = date.fromisoformat(str(request[field]))
            except ValueError as error:
                raise ValueError(f"{field} must use YYYY-MM-DD format.") from error
        if parsed_dates["return_date"] <= parsed_dates["departure_date"]:
            raise ValueError("return_date must be after departure_date.")
        if parsed_dates["hotel_check_out"] <= parsed_dates["hotel_check_in"]:
            raise ValueError("hotel_check_out must be after hotel_check_in.")
        origin_airport = str(request["origin_airport"]).upper()
        destination_airport = str(request["destination_airport"]).upper()
        if not re.fullmatch(r"[A-Z]{3}", origin_airport):
            raise ValueError("origin_airport must be a three-letter IATA airport code.")
        if not re.fullmatch(r"[A-Z]{3}", destination_airport):
            raise ValueError("destination_airport must be a three-letter IATA airport code.")
        currency = str(request.get("currency", "USD")).upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("currency must be a three-letter code.")
        days = (parsed_dates["hotel_check_out"] - parsed_dates["hotel_check_in"]).days + 1
        food_allowance = float(request.get("food_budget_per_person_per_day", 0))
        transport_allowance = float(request.get("transport_budget_per_person_per_day", 0))
        if (
            not math.isfinite(food_allowance)
            or not math.isfinite(transport_allowance)
            or food_allowance < 0
            or transport_allowance < 0
        ):
            raise ValueError("Daily food and transport allowances must be finite and non-negative.")
        daily_food = round(food_allowance * travelers, 2)
        daily_transport = round(transport_allowance * travelers, 2)
        required_allowances = round((daily_food + daily_transport) * days, 2)
        if required_allowances > budget:
            raise ValueError(
                "The food and transport allowances alone exceed the trip budget. "
                "Lower the allowances or increase the budget."
            )
        normalized = {
            "origin": str(request["origin"]),
            "origin_airport": origin_airport,
            "destination": str(request["destination"]),
            "destination_airport": destination_airport,
            "days": days,
            "budget": budget,
            "interests": unique_interests,
            "travelers": travelers,
            "currency": currency,
            "food_budget_per_person_per_day": food_allowance,
            "transport_budget_per_person_per_day": transport_allowance,
            **{field: value.isoformat() for field, value in parsed_dates.items()},
        }
        return normalized

    @kernel_function(description="Build a day-by-day trip plan using the specialist workers.")
    def build_itinerary(self, request: dict[str, Any]) -> dict[str, Any]:
        normalized = self.parse_request(request)
        state = TripState(request=normalized, budget=normalized["budget"])
        state.record("planner_manager", "request_accepted", request=normalized)
        flight_worker = FlightWorker(state, self.search_client)
        hotel_worker = HotelWorker(state, self.search_client)
        activity_worker = ActivityWorker(state, self.search_client)
        budget_worker = BudgetWorker(state)

        # Register every worker's real Python tools with Semantic Kernel.
        self.kernel.add_plugin(self, plugin_name="planner_manager")
        self.kernel.add_plugin(flight_worker, plugin_name="flight_worker")
        self.kernel.add_plugin(hotel_worker, plugin_name="hotel_worker")
        self.kernel.add_plugin(activity_worker, plugin_name="activity_worker")
        self.kernel.add_plugin(budget_worker, plugin_name="budget_worker")

        for day in range(1, normalized["days"] + 1):
            for kind, amount, description in (
                (
                    "food",
                    round(normalized["food_budget_per_person_per_day"] * normalized["travelers"], 2),
                    "Food allowance (user estimate)",
                ),
                (
                    "transport",
                    round(
                        normalized["transport_budget_per_person_per_day"]
                        * normalized["travelers"],
                        2,
                    ),
                    "Local transport allowance (user estimate)",
                ),
            ):
                if amount:
                    budget_worker.approve_addition({
                        "kind": kind,
                        "day": day,
                        "name": description,
                        "cost": amount,
                        "currency": normalized["currency"],
                        "source": "user-provided daily allowance",
                    })

        self._choose_with_replan(
            flight_worker.search_flights(
                normalized["origin_airport"],
                normalized["destination_airport"],
                normalized["travelers"],
                normalized["departure_date"],
                normalized["return_date"],
                normalized["currency"]
            ),
            flight_worker.find_cheaper_flights,
            budget_worker,
            state,
            category="flight",
        )
        self._choose_with_replan(
            hotel_worker.search_hotels(
                normalized["destination"],
                normalized["hotel_check_in"],
                normalized["hotel_check_out"],
                normalized["travelers"],
                normalized["currency"],
            ),
            hotel_worker.find_cheaper_hotels,
            budget_worker,
            state,
            category="hotel",
        )
        for day in range(1, normalized["days"] + 1):
            options = activity_worker.suggest_for_day(
                day, normalized["destination"], normalized["interests"]
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
                itinerary[0]["items"].append({
                    **item,
                    "schedule": "Outbound + return fare estimate",
                })
                itinerary[-1]["items"].append({
                    **item,
                    "cost": 0.0,
                    "schedule": "Return flight (fare included above)",
                })
            elif item["kind"] == "hotel":
                nights = max(1, days - 1)
                regular_nightly_cost = round(item["cost"] / nights, 2)
                for index, day in enumerate(itinerary[:nights]):
                    nightly_cost = (
                        regular_nightly_cost
                        if index < nights - 1
                        else round(item["cost"] - regular_nightly_cost * (nights - 1), 2)
                    )
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
            "currency": state.request["currency"],
            "interests": state.request["interests"],
            "days": itinerary,
            "budget": budget,
            "unpriced_activities": [
                item["name"] for item in state.chosen_items
                if item["kind"] == "activity" and item.get("cost") is None
            ],
            "activity_search_warnings": state.options.get("activity_search_warnings", []),
            "budget_note": (
                "Food and local transport are user-provided daily estimates. "
                "Activity admission prices are unavailable from the live listings and are "
                "excluded from the budget totals."
            ),
            "replans": state.replans,
            "trace": state.events,
        }
