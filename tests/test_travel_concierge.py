import unittest
from datetime import date, timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse
import os
from urllib.error import HTTPError

from openai import OpenAIError
from travel_concierge.llm_assistant import ItineraryAssistant, LLMConfigurationError
from travel_concierge.live_search import LiveSearchError, SerpApiClient
from travel_concierge.planner_manager import PlannerManager
from travel_concierge.state import AppendOnlyRunLog
from travel_concierge.weather import OpenMeteoClient, WeatherSearchError


class FixtureSearchClient:
    def __init__(self):
        self.calls = []

    def search(self, parameters):
        self.calls.append(parameters)
        if parameters["engine"] == "google_flights":
            if parameters["departure_id"] == "KIX":
                return {"best_flights": [{
                    "price": 100,
                    "flights": [{
                        "airline": "Example Air",
                        "departure_airport": {"id": "KIX"},
                        "arrival_airport": {"id": "BOS"},
                    }],
                }]}
            return {
                "best_flights": [{
                    "price": 500,
                    "flights": [{
                        "airline": "Example Air",
                        "departure_airport": {"id": "BOS"},
                        "arrival_airport": {"id": "KIX"},
                    }],
                }],
                "other_flights": [{
                    "price": 200,
                    "flights": [{
                        "airline": "Example Air",
                        "departure_airport": {"id": "BOS"},
                        "arrival_airport": {"id": "KIX"},
                    }],
                }],
            }
        if parameters["engine"] == "google_hotels":
            return {
                "properties": [
                    {
                        "name": "Live hotel deal",
                        "total_rate": {"extracted_lowest": 200},
                        "rate_per_night": {"extracted_lowest": 66.67},
                        "serpapi_property_details_link": "https://example.test/hotel",
                        "prices": [{"source": "Example Booking", "link": "https://example.test/book"}],
                    },
                    {
                        "name": "Another live hotel",
                        "total_rate": {"extracted_lowest": 400},
                        "rate_per_night": {"extracted_lowest": 133.33},
                    },
                ]
            }
        if parameters["engine"] == "google_maps":
            interest = parameters["q"].split(" ", 1)[0].title()
            return {
                "local_results": [
                    {
                        "title": f"{interest} attraction {number}",
                        "place_id": f"{interest}-{number}",
                        "rating": 4.5,
                        "gps_coordinates": {
                            "latitude": 35.0 + number / 100,
                            "longitude": 135.0 + number / 100,
                        },
                    }
                    for number in range(1, 6)
                ]
            }
        raise AssertionError(f"Unexpected engine: {parameters['engine']}")


class TravelConciergeTests(unittest.TestCase):
    def setUp(self):
        self.search_client = FixtureSearchClient()
        self.manager = PlannerManager(search_client=self.search_client)
        self.start = date.today() + timedelta(days=90)
        self.end = self.start + timedelta(days=3)

    def request(self, budget=1000):
        return {
            "origin": "Boston",
            "origin_airport": "BOS",
            "destination": "Kyoto",
            "destination_airport": "KIX",
            "departure_date": self.start.isoformat(),
            "return_date": self.end.isoformat(),
            "hotel_check_in": self.start.isoformat(),
            "hotel_check_out": self.end.isoformat(),
            "travelers": 2,
            "budget": budget,
            "interests": ["culture", "food"],
        }

    def test_builds_itinerary_from_live_search_results(self):
        result = self.manager.build_itinerary(self.request())

        self.assertEqual(len(result["days"]), 4)
        self.assertEqual(result["currency"], "USD")
        self.assertTrue(all(day["items"] for day in result["days"]))
        kinds = {item["kind"] for day in result["days"] for item in day["items"]}
        self.assertTrue({"flight", "hotel", "activity"}.issubset(kinds))
        self.assertEqual(result["budget"]["spent"], 500)
        self.assertEqual(len(result["unpriced_activities"]), 4)
        displayed_priced_total = sum(
            item["cost"]
            for day in result["days"]
            for item in day["items"]
            if item.get("cost") is not None
        )
        self.assertAlmostEqual(displayed_priced_total, result["budget"]["spent"])
        activities = [
            item for day in result["days"] for item in day["items"]
            if item["kind"] == "activity"
        ]
        self.assertTrue(all(item["cost"] is None for item in activities))
        self.assertTrue(all(item["latitude"] is not None for item in activities))
        self.assertEqual(
            [item["matched_interests"][0] for item in activities],
            ["culture", "food", "culture", "food"],
        )
        self.assertEqual(
            [call["engine"] for call in self.search_client.calls].count("google_maps"),
            2,
        )
        flight_searches = [
            call for call in self.search_client.calls
            if call["engine"] == "google_flights"
        ]
        self.assertEqual(len(flight_searches), 2)
        self.assertEqual(flight_searches[0]["departure_id"], "BOS")
        self.assertEqual(flight_searches[0]["arrival_id"], "KIX")
        self.assertEqual(flight_searches[0]["type"], "2")
        self.assertEqual(flight_searches[1]["departure_id"], "KIX")
        self.assertEqual(flight_searches[1]["arrival_id"], "BOS")
        self.assertEqual(flight_searches[1]["outbound_date"], self.end.isoformat())
        self.assertTrue(all("departure_id" in call for call in flight_searches))
        hotels = [
            item for day in result["days"] for item in day["items"]
            if item["kind"] == "hotel"
        ]
        self.assertEqual(hotels[0]["booking_links"][0]["source"], "Example Booking")

    def test_user_food_and_transport_allowances_enter_budget(self):
        request = self.request()
        request["food_budget_per_person_per_day"] = 30
        request["transport_budget_per_person_per_day"] = 10
        result = self.manager.build_itinerary(request)
        food_total = sum(
            item["cost"] for day in result["days"] for item in day["items"]
            if item["kind"] == "food"
        )
        transport_total = sum(
            item["cost"] for day in result["days"] for item in day["items"]
            if item["kind"] == "transport"
        )
        self.assertEqual(food_total, 240)
        self.assertEqual(transport_total, 80)
        self.assertEqual(result["budget"]["spent"], 820)

    def test_allowances_over_budget_fail_before_live_search(self):
        request = self.request(budget=100)
        request["food_budget_per_person_per_day"] = 50
        with self.assertRaisesRegex(ValueError, "allowances alone exceed"):
            self.manager.build_itinerary(request)
        self.assertEqual(self.search_client.calls, [])

    def test_rejects_live_fares_that_exceed_budget(self):
        result = self.manager.build_itinerary(self.request(budget=100))
        categories_without_choices = {
            event["category"]
            for event in result["trace"]
            if event["action"] == "no_affordable_option"
        }
        self.assertIn("flight", categories_without_choices)
        self.assertIn("hotel", categories_without_choices)
        self.assertEqual(result["budget"]["spent"], 0)
        self.assertTrue(result["unpriced_activities"])

    def test_invalid_request_is_rejected(self):
        with self.assertRaises(ValueError):
            self.manager.build_itinerary({"origin": "Boston"})

    def test_interests_are_deduplicated_and_limited(self):
        request = self.request()
        request["interests"] = ["Culture", "culture", "Food"]
        normalized = self.manager.parse_request(request)
        self.assertEqual(normalized["interests"], ["Culture", "Food"])

        request["interests"] = ["culture", "food", "art", "history", "nature", "music"]
        with self.assertRaisesRegex(ValueError, "no more than 5"):
            self.manager.parse_request(request)

    def test_missing_api_key_is_reported_without_fallback(self):
        with self.assertRaisesRegex(LiveSearchError, "SERPAPI_API_KEY"):
            SerpApiClient(api_key="").search({"engine": "google_flights"})

        manager = PlannerManager(search_client=SerpApiClient(api_key=""))
        with self.assertRaisesRegex(LiveSearchError, "SERPAPI_API_KEY"):
            manager.build_itinerary(self.request())

    def test_api_requests_bypass_cached_searches(self):
        with patch("travel_concierge.live_search.urlopen") as mocked_urlopen:
            mocked_urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
            SerpApiClient(api_key="test-key").search({"engine": "google_flights"})

        request = mocked_urlopen.call_args.args[0]
        query = parse_qs(urlparse(request.full_url).query)
        self.assertEqual(query["no_cache"], ["true"])
        self.assertEqual(query["api_key"], ["test-key"])

    def test_api_timeout_is_reported_as_live_search_error(self):
        with patch("travel_concierge.live_search.urlopen", side_effect=TimeoutError("timeout")):
            with self.assertRaisesRegex(LiveSearchError, "Could not reach SerpApi"):
                SerpApiClient(api_key="test-key").search({"engine": "google_flights"})

    def test_http_error_includes_provider_detail_without_exposing_key(self):
        response = BytesIO(b'{"error":"Missing required outbound_date; token test-key"}')
        http_error = HTTPError(
            "https://serpapi.com/search.json",
            400,
            "Bad Request",
            {},
            response,
        )
        with patch("travel_concierge.live_search.urlopen", side_effect=http_error):
            with self.assertRaises(LiveSearchError) as raised:
                SerpApiClient(api_key="test-key").search({"engine": "google_flights"})
        self.assertIn("Missing required outbound_date", str(raised.exception))
        self.assertNotIn("test-key", str(raised.exception))

    def test_run_log_appends_events(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run_log.jsonl"
            self.manager.run_log = AppendOnlyRunLog(path)
            self.manager.build_itinerary(self.request())
            first_size = path.stat().st_size
            self.manager.build_itinerary(self.request())
            self.assertGreater(path.stat().st_size, first_size)


class WeatherTests(unittest.TestCase):
    def test_forecast_is_clipped_to_open_meteo_horizon(self):
            client = OpenMeteoClient()
            start = date.today() + timedelta(days=13)
            end = date.today() + timedelta(days=20)
            with patch.object(
                client,
                "_get_json",
                side_effect=[
                    {"results": [{"name": "Kyoto", "country": "Japan", "latitude": 35, "longitude": 135}]},
                    {
                        "daily": {
                            "time": [(date.today() + timedelta(days=day)).isoformat() for day in (13, 14, 15)],
                            "weather_code": [1, 2, 3],
                            "temperature_2m_max": [20, 21, 22],
                            "temperature_2m_min": [10, 11, 12],
                            "precipitation_probability_max": [0, 10, 20],
                        }
                    },
                ],
            ) as get_json:
                result = client.get_forecast("Kyoto", start.isoformat(), end.isoformat())

            self.assertTrue(result["available"])
            self.assertEqual(len(result["forecast"]), 3)
            self.assertEqual(result["forecast"][-1]["date"], (date.today() + timedelta(days=15)).isoformat())
            self.assertIn("available only through", result["warnings"][0])
            forecast_parameters = get_json.call_args_list[1].args[1]
            self.assertEqual(forecast_parameters["end_date"], (date.today() + timedelta(days=15)).isoformat())

    def test_dates_outside_forecast_horizon_do_not_make_requests(self):
            client = OpenMeteoClient()
            start = date.today() + timedelta(days=16)
            with patch.object(client, "_get_json") as get_json:
                result = client.get_forecast(
                    "Kyoto", start.isoformat(), (start + timedelta(days=2)).isoformat()
                )
            self.assertFalse(result["available"])
            get_json.assert_not_called()

    def test_network_timeout_is_reported_as_weather_error(self):
            client = OpenMeteoClient()
            with patch("travel_concierge.weather.urlopen", side_effect=TimeoutError("timeout")):
                with self.assertRaisesRegex(WeatherSearchError, "Could not reach Open-Meteo"):
                    client._get_json(client.geocoding_endpoint, {"name": "Kyoto"})


class LLMAssistantTests(unittest.TestCase):
    def test_briefing_is_opt_in_and_uses_supplied_trip_data(self):
            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
                with self.assertRaisesRegex(LLMConfigurationError, "OpenAI API key"):
                    ItineraryAssistant()

            client = SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(
                        create=Mock(return_value=SimpleNamespace(
                            choices=[SimpleNamespace(message=SimpleNamespace(content="Pack an umbrella."))]
                        ))
                    )
                )
            )
            itinerary = {
                "destination": "Kyoto",
                "interests": ["culture"],
                "currency": "USD",
                "budget": {"spent": 300, "remaining": 700},
                "days": [{"day": 1, "items": [{"name": "Museum", "kind": "activity", "cost": None}]}],
                "unpriced_activities": ["Museum"],
            }
            with (
                patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
                patch("travel_concierge.llm_assistant.OpenAI", return_value=client) as openai_client,
            ):
                assistant = ItineraryAssistant()
                briefing = assistant.create_briefing(itinerary)

            self.assertEqual(briefing, "Pack an umbrella.")
            openai_client.assert_called_once_with(api_key="test-key")
            sent_summary = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
            self.assertIn('"destination": "Kyoto"', sent_summary)
            self.assertIn('"unpriced_activities": ["Museum"]', sent_summary)

    def test_explicit_key_is_used_without_environment_configuration(self):
            client = SimpleNamespace(
                chat=SimpleNamespace(completions=SimpleNamespace(create=Mock()))
            )
            with (
                patch.dict(os.environ, {"OPENAI_API_KEY": ""}),
                patch("travel_concierge.llm_assistant.OpenAI", return_value=client) as openai_client,
            ):
                ItineraryAssistant(api_key="session-only-key")
            openai_client.assert_called_once_with(api_key="session-only-key")

    def test_empty_model_response_is_an_explicit_error(self):
            client = SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(
                        create=Mock(return_value=SimpleNamespace(
                            choices=[SimpleNamespace(message=SimpleNamespace(content=" "))]
                        ))
                    )
                )
            )
            itinerary = {
                "destination": "Kyoto",
                "interests": ["culture"],
                "currency": "USD",
                "budget": {},
                "days": [],
                "unpriced_activities": [],
            }
            with (
                patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
                patch("travel_concierge.llm_assistant.OpenAI", return_value=client),
            ):
                with self.assertRaisesRegex(OpenAIError, "empty trip briefing"):
                    ItineraryAssistant().create_briefing(itinerary)


if __name__ == "__main__":
    unittest.main()
