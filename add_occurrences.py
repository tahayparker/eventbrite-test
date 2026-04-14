import os
import logging
import requests
from datetime import datetime, timedelta
from pathlib import Path
import pytz

# Configure logging with timestamp, level, and message for debuggability
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Auth token and series ID sourced from environment variables
TOKEN = os.environ["EVENTBRITE_TOKEN"]
SERIES_ID_RAW = os.environ["SERIES_ID"]
SYDNEY_TZ = pytz.timezone("Australia/Sydney")


def validate_series_id(series_id: str) -> str:
    """
    Validate Eventbrite series/event ID used in URL path construction.
    Event IDs are expected to be numeric; reject anything else to prevent
    path/query manipulation through untrusted input.
    """
    if not series_id or not series_id.isdigit():
        raise ValueError("SERIES_ID must be a non-empty numeric string")
    return series_id


SERIES_ID = validate_series_id(SERIES_ID_RAW)


def sanitize_for_log(value) -> str:
    """Return a log-safe string by removing CR/LF to prevent log injection."""
    return str(value).replace("\r", "").replace("\n", "")


# Maps the current weekday (when the script runs) to the target weekday and time slots.
# Keys are weekday indices (0=Mon, 2=Wed, 3=Thu) representing when the GitHub Action triggers.
# Each entry defines which day's slots to create and the (hour, minute) pairs for each occurrence.
DAY_SCHEDULE = {
    0: {"target_weekday": 1, "slots": [(10, 30), (11, 0), (11, 30)]},  # Mon run -> Tue slots
    2: {"target_weekday": 3, "slots": [(14, 0), (14, 30), (15, 0)]},   # Wed run -> Thu slots
    3: {"target_weekday": 4, "slots": [(10, 30), (11, 0), (11, 30)]},  # Thu run -> Fri slots
}

# Each occurrence lasts 30 minutes (in seconds)
OCCURRENCE_DURATION_SECS = 30 * 60

# Path to the skip dates file, relative to the script's directory
SKIP_DATES_FILE = Path(__file__).parent / "skip_dates.txt"


def load_skip_dates():
    """Read skip_dates.txt and return a set of dates to skip.

    Each line should contain a date in dd-mm-yyyy format.
    Blank lines and lines starting with '#' are ignored.
    Returns an empty set if the file doesn't exist.
    """
    if not SKIP_DATES_FILE.exists():
        logger.debug("No skip_dates.txt found at %s, skipping none", SKIP_DATES_FILE)
        return set()

    skip_dates = set()
    with open(SKIP_DATES_FILE, "r") as f:
        for line_num, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                parsed = datetime.strptime(line, "%d-%m-%Y").date()
                skip_dates.add(parsed)
            except ValueError:
                logger.warning(
                    "Invalid date format on line %d of skip_dates.txt: '%s' (expected dd-mm-yyyy)",
                    line_num,
                    line,
                )

    logger.info("Loaded %d skip date(s): %s", len(skip_dates), sorted(skip_dates))
    return skip_dates


def get_existing_utc_starts():
    """Paginate through all existing series events and collect their UTC start times.

    Returns a set of UTC start time strings to use for duplicate detection.
    """
    existing = set()
    url = f"https://www.eventbriteapi.com/v3/series/{SERIES_ID}/events/"
    page = 1

    while url:
        logger.debug("Fetching existing events (page %d): %s", page, sanitize_for_log(url))
        resp = requests.get(url, headers={"Authorization": f"Bearer {TOKEN}"})

        if not resp.ok:
            safe_resp_text = resp.text.replace("\r", "").replace("\n", "")
            logger.error(
                "Failed to fetch existing events: HTTP %d - %s",
                resp.status_code,
                safe_resp_text,
            )
            break

        data = resp.json()
        events = data.get("events", [])
        logger.debug("Retrieved %d events on page %d", len(events), page)

        for event in events:
            existing.add(event["start"]["utc"])

        # Handle pagination via continuation token
        pagination = data.get("pagination", {})
        continuation = pagination.get("continuation")
        has_more = pagination.get("has_more_items", False)

        if continuation and has_more:
            url = f"https://www.eventbriteapi.com/v3/series/{SERIES_ID}/events/?continuation={continuation}"
            page += 1
        else:
            url = None

    logger.info("Found %d existing occurrence(s) in the series", len(existing))
    return existing


def build_schedule_payloads(target_date, hour_minute_pairs, existing_utc_starts):
    """Construct schedule payloads for each time slot, skipping any that already exist.

    Uses iCalendar RRULE with COUNT=1 to create a single non-repeating occurrence per slot.
    Returns a list of dicts, each containing the API payload and the UTC start string.
    """
    payloads = []

    for hour, minute in hour_minute_pairs:
        # Localize to Sydney, then convert to UTC for the API
        local_dt = SYDNEY_TZ.localize(
            datetime(target_date.year, target_date.month, target_date.day, hour, minute)
        )
        utc_dt = local_dt.astimezone(pytz.utc)
        start_utc_str = utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        if start_utc_str in existing_utc_starts:
            logger.info("Skipping %s -- occurrence already exists", start_utc_str)
            continue

        # RRULE with FREQ=DAILY;COUNT=1 creates exactly one occurrence at DTSTART
        dtstart = utc_dt.strftime("%Y%m%dT%H%M%SZ")
        recurrence_rule = f"DTSTART:{dtstart}\nRRULE:FREQ=DAILY;COUNT=1"

        payloads.append({
            "payload": {
                "schedule": {
                    "occurrence_duration": OCCURRENCE_DURATION_SECS,
                    "recurrence_rule": recurrence_rule,
                }
            },
            "start_utc": start_utc_str,
        })

    logger.info("Built %d new payload(s) to submit", len(payloads))
    return payloads


def main():
    now_sydney = datetime.now(SYDNEY_TZ)
    today = now_sydney.weekday()

    logger.info(
        "Script started -- Sydney time: %s (%s)",
        now_sydney.strftime("%Y-%m-%d %H:%M:%S"),
        now_sydney.strftime("%A"),
    )

    if today not in DAY_SCHEDULE:
        logger.info("No schedule configured for %s, exiting", now_sydney.strftime("%A"))
        return

    schedule = DAY_SCHEDULE[today]

    # Calculate how many days ahead the target date is from today
    days_ahead = (schedule["target_weekday"] - today + 7) % 7
    target_date = now_sydney + timedelta(days=days_ahead)
    logger.info("Target date for new occurrences: %s", target_date.date())

    # Check if the target date is in the skip list before doing any API work
    skip_dates = load_skip_dates()
    if target_date.date() in skip_dates:
        logger.info("Target date %s is in skip_dates.txt, exiting", target_date.date())
        return

    existing = get_existing_utc_starts()
    schedules = build_schedule_payloads(target_date, schedule["slots"], existing)

    if not schedules:
        logger.info("All slots for %s already exist, nothing to do", target_date.date())
        return

    logger.info("Submitting %d occurrence(s) for %s", len(schedules), target_date.date())

    url = f"https://www.eventbriteapi.com/v3/events/{SERIES_ID}/schedules/"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }

    for i, s in enumerate(schedules):
        logger.info("[%d/%d] Creating occurrence at %s", i + 1, len(schedules), s["start_utc"])
        response = requests.post(url, headers=headers, json=s["payload"])

        if response.ok:
            logger.info("  Created successfully (HTTP %d)", response.status_code)
        else:
            safe_response_text = response.text.replace("\r", "\\r").replace("\n", "\\n")
            logger.error(
                "  Request failed: HTTP %d - %s", response.status_code, safe_response_text
            )

    logger.info("Finished processing all scheduled occurrences")


if __name__ == "__main__":
    main()
