import os
import requests
from datetime import datetime, timedelta
import pytz

TOKEN = os.environ["EVENTBRITE_TOKEN"]
SERIES_ID = os.environ["SERIES_ID"]
EVENT_NAME = "TP Test"
SYDNEY_TZ = pytz.timezone("Australia/Sydney")

DAY_SCHEDULE = {
    0: {"target_weekday": 1, "slots": [(10,30),(11,0),(11,30)]},  # Mon → Tue
    2: {"target_weekday": 3, "slots": [(14,0),(14,30),(15,0)]},   # Wed → Thu
    3: {"target_weekday": 4, "slots": [(10,30),(11,0),(11,30)]},  # Thu → Fri
}

def get_existing_utc_starts():
    """Fetch all existing occurrences and return set of their UTC start strings."""
    existing = set()
    url = f"https://www.eventbriteapi.com/v3/series/{SERIES_ID}/events/"
    while url:
        resp = requests.get(url, headers={"Authorization": f"Bearer {TOKEN}"})
        if not resp.ok:
            print(f"⚠️ Could not fetch existing events: {resp.text}")
            break
        data = resp.json()
        for event in data.get("events", []):
            existing.add(event["start"]["utc"])
        # paginate
        continuation = data.get("pagination", {}).get("continuation")
        if continuation and data.get("pagination", {}).get("has_more_items"):
            url = f"https://www.eventbriteapi.com/v3/series/{SERIES_ID}/events/?continuation={continuation}"
        else:
            url = None
    print(f"Found {len(existing)} existing occurrences.")
    return existing

def make_slots(base_date, hour_minute_pairs, existing_utc_starts):
    slots = []
    for hour, minute in hour_minute_pairs:
        start = base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        end = start + timedelta(minutes=30)
        start_utc = start.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if start_utc in existing_utc_starts:
            print(f"⏭️  Skipping {start_utc} — already exists.")
            continue
        slots.append({
            "start": {"timezone": "Australia/Sydney", "utc": start_utc},
            "end":   {"timezone": "Australia/Sydney", "utc": end.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
            "capacity": 50
        })
    return slots

def main():
    now_sydney = datetime.now(SYDNEY_TZ)
    today = now_sydney.weekday()

    if today not in DAY_SCHEDULE:
        print(f"No schedule for {now_sydney.strftime('%A')} — skip.")
        return

    schedule = DAY_SCHEDULE[today]
    days_ahead = (schedule["target_weekday"] - today + 7) % 7
    target_date = now_sydney + timedelta(days=days_ahead)
    print(f"Target day: {target_date.strftime('%A %d %B %Y')}")

    existing = get_existing_utc_starts()
    slots = make_slots(target_date, schedule["slots"], existing)

    if not slots:
        print("✅ All slots already exist — nothing to create.")
        return

    print(f"Creating {len(slots)} new slot(s)...")

    payload = {
        "event": {
            "name": {"html": EVENT_NAME},
            "start": slots[0]["start"],
            "end":   slots[-1]["end"],
            "currency": "AUD"
        },
        "series_dates": {"create": slots}
    }

    response = requests.patch(
        f"https://www.eventbriteapi.com/v3/series/{SERIES_ID}/",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json"
        },
        json=payload
    )

    if response.ok:
        print("✅ Success:", response.json())
    else:
        print("❌ Failed:", response.status_code, response.text)
        exit(1)

if __name__ == "__main__":
    main()
