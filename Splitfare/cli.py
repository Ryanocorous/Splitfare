# terminal usage options

from __future__ import annotations

from .core import (
    INDEX_WINDOW_OPTIONS,
    RAILCARD_OPTIONS,
    SOURCE_BRFARES,
    SOURCE_DEMO,
    SOURCE_LABELS,
    SOURCE_OFFICIAL,
    SplitFareError,
    build_options,
    dumps_result,
    run_search,
)


def ask(prompt: str, default: str = "") -> str:
    """This asks a question and uses a default if the user presses Enter."""

    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def choose_source() -> str:
    """This asks which data source the user wants to use."""

    while True:
        print("Which would you like to use?")
        print(f"1) {SOURCE_LABELS[SOURCE_OFFICIAL]} - creates official check/buy links")
        print(f"2) {SOURCE_LABELS[SOURCE_BRFARES]} - checks reference fares with BR Fares")
        print(f"3) {SOURCE_LABELS[SOURCE_DEMO]} - offline demo prices for testing")
        print("4) Options")
        choice = input("Choose 1, 2, 3, or 4: ").strip()

        if choice == "1":
            return SOURCE_OFFICIAL
        if choice == "2":
            return SOURCE_BRFARES
        if choice == "3":
            return SOURCE_DEMO
        if choice == "4":
            print_options_help()
        else:
            print("Please choose 1, 2, 3, or 4.\n")


def print_options_help() -> None:
    """This prints the available options."""

    print("\nOptions")
    print("- Origin and destination must be 3-letter station codes, e.g. COV, BHM, EUS.")
    print("- Calling points are optional. Add comma-separated station codes for split search.")
    print("- Railcard can be blank or one of these codes:")
    for code, label in RAILCARD_OPTIONS.items():
        if code:
            print(f"  {code:<4} {label}")
    print("- Index minutes checks prices from the selected time up to that many minutes later.")
    print(f"- Preset index windows: {', '.join(str(v) for v in INDEX_WINDOW_OPTIONS)} minutes")
    print("- Use Demo mode first to test the app without network access.\n")


def choose_index_minutes() -> tuple[int, int | None]:
    """This asks for an index window, including custom."""

    print("Index price window:")
    for index, value in enumerate(INDEX_WINDOW_OPTIONS, start=1):
        print(f"{index}) {value} minutes")
    print("7) Custom")

    choice = ask("Choose", "1")
    if choice == "7":
        custom = int(ask("Custom minutes", "15"))
        return 5, custom

    index = int(choice) - 1
    if index < 0 or index >= len(INDEX_WINDOW_OPTIONS):
        return 5, None
    return INDEX_WINDOW_OPTIONS[index], None


def main() -> None:
    """This is the terminal script for checking split-ticket prices."""

    print("SplitFare UK")
    print("This compares direct fares with split-ticket combinations.\n")

    source = choose_source()
    print("")

    origin = ask("From station code", "COV")
    destination = ask("To station code", "EUS")
    date_value = ask("Date: DDMMYY, YYYY-MM-DD, or +7", "+7")
    time_value = ask("Time", "09:00")
    calling_points = ask("Calling points for split search, comma-separated", "BHM,MKC")

    print("Railcard options: blank for none, or YNG, TST, SRN, DIS, FAM, NEW, HMF, TWO, VTR")
    railcard = ask("Railcard", "")

    index_minutes, custom_index_minutes = choose_index_minutes()

    try:
        options = build_options(
            source=source,
            origin=origin,
            destination=destination,
            travel_date=date_value,
            start_time=time_value,
            calling_points=calling_points,
            railcard=railcard,
            index_minutes=index_minutes,
            custom_index_minutes=custom_index_minutes,
        )
        result = run_search(options)
    except SplitFareError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)

    print("\nResult")
    print(dumps_result(result))
    print("\nOpen the buy_url links to check/purchase tickets on National Rail.")


if __name__ == "__main__":
    main()
