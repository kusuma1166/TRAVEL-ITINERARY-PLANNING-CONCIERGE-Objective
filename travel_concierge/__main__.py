from __future__ import annotations

import argparse
import json
from pathlib import Path

from .planner_manager import PlannerManager
from .state import AppendOnlyRunLog


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan a budget-aware multi-day trip.")
    parser.add_argument("--origin", required=True, help="Origin city")
    parser.add_argument("--origin-airport", required=True, help="Origin IATA airport code, e.g. BOS")
    parser.add_argument("--destination", required=True, help="Destination city")
    parser.add_argument(
        "--destination-airport", required=True, help="Destination IATA airport code, e.g. KIX"
    )
    parser.add_argument("--departure-date", required=True, help="Flight departure date (YYYY-MM-DD)")
    parser.add_argument("--return-date", required=True, help="Flight return date (YYYY-MM-DD)")
    parser.add_argument("--check-in", required=True, help="Hotel check-in date (YYYY-MM-DD)")
    parser.add_argument("--check-out", required=True, help="Hotel check-out date (YYYY-MM-DD)")
    parser.add_argument("--travelers", type=int, default=2)
    parser.add_argument("--budget", type=float, default=3000)
    parser.add_argument("--interests", default="culture, food, nature")
    parser.add_argument("--currency", default="USD", help="Three-letter currency code")
    parser.add_argument("--food-per-person-per-day", type=float, default=0)
    parser.add_argument("--transport-per-person-per-day", type=float, default=0)
    parser.add_argument("--log", default="run_log.jsonl")
    args = parser.parse_args()
    request = {
        "origin": args.origin,
        "origin_airport": args.origin_airport,
        "destination": args.destination,
        "destination_airport": args.destination_airport,
        "departure_date": args.departure_date,
        "return_date": args.return_date,
        "hotel_check_in": args.check_in,
        "hotel_check_out": args.check_out,
        "travelers": args.travelers,
        "budget": args.budget,
        "interests": args.interests,
        "currency": args.currency,
        "food_budget_per_person_per_day": args.food_per_person_per_day,
        "transport_budget_per_person_per_day": args.transport_per_person_per_day,
    }
    result = PlannerManager(AppendOnlyRunLog(Path(args.log))).build_itinerary(request)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
