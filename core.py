# .-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-.
# |                                                                                               |
# |       - This is originally ticketsplit by "https://github.com/gmoutsin/ticketsplit"           |
# |             -- I forked it because it was outdated python 2 code and started                  |
# |             -- to work on improving it and making it free to run for myself.                  |
# |             -- This is an old version, I'm just working on the new one atm                    | 
# |             -- and will commit when it's done.                                                |
# |                                                                                               |
# |       New features: HTML, Indexing, 100% free, multiple search methods, easy buy and more     |
# `-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-'

# V2.0.0 - Modernised code and updated python terminology and identifiers. This version is not 100% functional, more to come soon.

from __future__ import annotations


from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.parse import quote, urlencode

import argparse
import re
import sys

try:
    import requests
except ImportError:  # checked for dependencies
    requests = None 

try:
    from pyquery import PyQuery as PQ
except ImportError:  # only used when dependencies are missing 
    PQ = Any  # ignore[misc, assignment]


OFFICIAL_JOURNEY_PLANNER_URL = "https://www.nationalrail.co.uk/journey-planner/"

# Free/registration-based official data sources for a proper non-scraping version.
NATIONAL_RAIL_DATA_PORTAL_URL = "https://opendata.nationalrail.co.uk/"
RAIL_DATA_MARKETPLACE_URL = "https://raildata.org.uk/"

# LEGACY_OJP_SCRAPER_BASE_URL = "https://ojp.nationalrail.co.uk" - this was in the original but is old

DEFAULT_ORIGIN = "BHM"
DEFAULT_DESTINATION = "EDB"
DEFAULT_TIME = "09:00"
REQUEST_TIMEOUT_SECONDS = 30




@dataclass(frozen=True)
class Station:
    """This stores one train station and its 3-letter station code."""

    name: str
    code: str

    def __str__(self) -> str:
        return f"{self.name} [{self.code}]"


@dataclass
class CallingPoint:
    """This stores a station where the train stops."""

    station: Station
    arrival: str
    departure: str

    def __post_init__(self) -> None:
        # Some calling points only show arrival or departure.
        # If one is missing, we copy the available time.
        if not self.departure and self.arrival:
            self.departure = self.arrival
        elif self.departure and not self.arrival:
            self.arrival = self.departure

        if not self.arrival and not self.departure:
            raise ValueError(f"No arrival or departure time for {self.station}")

    def __str__(self) -> str:
        return f"{str(self.station):>40}  arr {self.arrival:<5}  dep {self.departure:<5}"


@dataclass
class Route:
    """This stores the selected train route and all its calling points."""

    origin: Station
    destination: Station
    travel_date: str
    departure: str
    arrival: str
    calling_points: list[CallingPoint] = field(default_factory=list)
    changes: list[Station] = field(default_factory=list)

    def add_calling_point(self, calling_point: CallingPoint) -> None:
        self.calling_points.append(calling_point)

    def __str__(self) -> str:
        lines = [
            f"From: {str(self.origin):<30}  To: {str(self.destination):<30}",
            f"      {self.departure:<30}      {self.arrival:<30}",
        ]

        if self.calling_points:
            lines.append("\nCalling points:")
            lines.extend(str(point) for point in self.calling_points)

        if self.changes:
            lines.append("\nChanges: " + ", ".join(str(change) for change in self.changes))

        return "\n".join(lines)


@dataclass
class RouteStop:
    """This is one stop in the route graph."""

    station: Station
    departure: str
    arrival: str


@dataclass
class SplitSegment:
    """This is one ticket segment in the cheapest split plan."""

    start_index: int
    end_index: int
    price: float


class NationalRailPrototypeClient:
    """
    This fetches train pages and prices.

    This is only a prototype scraper. Later, replace this class with official
    fares and timetable data.
    """

    def __init__(self, manual_choice: bool = False) -> None:
        self.session = requests.Session()
        self.manual_choice = manual_choice

        # This avoids fetching the same fare twice.
        self.price_cache: dict[tuple[str, str, str, str, str], float] = {}

    def journey_url(self, origin: str, destination: str, travel_date: str, time: str) -> str:
        """This builds a National Rail journey planner URL."""

        return (
            f"{BASE_URL}/service/timesandfares/"
            f"{origin}/{destination}/{travel_date}/{time}/dep"
        )

    def get_page(self, url: str) -> PQ:
        """This downloads a page and converts it into queryable HTML."""

        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return PQ(response.content)

    def journey_rows(self, page: PQ) -> list[PQ]:
        """This finds journey rows in the search results table."""

        return list(page("div#ctf-results table#oft tbody tr").items())

    def choose_trip(self, url: str) -> PQ:
        """This asks the user to choose one journey from the journey results."""

        page = self.get_page(url)
        rows = self.journey_rows(page)

        if not rows:
            raise RuntimeError(f"No trains found. URL: {url}")

        if len(rows) == 1:
            return rows[0]

        print(f"{len(rows)} trains were found.")
        print(f"{'No.':<4} {'Dep':<7} {'From':<7} {'To':<7} {'Arr':<7} {'Dur':<8} {'Chg':<4} {'Price':>8}")

        for index, row in enumerate(rows, start=1):
            print(
                f"{index:<4} "
                f"{text(row, 'td.dep'):<7} "
                f"{text(row, 'td.from abbr'):<7} "
                f"{text(row, 'td.to abbr'):<7} "
                f"{text(row, 'td.arr'):<7} "
                f"{text(row, 'td.dur').replace(' ', ''):<8} "
                f"{text(row, 'td.chg'):<4} "
                f"{price_text(row):>8}"
            )

        print(f"URL: {url}")

        while True:
            choice = input("Choose trip number: ").strip()

            if choice.isdigit():
                index = int(choice) - 1

                if 0 <= index < len(rows):
                    print("")
                    return rows[index]

            print("Invalid choice. Try again.")

    def fetch_selected_route(self, origin: str, destination: str, travel_date: str, time: str) -> Route:
        """This gets one selected route and its calling points."""

        url = self.journey_url(origin, destination, travel_date, time)
        trip = self.choose_trip(url)

        details_href = trip("td.info a").attr("href")

        if not details_href:
            raise RuntimeError("Could not find journey details link.")

        route = Route(
            origin=Station(
                clean_station_name(text(trip, "td.from")),
                text(trip, "td.from abbr"),
            ),
            destination=Station(
                clean_station_name(text(trip, "td.to")),
                text(trip, "td.to abbr"),
            ),
            travel_date=travel_date,
            departure=text(trip, "td.dep"),
            arrival=text(trip, "td.arr"),
        )

        details_url = quote(f"{BASE_URL}{details_href}", safe="/:?&=")
        details_page = self.get_page(details_url)

        changes_text = details_page("table#journey tbody td.changes").text().strip()
        number_of_legs = int(changes_text or "0") + 1

        legs = list(
            details_page(
                "div.journey-details table#journeyLegDetails tbody tr td.method"
            ).parent().items()
        )

        calling_point_tables = list(
            details_page(
                "div.journey-details table#journeyLegDetails "
                "tbody tr.callingpoints div.callingpointslide table tbody"
            ).items()
        )

        for leg_index in range(number_of_legs):
            if leg_index < len(calling_point_tables):
                self._add_leg_calling_points(route, calling_point_tables[leg_index])

            if leg_index != number_of_legs - 1 and leg_index + 1 < len(legs):
                self._add_change_point(route, legs[leg_index], legs[leg_index + 1])

        return route

    def _add_leg_calling_points(self, route: Route, table: PQ) -> None:
        """This adds all calling points for one leg of the journey."""

        for row in table("tr").items():
            station_code = text(row, "td.calling-points a abbr")
            station_name = clean_station_name(text(row, "td.calling-points a"))

            if not station_code or not station_name:
                continue

            route.add_calling_point(
                CallingPoint(
                    station=Station(station_name, station_code),
                    arrival=text(row, "td.arrives"),
                    departure=text(row, "td.departs"),
                )
            )

    def _add_change_point(self, route: Route, current_leg: PQ, next_leg: PQ) -> None:
        """This adds a change station between two legs."""

        station = Station(
            clean_station_name(text(current_leg, "td.destination a")),
            text(current_leg, "td.destination a abbr"),
        )

        route.changes.append(station)
        route.add_calling_point(
            CallingPoint(
                station=station,
                arrival=text(current_leg, "td.arriving"),
                departure=text(next_leg, "td.leaving"),
            )
        )

    def fetch_price(
        self,
        origin: Station,
        destination: Station,
        travel_date: str,
        departure_time: str,
        expected_arrival: str,
    ) -> float:
        """
        This finds the cheapest visible price between two stations.

        It tries to match the same departure time first, then the same arrival time.
        """

        cache_key = (
            origin.code,
            destination.code,
            travel_date,
            departure_time,
            expected_arrival,
        )

        if cache_key in self.price_cache:
            return self.price_cache[cache_key]

        search_time = five_minutes_before(departure_time)
        url = self.journey_url(origin.code, destination.code, travel_date, search_time)

        page = self.get_page(url)
        rows = self.journey_rows(page)

        matching_rows = [
            row for row in rows
            if text(row, "td.dep") == departure_time
        ]

        if len(matching_rows) > 1:
            arrival_matches = [
                row for row in matching_rows
                if text(row, "td.arr") == expected_arrival
            ]

            if len(arrival_matches) == 1:
                selected_row = arrival_matches[0]
            elif self.manual_choice:
                selected_row = self.choose_trip(url)
            else:
                selected_row = matching_rows[0]

        elif len(matching_rows) == 1:
            selected_row = matching_rows[0]

        elif self.manual_choice:
            selected_row = self.choose_trip(url)

        else:
            selected_row = first_train_after(rows, departure_time)

        price = parse_price(price_text(selected_row))
        self.price_cache[cache_key] = price

        return price


class SplitFareFinder:
    """This compares direct fare vs split-ticket fares."""

    def __init__(self, route: Route, client: NationalRailPrototypeClient) -> None:
        self.route = route
        self.client = client
        self.stops = self._build_stops()

        # This stores prices between every possible pair of stops.
        self.price_table: dict[tuple[int, int], float] = {}

        # These are used by the cheapest-price algorithm.
        self.previous_stop: list[Optional[int]] = [None] * len(self.stops)
        self.cheapest_costs: list[float] = [float("inf")] * len(self.stops)
        self.cheapest_costs[0] = 0.0

    def _build_stops(self) -> list[RouteStop]:
        """This builds the route graph from origin, calling points and destination."""

        stops = [
            RouteStop(
                station=self.route.origin,
                departure=self.route.departure,
                arrival=self.route.departure,
            )
        ]

        for point in self.route.calling_points:
            stops.append(
                RouteStop(
                    station=point.station,
                    departure=point.departure,
                    arrival=point.arrival,
                )
            )

        stops.append(
            RouteStop(
                station=self.route.destination,
                departure=self.route.arrival,
                arrival=self.route.arrival,
            )
        )

        return stops

    def fetch_all_prices(self) -> None:
        """This gets the fare for every valid pair of stops."""

        total_steps = len(self.stops) - 1

        print("Fetching prices...")
        print(f"Progress: 0/{total_steps}")

        for start_index in range(len(self.stops) - 1):
            start_stop = self.stops[start_index]

            for end_index in range(start_index + 1, len(self.stops)):
                end_stop = self.stops[end_index]

                price = self.client.fetch_price(
                    origin=start_stop.station,
                    destination=end_stop.station,
                    travel_date=self.route.travel_date,
                    departure_time=start_stop.departure,
                    expected_arrival=end_stop.arrival,
                )

                self.price_table[(start_index, end_index)] = price

            print(f"Progress: {start_index + 1}/{total_steps}")

        print("")

    def find_cheapest_split(self) -> list[SplitSegment]:
        """This uses dynamic programming to find the cheapest ticket combination."""

        for start_index in range(len(self.stops) - 1):
            for end_index in range(start_index + 1, len(self.stops)):
                price = self.price_table[(start_index, end_index)]
                new_cost = self.cheapest_costs[start_index] + price

                if new_cost < self.cheapest_costs[end_index]:
                    self.cheapest_costs[end_index] = new_cost
                    self.previous_stop[end_index] = start_index

        return self._rebuild_segments()

    def _rebuild_segments(self) -> list[SplitSegment]:
        """This rebuilds the best split-ticket path after dynamic programming."""

        segments: list[SplitSegment] = []
        end_index = len(self.stops) - 1

        while self.previous_stop[end_index] is not None:
            start_index = self.previous_stop[end_index]
            price = self.price_table[(start_index, end_index)]

            segments.append(
                SplitSegment(
                    start_index=start_index,
                    end_index=end_index,
                    price=price,
                )
            )

            end_index = start_index

        segments.reverse()
        return segments

    def print_price_table(self) -> None:
        """This prints all checked ticket prices."""

        print("Ticket prices:")

        header = "      " + "".join(
            f"{stop.station.code:>8}"
            for stop in self.stops[1:]
        )

        print(header)

        for start_index, start_stop in enumerate(self.stops[:-1]):
            row = f"{start_stop.station.code:>5}"

            for _ in range(start_index):
                row += f"{'.':>8}"

            for end_index in range(start_index + 1, len(self.stops)):
                price = self.price_table.get((start_index, end_index), float("inf"))
                row += f"{price:>8.2f}"

            print(row)

        print("")

    def print_cheapest_plan(self, segments: list[SplitSegment]) -> None:
        """This prints the final cheapest split-ticket plan."""

        direct_price = self.price_table[(0, len(self.stops) - 1)]
        split_price = self.cheapest_costs[-1]

        print("Result:")
        print(f"Direct ticket: £{direct_price:.2f}")
        print(f"Cheapest found: £{split_price:.2f}")
        print(f"Saving: £{direct_price - split_price:.2f}")
        print("")

        if len(segments) <= 1:
            print("The direct ticket is cheapest.")
            return

        print("Cheapest split combination:")

        for segment in segments:
            start_stop = self.stops[segment.start_index]
            end_stop = self.stops[segment.end_index]

            print(
                f"- {start_stop.station} {start_stop.departure} "
                f"to {end_stop.station} {end_stop.arrival}: "
                f"£{segment.price:.2f}"
            )


def text(row: PQ, selector: str) -> str:
    """This safely extracts text from one HTML row."""

    return row(selector).text().strip()


def price_text(row: PQ) -> str:
    """This extracts the visible ticket price text."""

    return text(row, "td.fare label") or text(row, "td.fare div label")


def parse_price(raw_price: str) -> float:
    """This converts a price like £42.30 into a float."""

    match = re.search(r"([0-9]+(?:\.[0-9]{1,2})?)", raw_price)

    if not match:
        raise ValueError(f"Could not parse price from: {raw_price!r}")

    return float(match.group(1))


def clean_station_name(raw_name: str) -> str:
    """This removes the station code from names like Birmingham [BHM]."""

    return raw_name.split("[")[0].strip()


def first_train_after(rows: list[PQ], departure_time: str) -> PQ:
    """This chooses the first train after the requested departure time."""

    wanted = time_to_minutes(departure_time)

    for row in rows:
        row_time = text(row, "td.dep")

        if row_time and time_to_minutes(row_time) >= wanted:
            print(
                f"No exact train match. Chose train leaving at {row_time} "
                f"with price {price_text(row)}."
            )
            return row

    if not rows:
        raise RuntimeError("No train rows found.")

    return rows[-1]


def five_minutes_before(time_text: str) -> str:
    """This subtracts 5 minutes because the search page may need an earlier search time."""

    total_minutes = max(time_to_minutes(time_text) - 5, 0)
    hours = total_minutes // 60
    minutes = total_minutes % 60

    return f"{hours:02d}{minutes:02d}"


def time_to_minutes(time_text: str) -> int:
    """This converts HH:MM into minutes after midnight."""

    hours, minutes = time_text.split(":")
    return int(hours) * 60 + int(minutes)


def parse_time_input(raw_time: str, default: str = DEFAULT_TIME) -> str:
    """This normalises user time input into HH:MM."""

    raw_time = raw_time.strip()

    if not raw_time:
        return default

    if raw_time.isdigit() and len(raw_time) <= 2:
        return f"{int(raw_time):02d}:00"

    if re.fullmatch(r"\d{3,4}", raw_time):
        raw_time = raw_time.zfill(4)
        return f"{raw_time[:2]}:{raw_time[2:]}"

    return raw_time


def default_travel_date() -> date:
    """This returns next week's date."""

    return date.today() + timedelta(days=7)


def parse_date_input(raw_date: str) -> str:
    """
    This converts date input into National Rail format DDMMYY.

    Accepted examples:
    - empty input = next week
    - +7 = seven days from today
    - 01 07 26
    - 01/07/26
    - 01-07-2026
    """

    raw_date = raw_date.strip()

    if not raw_date:
        return format_national_rail_date(default_travel_date())

    if raw_date.startswith("+"):
        return format_national_rail_date(
            date.today() + timedelta(days=int(raw_date[1:]))
        )

    parts = re.split(r"[ /,\-]+", raw_date)

    if len(parts) < 2:
        raise ValueError("Date must include at least day and month.")

    day = int(parts[0])
    month = int(parts[1])
    year = int(parts[2]) if len(parts) > 2 else date.today().year

    if year < 100:
        year += 2000

    return f"{day:02d}{month:02d}{str(year)[2:]}"


def format_national_rail_date(value: date) -> str:
    """This formats a date as DDMMYY."""

    return value.strftime("%d%m%y")


def prompt_with_default(label: str, default: str) -> str:
    """This asks the user for a value, using a default if they press Enter."""

    user_input = input(f"{label} [{default}]: ").strip()
    return user_input or default


def main() -> None:
    """This is the main script to compare direct fares with split-ticket fares."""

    print("SplitFare prototype")
    print("This script compares direct rail tickets with split-ticket combinations.")
    print("")

    origin = prompt_with_default("Travelling from station code", DEFAULT_ORIGIN).upper()
    destination = prompt_with_default("Travelling to station code", DEFAULT_DESTINATION).upper()

    default_date = format_national_rail_date(default_travel_date())
    raw_date = input(f"Travelling date, or +n days from today [{default_date}]: ")
    travel_date = parse_date_input(raw_date)

    raw_time = input(f"Travelling time [{DEFAULT_TIME}]: ")
    travel_time = parse_time_input(raw_time)

    # National Rail URL wants time as HHMM, not HH:MM.
    search_time = travel_time.replace(":", "")

    print("")
    print(f"Searching {origin} to {destination} on {travel_date} at {travel_time}")
    print("")

    client = NationalRailPrototypeClient(manual_choice=False)

    route = client.fetch_selected_route(
        origin=origin,
        destination=destination,
        travel_date=travel_date,
        time=search_time,
    )

    print(route)
    print("")

    finder = SplitFareFinder(route, client)

    finder.fetch_all_prices()
    finder.print_price_table()

    segments = finder.find_cheapest_split()
    finder.print_cheapest_plan(segments)


if __name__ == "__main__":
    main()
