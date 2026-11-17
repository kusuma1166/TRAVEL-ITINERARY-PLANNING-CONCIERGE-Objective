from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class LiveSearchError(RuntimeError):
    """Raised when a configured live travel search cannot be completed."""


class SerpApiClient:
    """Small, explicit HTTP client for live Google Travel and Maps searches."""

    endpoint = "https://serpapi.com/search.json"

    def __init__(self, api_key: str | None = None, timeout: float = 30) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("SERPAPI_API_KEY")
        self.timeout = timeout

    def search(self, parameters: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise LiveSearchError(
                "Set SERPAPI_API_KEY to use live flight, hotel, and activity searches. "
                "Get a key at https://serpapi.com/users/sign_up."
            )

        query = urlencode({
            **parameters,
            "api_key": self.api_key,
            "no_cache": "true",
            "output": "json",
        })
        request = Request(
            f"{self.endpoint}?{query}",
            headers={"Accept": "application/json", "User-Agent": "TravelConcierge/1.0"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except HTTPError as error:
            try:
                error_payload = json.loads(error.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                error_payload = {}
            detail = error_payload.get("error") if isinstance(error_payload, dict) else None
            if isinstance(detail, str):
                detail = detail.strip()
                if self.api_key:
                    detail = detail.replace(self.api_key, "[redacted]")
                detail = detail[:500]
            else:
                detail = ""
            message = (
                f"SerpApi returned HTTP {error.code} for the "
                f"{parameters.get('engine')} search."
            )
            if detail:
                message += f" Details: {detail}"
            raise LiveSearchError(
                message
            ) from error
        except (URLError, TimeoutError) as error:
            reason = getattr(error, "reason", error)
            raise LiveSearchError(f"Could not reach SerpApi: {reason}") from error
        except json.JSONDecodeError as error:
            raise LiveSearchError("SerpApi returned invalid JSON.") from error

        if not isinstance(payload, dict):
            raise LiveSearchError("SerpApi returned an unexpected response.")
        if payload.get("error"):
            raise LiveSearchError(f"SerpApi search failed: {payload['error']}")
        return payload
