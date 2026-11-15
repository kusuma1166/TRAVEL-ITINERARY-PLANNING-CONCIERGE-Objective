import unittest

from travel_concierge.planner_manager import PlannerManager
from travel_concierge.state import AppendOnlyRunLog


class TravelConciergeTests(unittest.TestCase):
    def setUp(self):
        self.manager = PlannerManager()

    def test_builds_daywise_itinerary_with_budgeted_choices(self):
        result = self.manager.build_itinerary({
            "origin": "Boston",
            "destination": "Kyoto",
            "days": 3,
            "travelers": 2,
            "budget": 5000,
            "interests": ["culture", "food"],
        })
        self.assertEqual(len(result["days"]), 3)
        self.assertTrue(all(day["items"] for day in result["days"]))
        kinds = {item["kind"] for day in result["days"] for item in day["items"]}
        self.assertTrue({"flight", "hotel", "activity"}.issubset(kinds))
        self.assertLessEqual(result["budget"]["spent"], result["budget"]["budget"])
        displayed_total = sum(
            item["cost"] for day in result["days"] for item in day["items"]
        )
        self.assertAlmostEqual(displayed_total, result["budget"]["spent"])

    def test_exceeded_choices_trigger_cheaper_alternatives_and_replan(self):
        result = self.manager.build_itinerary({
            "origin": "Boston",
            "destination": "Kyoto",
            "days": 3,
            "travelers": 1,
            "budget": 700,
            "interests": ["history"],
        })
        self.assertGreater(result["replans"], 0)
        self.assertLessEqual(result["budget"]["spent"], 700)
        self.assertTrue(any(event["action"] == "find_cheaper_flights" for event in result["trace"]))
        self.assertTrue(any(event["action"] == "find_cheaper_hotels" for event in result["trace"]))
        self.assertTrue(any(event["action"] == "find_cheaper_activities" for event in result["trace"]))

    def test_invalid_request_is_rejected(self):
        with self.assertRaises(ValueError):
            self.manager.build_itinerary({
                "origin": "Boston",
                "destination": "Kyoto",
                "days": 0,
                "budget": 1000,
                "interests": [],
            })

    def test_run_log_appends_events(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run_log.jsonl"
            log = AppendOnlyRunLog(path)
            self.manager.run_log = log
            self.manager.build_itinerary({
                "origin": "Boston",
                "destination": "Kyoto",
                "days": 1,
                "budget": 1500,
                "interests": ["art"],
            })
            first_size = path.stat().st_size
            self.manager.build_itinerary({
                "origin": "Boston",
                "destination": "Kyoto",
                "days": 1,
                "budget": 1500,
                "interests": ["art"],
            })
            self.assertGreater(path.stat().st_size, first_size)


if __name__ == "__main__":
    unittest.main()
