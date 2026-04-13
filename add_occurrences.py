import os
import json
import requests
from datetime import datetime, timedelta
import pytz

TOKEN = os.environ["EVENTBRITE_TOKEN"]
SERIES_ID = os.environ["SERIES_ID"]
EVENT_NAME = "TP Test"
SYDNEY_TZ = pytz.timezone("Australia/Sydney")

# Mon=0 Tue=1 Wed=2 Thu=3 Fri=4
DAY_SCHEDULE = {
    0: {"target_weekday": 1, "slots": [(10,30),(11,0),(11,30)]},  # Mon → Tue
    2: {"target_weekday": 3, "slots": [(14,0),(14,30),(15,0)]},   # Wed → Thu
    3: {"target_weekday": 4, "slots": [(10,30),(11,0),(11,30)]},  # Thu → Fri
}

def make_slots(base_date, hour_minute_pairs):
    slots = []
    for hour, minute in hour_minute_pairs:
        start = base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        end = start + timedelta(minutes=30)
        slots.append({
            "start": {"timezone": "Australia/Sydney", "utc": start.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
            "end":   {"timezone": "Australia/Sydney", "utc": end.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
            "capacity": 50
        })
    return slots

def main():
    now_sydney = datetime.now(SYDNEY_TZ)
    today = now_sydney.weekday()

    # DST guard: only run 11:00–13:00 Sydney window
    if not (11 <= now_sydney.hour < 13):
        print(f"Guard: Sydney time {now_sydney.strftime('%A %H:%M')} outside window — skip.")
        return

    if today not in DAY_SCHEDULE:
        print(f"Guard: {now_sydney.strftime('%A')} not a release day — skip.")
        return

    schedule = DAY_SCHEDULE[today]
    target_weekday = schedule["target_weekday"]
    days_ahead = (target_weekday - today + 7) % 7
    target_date = now_sydney + timedelta(days=days_ahead)

    slots = make_slots(target_date, schedule["slots"])
    print(f"Adding {len(slots)} slots for {target_date.strftime('%A %d %B %Y')}")

    payload = {
        "event": {
            "name": {"html": EVENT_NAME},
            "start": slots[0]["start"],
            "end":   slots[-1]["end"],
            "currency": "AUD"
        },
        "series_dates": {"create": slots}
    }

    response = requests.post(
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
