from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI, OpenAIError


class LLMConfigurationError(RuntimeError):
    """Raised when the optional AI trip briefing is not configured."""


class ItineraryAssistant:
    def __init__(self, api_key: str | None = None) -> None:
        api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise LLMConfigurationError(
                "Enter an OpenAI API key to request an AI-generated trip briefing."
            )
        self.client = OpenAI(api_key=api_key)
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def create_briefing(
        self,
        itinerary: dict[str, Any],
        weather: dict[str, Any] | None = None,
    ) -> str:
        summary = {
            "destination": itinerary["destination"],
            "interests": itinerary["interests"],
            "currency": itinerary["currency"],
            "budget": itinerary["budget"],
            "days": [
                {
                    "day": day["day"],
                    "items": [
                        {
                            "name": item["name"],
                            "kind": item["kind"],
                            "cost": item.get("cost"),
                            "matched_interests": item.get("matched_interests", []),
                        }
                        for item in day["items"]
                    ],
                }
                for day in itinerary["days"]
            ],
            "weather": weather.get("forecast", []) if weather and weather.get("available") else [],
            "unpriced_activities": itinerary["unpriced_activities"],
        }
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a travel planning assistant. Summarize the supplied itinerary "
                        "and give practical tips grounded only in the supplied data. Never invent "
                        "prices, weather, opening hours, or availability. Clearly call out "
                        "unknown activity admission prices and any budget exclusions."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(summary, ensure_ascii=False),
                },
            ],
        )
        if not response.choices:
            raise OpenAIError("The model returned no choices for the trip briefing.")
        briefing = response.choices[0].message.content
        if not briefing or not briefing.strip():
            raise OpenAIError("The model returned an empty trip briefing.")
        return briefing.strip()
