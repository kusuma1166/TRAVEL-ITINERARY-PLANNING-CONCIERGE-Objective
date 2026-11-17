from __future__ import annotations

from typing import Any
from semantic_kernel.functions import kernel_function

from .live_search import LiveSearchError, SerpApiClient
from .state import TripState

MAX_INTERESTS = 5


class ActivityWorker:
    """Searches live destination attractions related to traveler interests."""

    def __init__(self, state: TripState, search_client: SerpApiClient) -> None:
        self.state = state
        self.search_client = search_client

    @kernel_function(description="Find live attractions for a trip day and stated interests.")
    def suggest_for_day(
        self, day: int, destination: str, interests: list[str]
    ) -> list[dict[str, Any]]:
        if "activities" not in self.state.options:
            activities_by_place: dict[str, dict[str, Any]] = {}
            search_warnings: list[str] = []
            for interest in interests:
                query = f"{interest} attractions things to do in {destination}"
                payload = self.search_client.search({
                    "engine": "google_maps",
                    "type": "search",
                    "q": query,
                    "hl": "en",
                })
                results = payload.get("local_results", [])
                if not isinstance(results, list):
                    raise LiveSearchError("Google Maps returned an invalid place-results list.")
                if not results:
                    search_warnings.append(f"No live place results for {interest!r}.")
                self.state.record(
                    "activity_worker",
                    "search_interest",
                    interest=interest,
                    options=len(results),
                )
                for result in results:
                    if not isinstance(result, dict):
                        continue
                    name = str(result.get("title", "")).strip()
                    if not name:
                        continue
                    place_id = result.get("place_id")
                    key = str(place_id or name.casefold())
                    if key in activities_by_place:
                        matches = activities_by_place[key]["matched_interests"]
                        if interest not in matches:
                            matches.append(interest)
                        continue
                    coordinates = result.get("gps_coordinates")
                    latitude = longitude = None
                    if isinstance(coordinates, dict):
                        try:
                            latitude = float(coordinates["latitude"])
                            longitude = float(coordinates["longitude"])
                        except (KeyError, TypeError, ValueError):
                            latitude = longitude = None
                        if (
                            latitude is not None
                            and longitude is not None
                            and not (-90 <= latitude <= 90 and -180 <= longitude <= 180)
                        ):
                            latitude = longitude = None
                    activities_by_place[key] = {
                        "kind": "activity",
                        "name": name,
                        "cost": None,
                        "price_status": "admission price not provided by search results",
                        "address": result.get("address"),
                        "rating": result.get("rating"),
                        "latitude": latitude,
                        "longitude": longitude,
                        "matched_interests": [interest],
                        "source": "Google Maps via SerpApi",
                        "source_url": result.get("link") or result.get("place_id_search"),
                    }
            if not activities_by_place:
                raise LiveSearchError(
                    f"Google Maps returned no usable attractions for {destination!r} "
                    "and the selected interests."
                )
            self.state.options["activities"] = list(activities_by_place.values())
            self.state.options["activity_search_warnings"] = search_warnings

        selected_names = {
            item["name"].casefold()
            for item in self.state.chosen_items
            if item["kind"] == "activity"
        }
        options = [
            {**item, "day": day}
            for item in self.state.options["activities"]
            if item["name"].casefold() not in selected_names
        ]
        if interests:
            target_interest = interests[(day - 1) % len(interests)].casefold()
            options.sort(
                key=lambda item: target_interest
                not in {interest.casefold() for interest in item["matched_interests"]}
            )
        self.state.options[f"activities_day_{day}"] = options
        self.state.record("activity_worker", "suggest_for_day", day=day, options=len(options))
        return options

    @kernel_function(description="Return daily activity options cheaper than the rejected option.")
    def find_cheaper_activities(self, day: int, rejected_cost: float) -> list[dict[str, Any]]:
        options = [
            item for item in self.state.options.get(f"activities_day_{day}", [])
            if item["cost"] is not None and item["cost"] < rejected_cost
        ]
        self.state.record("activity_worker", "find_cheaper_activities", day=day, options=len(options))
        return options
