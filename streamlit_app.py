from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import streamlit as st
from openai import OpenAIError

from travel_concierge.activity_worker import MAX_INTERESTS
from travel_concierge.llm_assistant import ItineraryAssistant, LLMConfigurationError
from travel_concierge.live_search import LiveSearchError, SerpApiClient
from travel_concierge.planner_manager import PlannerManager
from travel_concierge.state import AppendOnlyRunLog
from travel_concierge.weather import OpenMeteoClient, WeatherSearchError


INTEREST_CHOICES = (
    "Architecture",
    "Art",
    "Culture",
    "Food",
    "History",
    "Museums",
    "Music",
    "Nature",
    "Nightlife",
    "Outdoor",
    "Shopping",
    "Sports",
)


def _render_itinerary(result: dict, weather: dict | None, briefing: str | None) -> None:
    budget = result["budget"]
    metrics = st.columns(3)
    metrics[0].metric("Priced subtotal", f"{result['currency']} {budget['spent']:,.2f}")
    metrics[1].metric("Budget remaining", f"{result['currency']} {budget['remaining']:,.2f}")
    metrics[2].metric("Travelers", result["travelers"])

    st.caption(result["budget_note"])
    if result["activity_search_warnings"]:
        for warning in result["activity_search_warnings"]:
            st.warning(warning)
    if result["unpriced_activities"]:
        st.info(
            "Admission prices are not included for: "
            + ", ".join(result["unpriced_activities"])
        )
    if briefing:
        st.subheader("AI trip briefing")
        st.info(briefing)

    st.subheader("Weather forecast")
    if weather is None:
        st.info("Weather forecast was not loaded.")
    elif not weather["available"]:
        st.info(weather["message"])
    else:
        st.caption(f"Forecast for {weather['location']} · Source: {weather['source']}")
        st.dataframe(weather["forecast"], hide_index=True, use_container_width=True)
        for warning in weather["warnings"]:
            st.warning(warning)

    for day in result["days"]:
        st.subheader(f"Day {day['day']}")
        if not day["items"]:
            st.caption("No options were available for this day.")
            continue
        for item in day["items"]:
            columns = st.columns([4, 1])
            columns[0].write(item["name"])
            columns[0].caption(item.get("schedule", item.get("source", item["kind"].title())))
            if item.get("matched_interests"):
                columns[0].caption("Interests: " + ", ".join(item["matched_interests"]))
            if item.get("address"):
                columns[0].caption(item["address"])
            if item.get("rating") is not None:
                columns[0].caption(f"Rating: {item['rating']}")
            cost = item.get("cost")
            columns[1].markdown(
                f"**{result['currency']} {cost:,.2f}**"
                if cost is not None
                else "**Price unavailable**"
            )
            source_url = item.get("source_url")
            if isinstance(source_url, str) and urlparse(source_url).scheme == "https":
                st.link_button(
                    "View live listing",
                    source_url,
                    key=f"listing-{day['day']}-{item['kind']}-{item['name']}",
                )
            if item["kind"] == "hotel" and day["day"] == 1:
                for index, booking in enumerate(item.get("booking_links", [])):
                    url = booking.get("url")
                    provider = booking.get("source") or "Hotel provider"
                    if isinstance(url, str) and urlparse(url).scheme == "https":
                        st.link_button(
                            f"Book via {provider}",
                            url,
                            key=f"hotel-booking-{index}",
                        )

    points = [
        {
            "lat": item["latitude"],
            "lon": item["longitude"],
            "place": item["name"],
        }
        for day in result["days"]
        for item in day["items"]
        if item["kind"] == "activity"
        and item.get("latitude") is not None
        and item.get("longitude") is not None
    ]
    st.subheader("Activity map")
    if points:
        st.map(pd.DataFrame(points))
    else:
        st.info("No activity coordinates were returned for this search.")

    with st.expander("Search and planning trace"):
        st.json(result["trace"])


def main() -> None:
    st.set_page_config(page_title="Travel Concierge", page_icon="✈️", layout="wide")
    st.title("Travel Itinerary Concierge")
    st.caption(
        "Build a trip from live flight, hotel, and destination searches. "
        "Prices and availability can change before booking."
    )
    with st.sidebar:
        st.header("API configuration")
        serpapi_key = st.text_input(
            "SerpApi key",
            value=os.environ.get("SERPAPI_API_KEY", ""),
            type="password",
            key="serpapi_api_key",
            help="Required for live flight, hotel, and activity searches.",
        )
        openai_key = st.text_input(
            "OpenAI key (optional)",
            value=os.environ.get("OPENAI_API_KEY", ""),
            type="password",
            key="openai_api_key",
            help="Used only when you opt in to an AI trip briefing.",
        )
        st.caption("Keys are held only in this active local app session, not project files or logs.")
        st.link_button("Get a SerpApi key", "https://serpapi.com/users/sign_up")
        st.link_button("Create an OpenAI key", "https://platform.openai.com/api-keys")
    if not serpapi_key:
        st.info("Enter a SerpApi key in the sidebar to enable live itinerary searches.")
    if not openai_key:
        st.caption("The optional AI briefing is disabled until an OpenAI key is entered.")

    default_departure = date.today() + timedelta(days=7)
    default_return = default_departure + timedelta(days=3)
    with st.form("trip_search"):
        st.subheader("Route")
        route = st.columns(2)
        origin = route[0].text_input("Origin city", value="Boston")
        origin_airport = route[0].text_input("Origin IATA airport code", value="BOS")
        destination = route[1].text_input("Destination city", value="Kyoto")
        destination_airport = route[1].text_input(
            "Destination IATA airport code", value="KIX"
        )

        st.subheader("Dates and budget")
        timing = st.columns(4)
        departure_date = timing[0].date_input(
            "Flight departure", value=default_departure, min_value=date.today()
        )
        return_date = timing[1].date_input(
            "Flight return", value=default_return, min_value=date.today()
        )
        hotel_check_in = timing[2].date_input(
            "Hotel check-in", value=default_departure, min_value=date.today()
        )
        hotel_check_out = timing[3].date_input(
            "Hotel check-out", value=default_return, min_value=date.today()
        )
        details = st.columns(3)
        travelers = details[0].number_input("Adult travelers", min_value=1, value=2, step=1)
        budget = details[1].number_input(
            "Trip budget", min_value=0.0, value=2500.0, step=100.0
        )
        currency = details[2].selectbox(
            "Currency", options=("USD", "EUR", "GBP", "JPY", "INR")
        )

        st.subheader("Interests")
        selected_interests = st.multiselect(
            f"Choose up to {MAX_INTERESTS}",
            options=INTEREST_CHOICES,
            default=["Culture", "Food"],
        )
        additional_interests = st.text_input(
            "Other interests (comma-separated)",
            placeholder="e.g. photography, gardens",
        )
        expenses = st.columns(2)
        food_allowance = expenses[0].number_input(
            "Food allowance per adult per day",
            min_value=0.0,
            value=0.0,
            step=5.0,
            help="Your estimate, not a live quote. Zero leaves food out of the budget.",
        )
        transport_allowance = expenses[1].number_input(
            "Local transport per adult per day",
            min_value=0.0,
            value=0.0,
            step=5.0,
            help="Your estimate, not a live quote. Zero leaves transport out of the budget.",
        )
        include_ai_briefing = st.checkbox(
            "Generate an AI briefing with OpenAI (sends trip details to OpenAI)",
            value=False,
            disabled=not bool(openai_key),
        )
        submitted = st.form_submit_button(
            "Search live itinerary",
            type="primary",
            use_container_width=True,
            disabled=not bool(serpapi_key.strip()),
        )

    if submitted:
        interests = selected_interests + [
            interest.strip()
            for interest in additional_interests.split(",")
            if interest.strip()
        ]
        unique_interests = list(dict.fromkeys(interest.casefold() for interest in interests))
        st.session_state.pop("itinerary", None)
        st.session_state.pop("weather", None)
        st.session_state.pop("briefing", None)
        if not unique_interests:
            st.error("Select or enter at least one interest.")
        elif len(unique_interests) > MAX_INTERESTS:
            st.error(f"Choose no more than {MAX_INTERESTS} interests to limit API searches.")
        else:
            request = {
                "origin": origin,
                "origin_airport": origin_airport,
                "destination": destination,
                "destination_airport": destination_airport,
                "departure_date": departure_date.isoformat(),
                "return_date": return_date.isoformat(),
                "hotel_check_in": hotel_check_in.isoformat(),
                "hotel_check_out": hotel_check_out.isoformat(),
                "travelers": travelers,
                "budget": budget,
                "currency": currency,
                "interests": interests,
                "food_budget_per_person_per_day": food_allowance,
                "transport_budget_per_person_per_day": transport_allowance,
            }
            try:
                with st.spinner("Searching live flights, hotels, and activities..."):
                    planner = PlannerManager(
                        AppendOnlyRunLog(Path(__file__).with_name("run_log.jsonl")),
                        search_client=SerpApiClient(api_key=serpapi_key.strip()),
                    )
                    st.session_state["itinerary"] = planner.build_itinerary(request)
            except (LiveSearchError, ValueError) as error:
                st.error(str(error))
            else:
                try:
                    st.session_state["weather"] = OpenMeteoClient().get_forecast(
                        destination,
                        hotel_check_in.isoformat(),
                        hotel_check_out.isoformat(),
                    )
                except WeatherSearchError as error:
                    st.session_state["weather"] = {
                        "available": False,
                        "message": str(error),
                    }
                if include_ai_briefing:
                    try:
                        st.session_state["briefing"] = ItineraryAssistant(
                            api_key=openai_key.strip() or None
                        ).create_briefing(
                            st.session_state["itinerary"],
                            st.session_state["weather"],
                        )
                    except (LLMConfigurationError, OpenAIError) as error:
                        st.warning(f"AI briefing unavailable: {error}")

    result = st.session_state.get("itinerary")
    if result:
        st.divider()
        st.header(f"Your trip to {result['destination']}")
        _render_itinerary(
            result,
            st.session_state.get("weather"),
            st.session_state.get("briefing"),
        )


if __name__ == "__main__":
    main()
