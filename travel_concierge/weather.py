from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class WeatherSearchError(RuntimeError):
    """Raised when a current weather search cannot be completed."""


WEATHER_CODES = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


class OpenMeteoClient:
    geocoding_endpoint = "https://geocoding-api.open-meteo.com/v1/search"
    forecast_endpoint = "https://api.open-meteo.com/v1/forecast"
    forecast_horizon_days = 16

    def __init__(self, timeout: float = 20) -> None:
        self.timeout = timeout

    def get_forecast(self, location: str, start_date: str, end_date: str) -> dict[str, Any]:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        today = date.today()
        forecast_start = max(start, today)
        forecast_end = min(end, today + timedelta(days=self.forecast_horizon_days - 1))
        if forecast_start > forecast_end:
            return {
                "available": False,
                "message": (
                    "No forecast is available for the selected dates. "
                    "Open-Meteo forecasts cover today through the next 15 days."
                ),
                "source": "Open-Meteo",
            }

        locations = self._get_json(self.geocoding_endpoint, {
            "name": location,
            "count": 1,
            "language": "en",
            "format": "json",
        }).get("results", [])
        if not locations:
            raise WeatherSearchError(f"Could not find weather coordinates for {location!r}.")
        matched_location = locations[0]
        try:
            latitude = float(matched_location["latitude"])
            longitude = float(matched_location["longitude"])
        except (KeyError, TypeError, ValueError) as error:
            raise WeatherSearchError("Open-Meteo returned invalid location coordinates.") from error

        forecast = self._get_json(self.forecast_endpoint, {
            "latitude": latitude,
            "longitude": longitude,
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max"
            ),
            "start_date": forecast_start.isoformat(),
            "end_date": forecast_end.isoformat(),
            "timezone": "auto",
        })
        daily = forecast.get("daily")
        if not isinstance(daily, dict) or not isinstance(daily.get("time"), list):
            raise WeatherSearchError("Open-Meteo returned no daily forecast data.")

        reports = []
        for index, forecast_date in enumerate(daily["time"]):
            code = self._at(daily, "weather_code", index)
            reports.append({
                "date": forecast_date,
                "description": WEATHER_CODES.get(code, f"Weather code {code}"),
                "high": self._at(daily, "temperature_2m_max", index),
                "low": self._at(daily, "temperature_2m_min", index),
                "precipitation_probability": self._at(
                    daily, "precipitation_probability_max", index
                ),
            })

        warnings = []
        if forecast_start > start:
            warnings.append("Past days are omitted from the weather forecast.")
        if forecast_end < end:
            warnings.append(
                f"Forecasts are available only through {forecast_end.isoformat()}."
            )
        return {
            "available": bool(reports),
            "location": ", ".join(filter(None, (
                matched_location.get("name"),
                matched_location.get("admin1"),
                matched_location.get("country"),
            ))),
            "forecast": reports,
            "warnings": warnings,
            "source": "Open-Meteo",
        }

    def _get_json(self, endpoint: str, parameters: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"{endpoint}?{urlencode(parameters)}",
            headers={"Accept": "application/json", "User-Agent": "TravelConcierge/1.0"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except HTTPError as error:
            raise WeatherSearchError(
                f"Open-Meteo returned HTTP {error.code}."
            ) from error
        except (URLError, TimeoutError) as error:
            reason = getattr(error, "reason", error)
            raise WeatherSearchError(f"Could not reach Open-Meteo: {reason}") from error
        except json.JSONDecodeError as error:
            raise WeatherSearchError("Open-Meteo returned invalid JSON.") from error
        if not isinstance(payload, dict):
            raise WeatherSearchError("Open-Meteo returned an unexpected response.")
        if payload.get("error"):
            raise WeatherSearchError(f"Open-Meteo search failed: {payload.get('reason', 'unknown error')}")
        return payload

    @staticmethod
    def _at(values: dict[str, Any], key: str, index: int) -> Any:
        field = values.get(key)
        return field[index] if isinstance(field, list) and index < len(field) else None
