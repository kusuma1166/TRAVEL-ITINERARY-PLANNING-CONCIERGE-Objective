from __future__ import annotations

import math
from typing import Any
from urllib.parse import urlencode
from semantic_kernel.functions import kernel_function

from .live_search import LiveSearchError, SerpApiClient
from .state import TripState


class FlightWorker:
    """Searches live outbound and return fares and cheaper alternatives."""

    def __init__(self, state: TripState, search_client: SerpApiClient) -> None:
        self.state = state
        self.search_client = search_client

    @kernel_function(description="Search live outbound and return flight fares.")
    def search_flights(
        self,
        origin: str,
        destination: str,
        travelers: int,
        departure_date: str,
        return_date: str,
        currency: str,
    ) -> list[dict[str, Any]]:
        payload = self.search_client.search({
            "engine": "google_flights",
            "departure_id": origin,
            "arrival_id": destination,
            "outbound_date": departure_date,
            "type": "2",
            "adults": travelers,
            "currency": currency,
            "sort_by": "2",
            "hl": "en",
        })
        outbound_options = self._offers(payload)
        if not outbound_options:
            raise LiveSearchError("Google Flights returned no outbound flight offers.")

        return_payload = self.search_client.search({
            "engine": "google_flights",
            "departure_id": destination,
            "arrival_id": origin,
            "outbound_date": return_date,
            "type": "2",
            "adults": travelers,
            "currency": currency,
            "sort_by": "2",
            "hl": "en",
        })
        return_options = self._offers(return_payload)
        if not return_options:
            raise LiveSearchError("Google Flights returned no return flight offers.")
        return_offer = min(return_options, key=self._price)
        return_price = self._price(return_offer)
        return_route = self._route_summary(return_offer)

        options: list[dict[str, Any]] = []
        for outbound in sorted(outbound_options, key=self._price)[:5]:
            outbound_price = self._price(outbound)
            outbound_route = self._route_summary(outbound)
            options.append({
                "kind": "flight",
                "name": f"Outbound {outbound_route}; return {return_route}",
                "cost": round(outbound_price + return_price, 2),
                "currency": currency,
                "outbound_departure": departure_date,
                "return_departure": return_date,
                "source": "Google Flights one-way fares via SerpApi",
                "source_url": (
                    "https://www.google.com/travel/flights?"
                    + urlencode({
                        "q": (
                            f"flights from {origin} to {destination} on {departure_date} "
                            f"through {return_date}"
                        )
                    })
                ),
            })
        if not options:
            raise LiveSearchError(
                "Google Flights returned no priced outbound and return combination."
            )
        options.sort(key=lambda item: item["cost"])
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

    @staticmethod
    def _offers(payload: dict[str, Any]) -> list[dict[str, Any]]:
        offers = payload.get("best_flights", []) + payload.get("other_flights", [])
        return [offer for offer in offers if isinstance(offer, dict) and "price" in offer]

    @staticmethod
    def _price(offer: dict[str, Any]) -> float:
        try:
            price = float(offer["price"])
        except (KeyError, TypeError, ValueError) as error:
            raise LiveSearchError("Google Flights returned an offer with an invalid price.") from error
        if not math.isfinite(price) or price < 0:
            raise LiveSearchError("Google Flights returned an invalid price.")
        return price

    @staticmethod
    def _route_summary(offer: dict[str, Any]) -> str:
        flights = offer.get("flights", [])
        if not flights:
            return "Flight option"
        first = flights[0]
        last = flights[-1]
        departure = first.get("departure_airport", {}).get("id", "origin")
        arrival = last.get("arrival_airport", {}).get("id", "destination")
        airline = first.get("airline", "Airline")
        return f"{airline} {departure} to {arrival}"
