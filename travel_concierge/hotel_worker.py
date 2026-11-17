from __future__ import annotations

from datetime import date
import math
from typing import Any
from semantic_kernel.functions import kernel_function

from .live_search import LiveSearchError, SerpApiClient
from .state import TripState


class HotelWorker:
    """Searches live hotel availability and prices the full stay."""

    def __init__(self, state: TripState, search_client: SerpApiClient) -> None:
        self.state = state
        self.search_client = search_client

    @kernel_function(description="Search live hotel offers for the requested dates.")
    def search_hotels(
        self,
        destination: str,
        check_in_date: str,
        check_out_date: str,
        travelers: int,
        currency: str,
    ) -> list[dict[str, Any]]:
        payload = self.search_client.search({
            "engine": "google_hotels",
            "q": destination,
            "check_in_date": check_in_date,
            "check_out_date": check_out_date,
            "adults": travelers,
            "currency": currency,
            "sort_by": "3",
            "hl": "en",
        })
        nights = (
            date.fromisoformat(check_out_date) - date.fromisoformat(check_in_date)
        ).days
        options = []
        for property_result in payload.get("properties", []):
            if not isinstance(property_result, dict):
                continue
            rate = property_result.get("total_rate", {}).get("extracted_lowest")
            if rate is None:
                continue
            try:
                total_cost = float(rate)
            except (TypeError, ValueError) as error:
                raise LiveSearchError(
                    "Google Hotels returned a property with an invalid total rate."
                ) from error
            if not math.isfinite(total_cost) or total_cost < 0:
                raise LiveSearchError("Google Hotels returned an invalid total rate.")
            nightly = property_result.get("rate_per_night", {}).get("extracted_lowest")
            try:
                nightly_rate = float(nightly) if nightly is not None else round(total_cost / nights, 2)
            except (TypeError, ValueError) as error:
                raise LiveSearchError(
                    "Google Hotels returned a property with an invalid nightly rate."
                ) from error
            if not math.isfinite(nightly_rate) or nightly_rate < 0:
                raise LiveSearchError("Google Hotels returned an invalid nightly rate.")
            booking_links = [
                {"source": price.get("source"), "url": price.get("link")}
                for price in property_result.get("prices", [])
                if isinstance(price, dict) and isinstance(price.get("link"), str)
                and price["link"].startswith("https://")
            ]
            options.append({
                "kind": "hotel",
                "name": str(property_result.get("name", "Hotel")),
                "cost": round(total_cost, 2),
                "nightly_rate": nightly_rate,
                "nights": nights,
                "currency": currency,
                "check_in_date": check_in_date,
                "check_out_date": check_out_date,
                "rating": property_result.get("overall_rating"),
                "source": "Google Hotels via SerpApi",
                "source_url": property_result.get("serpapi_property_details_link"),
                "booking_links": booking_links,
            })
        if not options:
            raise LiveSearchError(
                "Google Hotels returned no properties with a total price for the selected dates."
            )
        options.sort(key=lambda item: item["cost"])
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
