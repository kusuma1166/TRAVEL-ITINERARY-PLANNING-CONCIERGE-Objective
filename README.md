# Travel Itinerary Planning Concierge

Offline-first, deterministic multi-agent travel planner built with **Semantic Kernel**. It accepts origin, destination, days, budget, interests, and traveler count, then prints a day-by-day plan and its agent trace. Estimates come from a small illustrative local catalog; they are not live travel quotes.

## Agent roster and coordination

`PlannerManager` validates the request and delegates in sequence to `FlightWorker`, `HotelWorker`, `ActivityWorker`, and `BudgetWorker`. This manager-worker architecture fits the task because fare, lodging, activity, and budget decisions have distinct responsibilities, while one manager coordinates the end-to-end itinerary. Each role is a separate module and its Python tools are registered as Semantic Kernel plugins. No model key or network access is required.

Every agent receives and reads/writes the same `TripState` object. It stores the request, option lists, approved choices, remaining budget, re-plan count, and trace. Only `BudgetWorker.approve_addition` can add a choice, and every item is checked before addition. When a choice does not fit, the manager asks that worker for cheaper alternatives and tries them before moving on.

| Agent | Python tools |
|---|---|
| Planner Manager | `parse_request`, `build_itinerary` |
| Flight Worker | `search_flights`, `find_cheaper_flights` |
| Hotel Worker | `search_hotels`, `find_cheaper_hotels` |
| Activity Worker | `suggest_for_day`, `find_cheaper_activities` |
| Budget Worker | `approve_addition`, `get_budget_report` |

## Run it

```powershell
python -m pip install -r requirements.txt
python -m travel_concierge --origin Boston --destination Kyoto --days 3 --travelers 2 --budget 2500 --interests "culture, food"
python -m unittest discover -s tests -v
```

Open and run `travel_concierge_demo.ipynb` for a notebook demo that prints the itinerary and full multi-agent trace. Each CLI/notebook run appends its trace to `run_log.jsonl`; existing entries are not overwritten. See [architecture.mmd](architecture.mmd) for the architecture diagram.

## Honest failure handled

If even the cheapest candidate exceeds the remaining budget, the manager records `no_affordable_option` and leaves that category unfilled rather than violating the budget. The trip can therefore be incomplete when the requested budget is infeasible. Prices and destination activity labels are estimates from an illustrative catalog, not real-time booking data.
