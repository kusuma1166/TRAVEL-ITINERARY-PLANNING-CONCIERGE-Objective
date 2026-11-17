# Travel Itinerary Planning Concierge

Multi-agent travel planner built with **Semantic Kernel**. It accepts origin/destination, explicit flight and hotel dates, budget, interests, and traveler count, then prints a day-by-day plan and its agent trace. Flight and hotel offers and destination activities are fetched live through SerpApi's Google Flights, Google Hotels, and Google Maps engines. Search results and prices can change and must be confirmed with the provider before booking.

## Agent roster and coordination

`PlannerManager` validates the request and delegates in sequence to `FlightWorker`, `HotelWorker`, `ActivityWorker`, and `BudgetWorker`. Flight and lodging prices are live search results; activities come from live destination listings. Each role is a separate module and its Python tools are registered as Semantic Kernel plugins.

Every agent receives and reads/writes the same `TripState` object. It stores the request, option lists, approved choices, remaining budget, re-plan count, and trace. Only `BudgetWorker.approve_addition` can add a choice, and every item is checked before addition. When a choice does not fit, the manager asks that worker for cheaper alternatives and tries them before moving on.

| Agent | Python tools |
|---|---|
| Planner Manager | `parse_request`, `build_itinerary` |
| Flight Worker | Live outbound and return fare searches, `find_cheaper_flights` |
| Hotel Worker | Live date-specific search, `find_cheaper_hotels` |
| Activity Worker | Live interest-based place search, `find_cheaper_activities` |
| Budget Worker | `approve_addition`, `get_budget_report` |

## Run it

```powershell
python -m pip install -r requirements.txt
```

Start the Streamlit frontend on this computer only:

```powershell
streamlit run streamlit_app.py --server.address 127.0.0.1
```

The page accepts up to five interests and searches live Maps results separately for each one, then rotates the preferred interest across trip days. That uses one Maps API search per interest. Flight searches use IATA airport codes; hotel and activity searches use the destination city name. Activity results with coordinates are shown on a map, and live hotel-provider and flight-search links open external sites. The app does not book or pay for travel.

Enter API keys in the masked fields in the app's sidebar. They remain in the active local app session and are not written to project files or logs. SerpApi is required for itinerary searches; OpenAI is optional and is called only after checking the AI briefing opt-in. The CLI can instead read `SERPAPI_API_KEY` from the process environment.

Create a SerpApi account and set its key in your PowerShell session (do not commit or share the key):

```powershell
$env:SERPAPI_API_KEY = "your-key"
python -m travel_concierge --origin Boston --origin-airport BOS --destination Kyoto --destination-airport KIX --departure-date 2027-06-01 --return-date 2027-06-04 --check-in 2027-06-01 --check-out 2027-06-04 --travelers 2 --budget 2500 --interests "culture, food" --food-per-person-per-day 35 --transport-per-person-per-day 12
python -m unittest discover -s tests -v
```

SerpApi key signup: https://serpapi.com/users/sign_up. The service currently lists a limited free tier; check its current [pricing](https://serpapi.com/pricing) and API docs for [Google Flights](https://serpapi.com/google-flights-api), [Google Hotels](https://serpapi.com/google-hotels-api), and [Google Maps](https://serpapi.com/google-maps-api). Every search requests uncached results. Flight searches use IATA airport codes; hotel and activity searches use the destination city name. Outbound and return airfare totals combine two live one-way searches, so they are fare estimates rather than a single round-trip fare. All travelers are treated as adults. `--departure-date`, `--return-date`, `--check-in`, and `--check-out` are required and use `YYYY-MM-DD`.

Open-Meteo supplies destination weather without an API key; forecasts are shown only for dates from today through 15 days ahead. Food and local transport are optional per-person daily estimates supplied by the traveler, reserved in the budget before flights and hotels are selected; they are not live quotes. The itinerary summary is sent to OpenAI only after the explicit opt-in checkbox is selected and an OpenAI key is available. `OPENAI_MODEL` can override the default `gpt-4o-mini` model.

Open and run `travel_concierge_demo.ipynb` for the live-search notebook demo. Each successful CLI/notebook run appends its trace to `run_log.jsonl`; existing entries are not overwritten. See [architecture.mmd](architecture.mmd) for the architecture diagram.

## Honest failure handled

If even the cheapest priced candidate exceeds the remaining budget, the manager records `no_affordable_option` and leaves that category unfilled rather than violating the budget. Activity listings often omit admission prices; those activities are labeled as unpriced and excluded from budget totals, so the final trip cost may be higher than the displayed priced subtotal. Search availability, displayed prices, taxes, and fees can change; confirm details with the provider before booking.
