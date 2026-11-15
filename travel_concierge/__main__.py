from __future__ import annotations

import argparse
import json
from pathlib import Path

from .planner_manager import PlannerManager
from .state import AppendOnlyRunLog


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan a budget-aware multi-day trip.")
    parser.add_argument("--origin", default="New York")
    parser.add_argument("--destination", default="Kyoto")
    parser.add_argument("--days", type=int, default=4)
    parser.add_argument("--travelers", type=int, default=2)
    parser.add_argument("--budget", type=float, default=3000)
    parser.add_argument("--interests", default="culture, food, nature")
    parser.add_argument("--log", default="run_log.jsonl")
    args = parser.parse_args()
    request = {
        "origin": args.origin,
        "destination": args.destination,
        "days": args.days,
        "travelers": args.travelers,
        "budget": args.budget,
        "interests": args.interests,
    }
    result = PlannerManager(AppendOnlyRunLog(Path(args.log))).build_itinerary(request)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
