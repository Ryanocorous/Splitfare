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

# V2.3.1 - Modernised code and updated python terminology and identifiers. This version is not 100% functional, more to come soon.

from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol
from urllib.parse import urlencode

import json
import re

try:
    import requests
except ImportError:  # checking for depends
    requests = None


# URL that let's us find purchase links, scrape this
OFFICIAL_JOURNEY_PLANNER_URL = "https://www.nationalrail.co.uk/journey-planner/"

# BR fares emdpoint
BRFARES_LEGACY_QUERY_URL = "https://gw.brfares.com/legacy_querysimple"

# The stuff we need
SOURCE_OFFICIAL = "official"
SOURCE_BRFARES = "brfares"
SOURCE_DEMO = "demo"
SOURCE_LABELS = {
    SOURCE_OFFICIAL: "National Rail official links",
    SOURCE_BRFARES: "BR Fares legacy API",
    SOURCE_DEMO: "Demo indexed prices",
}

# Common codes for railcards, the API uses these codes so i matched
RAILCARD_OPTIONS = {
    "": "No railcard",
    "YNG": "16-25 Railcard",
    "TST": "26-30 Railcard",
    "SRN": "Senior Railcard",
    "DIS": "Disabled Persons Railcard",
    "FAM": "Family & Friends Railcard",
    "NEW": "Network Railcard",
    "HMF": "HM Forces Railcard",
    "TWO": "Two Together Railcard",
    "VTR": "Veterans Railcard",
}

# This is how long it holds onto the prices for. Indexing allows easier comparisons. 
INDEX_WINDOW_OPTIONS = [5, 10, 20, 30, 45, 60]


class SplitFareError(Exception):
    """Base error for the split fare project."""


class ValidationError(SplitFareError):
    """Raised when user input is invalid."""


class ProviderError(SplitFareError):
    """Raised when a fare provider cannot return a price."""


@dataclass(frozen=True)
class Station:
    """This stores one station using its 3-letter CRS code."""

    code: str
    name: str = ""

    def __post_init__(self) -> None:
        clean_code = normalise_station_code(self.code)
        object.__setattr__(self, "code", clean_code)
        if not self.name:
            object.__setattr__(self, "name", clean_code)

    def __str__(self) -> str:
        return f"{self.name} [{self.code}]"


@dataclass(frozen=True) # frozen=true https://www.youtube.com/watch?v=XS088Opj9o0 -- freezes user options
class SearchOptions:
    """This stores user options for one search."""

    source: str
    origin: Station
    destination: Station
    travel_date: str
    start_time: str
    calling_points: tuple[Station, ...] = ()
    railcard: str = ""
    index_minutes: int = 5
    custom_index_minutes: int | None = None
    adults: int = 1
    children: int = 0

    @property
    def active_index_minutes(self) -> int:
        """This returns the chosen index window in minutes."""

        if self.custom_index_minutes is not None:
            return self.custom_index_minutes
        return self.index_minutes

    @property
    def all_stops(self) -> tuple[Station, ...]:
        """This returns origin, intermediate stops, and destination."""

        return (self.origin, *self.calling_points, self.destination)


@dataclass(frozen=True)
class FareQuote:
    """This stores one price quote between two stations."""

    origin: Station
    destination: Station
    price: Decimal | None
    source: str
    ticket_name: str = ""
    route: str = ""
    notes: str = ""
    check_url: str = ""
    buy_url: str = ""

    @property
    def price_label(self) -> str:
        """This formats the price for display."""

        if self.price is None:
            return "Price unknown"
        return f"£{money(self.price)}"


@dataclass(frozen=True)
class SplitSegment:
    """This is one ticket the user would buy in the split plan."""

    origin: Station
    destination: Station
    quote: FareQuote
    start_index: int
    end_index: int


@dataclass(frozen=True)
class SplitResult:
    """This stores the direct result and the cheapest split result."""

    source: str
    travel_date: str
    departure_time: str
    railcard: str
    index_minutes: int
    direct_quote: FareQuote
    segments: tuple[SplitSegment, ...]
    total_price: Decimal | None
    checked_times: tuple[str, ...]
    notes: tuple[str, ...] = ()

    @property
    def saving(self) -> Decimal | None:
        """This calculates the saving compared with the direct ticket."""

        if self.direct_quote.price is None or self.total_price is None:
            return None
        return self.direct_quote.price - self.total_price

    @property
    def total_label(self) -> str:
        if self.total_price is None:
            return "Price unknown"
        return f"£{money(self.total_price)}"

    @property
    def saving_label(self) -> str:
        saving = self.saving
        if saving is None:
            return "Unknown"
        return f"£{money(saving)}"


class FareProvider(Protocol):
    """This describes a provider that can return a fare quote."""

    label: str

    def quote(self, origin: Station, destination: Station, options: SearchOptions, departure_time: str) -> FareQuote:
        """Return a fare quote for one origin-destination pair."""


class OfficialLinkProvider:
    """
    This provider does not scrape prices.

    It creates official National Rail links so the user can check and buy manually.
    """

    label = SOURCE_LABELS[SOURCE_OFFICIAL]

    def quote(self, origin: Station, destination: Station, options: SearchOptions, departure_time: str) -> FareQuote:
        url = build_national_rail_url(
            origin=origin.code,
            destination=destination.code,
            travel_date=options.travel_date,
            departure_time=departure_time,
            railcard=options.railcard,
            adults=options.adults,
            children=options.children,
        )
        return FareQuote(
            origin=origin,
            destination=destination,
            price=None,
            source=self.label,
            ticket_name="Manual check",
            notes="Open the official link to check live ticket availability and buy.",
            check_url=url,
            buy_url=url,
        )


class DemoPriceProvider:
    """
    This is a free offline provider for testing the split algorithm and GUI.

    It is not real railway data. It deliberately makes some split tickets cheaper.
    """

    label = SOURCE_LABELS[SOURCE_DEMO]

    def quote(self, origin: Station, destination: Station, options: SearchOptions, departure_time: str) -> FareQuote:
        base = Decimal("8.00")
        code_gap = abs(sum(map(ord, origin.code)) - sum(map(ord, destination.code)))
        distance_part = Decimal(code_gap % 37) * Decimal("0.85")
        time_part = Decimal(time_to_minutes(departure_time) % 60) * Decimal("0.03")
        railcard_discount = Decimal("0.67") if options.railcard else Decimal("1.00")

        # This makes long direct legs more expensive, so split searching is visible.
        long_leg_penalty = Decimal("9.50") if code_gap > 20 else Decimal("0.00")
        price = (base + distance_part + time_part + long_leg_penalty) * railcard_discount
        price = money(price)

        url = build_national_rail_url(
            origin=origin.code,
            destination=destination.code,
            travel_date=options.travel_date,
            departure_time=departure_time,
            railcard=options.railcard,
            adults=options.adults,
            children=options.children,
        )
        return FareQuote(
            origin=origin,
            destination=destination,
            price=price,
            source=self.label,
            ticket_name="Demo single",
            route="Demo route",
            notes="Demo price only. Use the link to check real tickets.",
            check_url=url,
            buy_url=url,
        )


class BRFaresProvider:
    """
    This provider uses the BR Fares legacy JSON endpoint.

    It chooses the cheapest visible walk-up standard non-season fare. This is useful
    for comparison, but it does not prove Advance-ticket availability.
    """

    label = SOURCE_LABELS[SOURCE_BRFARES]

    def __init__(self, timeout_seconds: int = 20) -> None:
        if requests is None:
            raise ProviderError("Install requests first: pip install requests")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.cache: dict[tuple[str, str, str], FareQuote] = {}

    def quote(self, origin: Station, destination: Station, options: SearchOptions, departure_time: str) -> FareQuote:
        cache_key = (origin.code, destination.code, options.railcard)
        if cache_key in self.cache:
            cached = self.cache[cache_key]
            return replace_quote_links(cached, options, departure_time)

        params = {"orig": origin.code, "dest": destination.code}
        if options.railcard:
            params["rlc"] = options.railcard

        check_url = f"{BRFARES_LEGACY_QUERY_URL}?{urlencode(params)}"
        buy_url = build_national_rail_url(
            origin=origin.code,
            destination=destination.code,
            travel_date=options.travel_date,
            departure_time=departure_time,
            railcard=options.railcard,
            adults=options.adults,
            children=options.children,
        )

        try:
            response = self.session.get(
                BRFARES_LEGACY_QUERY_URL,
                params=params,
                timeout=self.timeout_seconds,
                headers={"Accept-Encoding": "gzip, deflate", "User-Agent": "SplitFarePrototype/0.3"},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # network, JSON, HTTP
            return FareQuote(
                origin=origin,
                destination=destination,
                price=None,
                source=self.label,
                ticket_name="Unavailable",
                notes=f"BR Fares request failed: {exc}",
                check_url=check_url,
                buy_url=buy_url,
            )

        best = choose_best_brfare(payload)
        if best is None:
            quote = FareQuote(
                origin=origin,
                destination=destination,
                price=None,
                source=self.label,
                ticket_name="No suitable fare found",
                notes="No walk-up standard non-season fare was found in the response.",
                check_url=check_url,
                buy_url=buy_url,
            )
        else:
            quote = FareQuote(
                origin=origin,
                destination=destination,
                price=best["price"],
                source=self.label,
                ticket_name=best["ticket_name"],
                route=best["route"],
                notes="BR Fares reference price. Open National Rail to buy/check availability.",
                check_url=check_url,
                buy_url=buy_url,
            )

        self.cache[cache_key] = quote
        return quote


def replace_quote_links(quote: FareQuote, options: SearchOptions, departure_time: str) -> FareQuote:
    """This reuses a cached price but updates the National Rail check link."""

    buy_url = build_national_rail_url(
        origin=quote.origin.code,
        destination=quote.destination.code,
        travel_date=options.travel_date,
        departure_time=departure_time,
        railcard=options.railcard,
        adults=options.adults,
        children=options.children,
    )
    return FareQuote(
        origin=quote.origin,
        destination=quote.destination,
        price=quote.price,
        source=quote.source,
        ticket_name=quote.ticket_name,
        route=quote.route,
        notes=quote.notes,
        check_url=quote.check_url,
        buy_url=buy_url,
    )


def choose_best_brfare(payload: dict) -> dict | None:
    """This chooses the cheapest useful fare from a BR Fares JSON response."""

    fares = payload.get("fares", [])
    candidates: list[dict] = []

    for fare in fares:
        adult = fare.get("adult", {})
        pence = adult.get("fare")
        if not isinstance(pence, int) or pence <= 10:
            continue

        ticket = fare.get("ticket", {})
        ticket_type = ticket.get("type", {}).get("desc", "").upper()
        ticket_class = ticket.get("tclass", {}).get("desc", "").upper()
        category = fare.get("category", {}).get("desc", "").upper()

        # Avoid seasons and first-class fares in the basic MVP.
        if "SEASON" in ticket_type:
            continue
        if "1ST" in ticket_class or "FIRST" in ticket_class:
            continue

        # Prefer walk-up fares. Quota fares may exist but not be purchasable.
        if category and category != "WALKUP":
            continue

        candidates.append(
            {
                "price": money(Decimal(pence) / Decimal(100)),
                "ticket_name": ticket.get("name", "Unknown ticket").strip(),
                "route": fare.get("route", {}).get("name", "").strip(),
                "raw": fare,
            }
        )

    if not candidates:
        return None

    return min(candidates, key=lambda item: item["price"])


class SplitFareFinder:
    """This is the algorithm that finds the cheapest split-ticket combination."""

    def __init__(self, provider: FareProvider) -> None:
        self.provider = provider

    def find_for_time(self, options: SearchOptions, departure_time: str) -> SplitResult:
        """This compares every possible split for one departure time."""

        stops = options.all_stops
        edge_quotes: dict[tuple[int, int], FareQuote] = {}

        for start in range(len(stops) - 1):
            for end in range(start + 1, len(stops)):
                quote = self.provider.quote(stops[start], stops[end], options, departure_time)
                edge_quotes[(start, end)] = quote

        direct_quote = edge_quotes[(0, len(stops) - 1)]
        if direct_quote.price is None:
            return SplitResult(
                source=self.provider.label,
                travel_date=options.travel_date,
                departure_time=departure_time,
                railcard=options.railcard,
                index_minutes=options.active_index_minutes,
                direct_quote=direct_quote,
                segments=tuple(
                    SplitSegment(
                        origin=stops[index],
                        destination=stops[index + 1],
                        quote=edge_quotes[(index, index + 1)],
                        start_index=index,
                        end_index=index + 1,
                    )
                    for index in range(len(stops) - 1)
                ),
                total_price=None,
                checked_times=(departure_time,),
                notes=("This source did not return automated prices. Use the links to check/buy manually.",),
            )

        costs = [Decimal("Infinity")] * len(stops)
        previous: list[int | None] = [None] * len(stops)
        costs[0] = Decimal("0.00")

        for start in range(len(stops) - 1):
            if costs[start].is_infinite():
                continue
            for end in range(start + 1, len(stops)):
                quote = edge_quotes[(start, end)]
                if quote.price is None:
                    continue
                new_cost = costs[start] + quote.price
                if new_cost < costs[end]:
                    costs[end] = new_cost
                    previous[end] = start

        segments = rebuild_segments(stops, edge_quotes, previous)
        total_price = None if costs[-1].is_infinite() else money(costs[-1])

        return SplitResult(
            source=self.provider.label,
            travel_date=options.travel_date,
            departure_time=departure_time,
            railcard=options.railcard,
            index_minutes=options.active_index_minutes,
            direct_quote=direct_quote,
            segments=tuple(segments),
            total_price=total_price,
            checked_times=(departure_time,),
        )

    def find_indexed(self, options: SearchOptions) -> SplitResult:
        """This checks several times and returns the cheapest result."""

        times = generate_index_times(options.start_time, options.active_index_minutes)
        results = [self.find_for_time(options, value) for value in times]

        priced_results = [result for result in results if result.total_price is not None]
        if priced_results:
            best = min(priced_results, key=lambda result: result.total_price or Decimal("Infinity"))
        else:
            best = results[0]

        return SplitResult(
            source=best.source,
            travel_date=best.travel_date,
            departure_time=best.departure_time,
            railcard=best.railcard,
            index_minutes=best.index_minutes,
            direct_quote=best.direct_quote,
            segments=best.segments,
            total_price=best.total_price,
            checked_times=tuple(times),
            notes=best.notes,
        )


def rebuild_segments(
    stops: tuple[Station, ...],
    edge_quotes: dict[tuple[int, int], FareQuote],
    previous: list[int | None],
) -> list[SplitSegment]:
    """This rebuilds the cheapest path after dynamic programming."""

    end = len(stops) - 1
    segments: list[SplitSegment] = []

    while previous[end] is not None:
        start = previous[end]
        quote = edge_quotes[(start, end)]
        segments.append(
            SplitSegment(
                origin=stops[start],
                destination=stops[end],
                quote=quote,
                start_index=start,
                end_index=end,
            )
        )
        end = start

    segments.reverse()
    return segments


def provider_from_source(source: str) -> FareProvider:
    """This creates the selected fare provider."""

    if source == SOURCE_OFFICIAL:
        return OfficialLinkProvider()
    if source == SOURCE_BRFARES:
        return BRFaresProvider()
    if source == SOURCE_DEMO:
        return DemoPriceProvider()
    raise ValidationError(f"Unknown source: {source}")


def run_search(options: SearchOptions) -> SplitResult:
    """This runs the full split-fare search for the selected options."""

    validate_options(options)
    provider = provider_from_source(options.source)
    finder = SplitFareFinder(provider)
    return finder.find_indexed(options)


def validate_options(options: SearchOptions) -> None:
    """This checks the search before running it."""

    if options.source not in SOURCE_LABELS:
        raise ValidationError("Choose a valid source.")
    if options.origin.code == options.destination.code:
        raise ValidationError("Origin and destination cannot be the same.")
    if options.adults < 1:
        raise ValidationError("At least one adult is required.")
    if options.children < 0:
        raise ValidationError("Children cannot be negative.")
    if options.active_index_minutes < 0 or options.active_index_minutes > 240:
        raise ValidationError("Index minutes must be between 0 and 240.")
    parse_national_rail_date(options.travel_date)
    time_to_minutes(options.start_time)

# Building all the options
def build_options(
    source: str,
    origin: str,
    destination: str,
    travel_date: str,
    start_time: str,
    calling_points: str = "",
    railcard: str = "",
    index_minutes: int = 5,
    custom_index_minutes: int | None = None,
    adults: int = 1,
    children: int = 0,
) -> SearchOptions:
    """This converts raw form/CLI input into SearchOptions."""

    return SearchOptions(
        source=source,
        origin=Station(origin),
        destination=Station(destination),
        travel_date=parse_date_input(travel_date),
        start_time=parse_time_input(start_time),
        calling_points=tuple(Station(code) for code in parse_calling_points(calling_points)),
        railcard=railcard.strip().upper(),
        index_minutes=int(index_minutes),
        custom_index_minutes=int(custom_index_minutes) if custom_index_minutes not in (None, "", 0, "0") else None,
        adults=int(adults),
        children=int(children),
    )


def build_national_rail_url(
    origin: str,
    destination: str,
    travel_date: str,
    departure_time: str,
    railcard: str = "",
    adults: int = 1,
    children: int = 0,
) -> str:
    """This builds a public National Rail journey planner link."""

    hour, minute = parse_time_input(departure_time).split(":")
    params = {
        "type": "single",
        "origin": normalise_station_code(origin),
        "destination": normalise_station_code(destination),
        "leavingType": "departing",
        "leavingDate": parse_date_input(travel_date),
        "leavingHour": hour,
        "leavingMin": minute,
        "adults": str(adults),
    }
    if children:
        params["children"] = str(children)
    if railcard:
        # National Rail may change railcard query parameter names. Keep this as a best-effort hint.
        params["railcard"] = railcard.upper()
    return f"{OFFICIAL_JOURNEY_PLANNER_URL}?{urlencode(params)}"


def parse_calling_points(raw: str) -> list[str]:
    """This parses comma/space separated calling point CRS codes."""

    if not raw.strip():
        return []
    parts = re.split(r"[ ,;\n\t]+", raw.strip())
    return [normalise_station_code(part) for part in parts if part.strip()]


def normalise_station_code(value: str) -> str:
    """This validates and normalises a 3-letter station CRS code."""

    code = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise ValidationError(f"Station code must be three letters: {value!r}")
    return code


def parse_time_input(value: str) -> str:
    """This converts time input into HH:MM."""

    raw = value.strip()
    if re.fullmatch(r"\d{1,2}", raw):
        raw = f"{int(raw):02d}:00"
    elif re.fullmatch(r"\d{3,4}", raw):
        raw = raw.zfill(4)
        raw = f"{raw[:2]}:{raw[2:]}"

    time_to_minutes(raw)
    return raw


def time_to_minutes(value: str) -> int:
    """This converts HH:MM to minutes after midnight."""

    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if not match:
        raise ValidationError(f"Time must be HH:MM, e.g. 09:30: {value!r}")
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValidationError(f"Invalid time: {value!r}")
    return hour * 60 + minute


def minutes_to_time(minutes: int) -> str:
    """This converts minutes after midnight back to HH:MM."""

    minutes = minutes % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def generate_index_times(start_time: str, index_minutes: int, step_minutes: int = 5) -> list[str]:
    """This creates times from start time to start time + index window."""

    start = time_to_minutes(start_time)
    if index_minutes < 0:
        raise ValidationError("Index minutes cannot be negative.")
    return [minutes_to_time(start + offset) for offset in range(0, index_minutes + 1, step_minutes)]


def parse_date_input(value: str) -> str:
    """This accepts +7, DDMMYY, DD/MM/YY, DD-MM-YYYY, or ISO YYYY-MM-DD."""

    raw = value.strip()
    if not raw:
        return (date.today() + timedelta(days=7)).strftime("%d%m%y")
    if raw.startswith("+"):
        return (date.today() + timedelta(days=int(raw[1:]))).strftime("%d%m%y")
    if re.fullmatch(r"\d{6}", raw):
        return parse_national_rail_date(raw)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        parsed = datetime.strptime(raw, "%Y-%m-%d").date()
        return parsed.strftime("%d%m%y")

    parts = re.split(r"[ /,\-]+", raw)
    if len(parts) < 2:
        raise ValidationError("Date must be DDMMYY, DD/MM/YY, YYYY-MM-DD, or +n.")
    day = int(parts[0])
    month = int(parts[1])
    year = int(parts[2]) if len(parts) > 2 else date.today().year
    if year < 100:
        year += 2000
    parsed = date(year, month, day)
    return parsed.strftime("%d%m%y")


def parse_national_rail_date(value: str) -> str:
    """This validates DDMMYY date format."""

    raw = value.strip()
    if not re.fullmatch(r"\d{6}", raw):
        raise ValidationError(f"Date must be DDMMYY: {value!r}")
    datetime.strptime(raw, "%d%m%y")
    return raw


def money(value: Decimal) -> Decimal:
    """This rounds money to two decimal places."""

    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def result_to_dict(result: SplitResult) -> dict:
    """This converts a result to plain dictionaries for templates or JSON."""

    return {
        "source": result.source,
        "travel_date": result.travel_date,
        "departure_time": result.departure_time,
        "railcard": result.railcard or "None",
        "index_minutes": result.index_minutes,
        "checked_times": result.checked_times,
        "direct": quote_to_dict(result.direct_quote),
        "segments": [
            {
                "origin": segment.origin.code,
                "destination": segment.destination.code,
                "price": segment.quote.price_label,
                "ticket_name": segment.quote.ticket_name,
                "route": segment.quote.route,
                "notes": segment.quote.notes,
                "check_url": segment.quote.check_url,
                "buy_url": segment.quote.buy_url,
            }
            for segment in result.segments
        ],
        "total": result.total_label,
        "saving": result.saving_label,
        "notes": result.notes,
    }


def quote_to_dict(quote: FareQuote) -> dict:
    """This converts one quote to a plain dictionary."""

    return {
        "origin": quote.origin.code,
        "destination": quote.destination.code,
        "price": quote.price_label,
        "ticket_name": quote.ticket_name,
        "route": quote.route,
        "notes": quote.notes,
        "check_url": quote.check_url,
        "buy_url": quote.buy_url,
    }


def dumps_result(result: SplitResult) -> str:
    """This formats a result as pretty JSON."""

    return json.dumps(result_to_dict(result), indent=2)
