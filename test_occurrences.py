"""
Test harness for the occurrence creation workflow.

Bypasses the day-of-week guard and defaults to DRY-RUN mode.
Pass --live to actually submit requests to the Eventbrite API.
"""

import os
import sys
import json
import logging
import re
import requests
from datetime import datetime, timedelta
from pathlib import Path
import pytz
from dotenv import load_dotenv

# Load .env so credentials don't need to be exported to the shell
load_dotenv()

# Configure logging with timestamp and level for debuggability
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("EVENTBRITE_TOKEN", "")
SERIES_ID = _validated_series_id(os.environ.get("SERIES_ID", ""))
SYDNEY_TZ = pytz.timezone("Australia/Sydney")


def _validated_series_id(raw_series_id: str) -> str:
    series_id = (raw_series_id or "").strip()
    if not series_id or not re.fullmatch(r"\d+", series_id):
        raise ValueError("SERIES_ID must be a non-empty numeric Eventbrite event ID.")
    return series_id

# Default to dry-run unless --live is explicitly passed
DRY_RUN = "--live" not in sys.argv

# Maps the trigger weekday to the target weekday and its time slots
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
        logger.debug("Fetching existing events (page %d): %s", page, url)
        resp = requests.get(url, headers={"Authorization": f"Bearer {TOKEN}"})

        if not resp.ok:
            logger.error(
                "Failed to fetch existing events: HTTP %d - %s",
                resp.status_code,
                resp.text,
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
    Returns a list of dicts containing the API payload, UTC start, and local time for logging.
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
            logger.info(
                "Skipping %s (%s) -- occurrence already exists",
                start_utc_str,
                local_dt.strftime("%H:%M %Z"),
            )
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
            "local_time": local_dt.strftime("%H:%M %Z"),
            "recurrence_rule": recurrence_rule,
        })

    logger.info("Built %d new payload(s) to submit", len(payloads))
    return payloads


def main():
    now_sydney = datetime.now(SYDNEY_TZ)
    today = now_sydney.weekday()

    logger.info(
        "Test script started -- Sydney time: %s (%s)",
        now_sydney.strftime("%Y-%m-%d %H:%M:%S"),
        now_sydney.strftime("%A"),
    )
    logger.info("Mode: %s", "DRY RUN (no API writes)" if DRY_RUN else "LIVE -- will call Eventbrite API")

    # Use today's schedule if available, otherwise fall back to Wednesday's for testing
    if today in DAY_SCHEDULE:
        schedule = DAY_SCHEDULE[today]
        logger.info("Today (%s) is a scheduled day", now_sydney.strftime("%A"))
    else:
        fallback_day = 2
        schedule = DAY_SCHEDULE[fallback_day]
        logger.info(
            "Today (%s) is not a scheduled day, falling back to Wednesday's schedule "
            "(target_weekday=%d, slots=%s)",
            now_sydney.strftime("%A"),
            schedule["target_weekday"],
            schedule["slots"],
        )

    # Calculate how many days ahead the target date is from today
    days_ahead = (schedule["target_weekday"] - today + 7) % 7
    if days_ahead == 0:
        days_ahead = 7
    target_date = now_sydney + timedelta(days=days_ahead)

    logger.info("Target date for new occurrences: %s", target_date.strftime("%A %Y-%m-%d"))

    # Check if the target date is in the skip list before doing any API work
    skip_dates = load_skip_dates()
    if target_date.date() in skip_dates:
        logger.info("Target date %s is in skip_dates.txt, exiting", target_date.date())
        return

    # Fetch existing events to check for duplicates
    logger.info("Fetching existing occurrences from Eventbrite...")
    existing = get_existing_utc_starts()

    if existing:
        for e in sorted(existing):
            logger.debug("  Existing: %s", e)

    schedules = build_schedule_payloads(target_date, schedule["slots"], existing)

    if not schedules:
        logger.info("All slots already exist, nothing to add")
        return

    # Log the prepared payloads before deciding whether to submit
    logger.info("Prepared %d new schedule(s):", len(schedules))
    for s in schedules:
        logger.info("  %s -> UTC %s", s["local_time"], s["start_utc"])
        logger.debug("  RRULE: %s", s["recurrence_rule"])

    # In dry-run mode, dump the payloads and exit without making API calls
    if DRY_RUN:
        logger.info("DRY RUN -- skipping API calls. Run with --live to create occurrences.")
        for i, s in enumerate(schedules):
            logger.info("--- Payload %d/%d ---", i + 1, len(schedules))
            logger.info("\n%s", json.dumps(s["payload"], indent=2))
        return

    # Submit each schedule to the Eventbrite API
    validated_series_id = _validated_series_id(SERIES_ID)
    url = f"https://www.eventbriteapi.com/v3/events/{validated_series_id}/schedules/"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }

    for i, s in enumerate(schedules):
        logger.info("[%d/%d] Creating occurrence at %s", i + 1, len(schedules), s["start_utc"])
        response = requests.post(url, headers=headers, json=s["payload"])

        if response.ok:
            logger.info("  Created successfully (HTTP %d)", response.status_code)
            try:
                logger.debug("  Response body:\n%s", json.dumps(response.json(), indent=2))
            except (ValueError, TypeError):
                logger.debug("  Response body: %s", response.text)
        else:
            logger.error("  Request failed: HTTP %d - %s", response.status_code, response.text)

    logger.info("Finished processing all scheduled occurrences")


if __name__ == "__main__":
    main()
