import os
import requests
from datetime import datetime, timedelta
import pytz

TOKEN = os.environ["EVENTBRITE_TOKEN"]
SERIES_ID = os.environ["SERIES_ID"]
SYDNEY_TZ = pytz.timezone("Australia/Sydney")

# Day mapping (0=Mon, 2=Wed, 3=Thu)
DAY_SCHEDULE = {
    0: {"target_weekday": 1, "slots": [(10,30),(11,0),(11,30)]},  # Run Mon -> Create Tue
    2: {"target_weekday": 3, "slots": [(14,0),(14,30),(15,0)]},   # Run Wed -> Create Thu
    3: {"target_weekday": 4, "slots": [(10,30),(11,0),(11,30)]},  # Run Thu -> Create Fri
}

def get_existing_utc_starts():
    """Fetch all existing occurrences to prevent duplicates."""
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
        
        continuation = data.get("pagination", {}).get("continuation")
        url = f"{url}?continuation={continuation}" if continuation and data.get("pagination", {}).get("has_more_items") else None
    return existing

def make_slots(target_date, hour_minute_pairs, existing_utc_starts):
    slots = []
    for hour, minute in hour_minute_pairs:
        # Properly localize the time to Sydney
        local_dt = SYDNEY_TZ.localize(datetime(
            target_date.year, target_date.month, target_date.day, hour, minute
        ))
        
        start_utc = local_dt.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        if start_utc in existing_utc_starts:
            print(f"⏭️ Skipping {start_utc} — already exists.")
            continue

        end_dt = local_dt + timedelta(minutes=30)
        end_utc = end_dt.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        slots.append({
            "start": {"timezone": "Australia/Sydney", "utc": start_utc},
            "end":   {"timezone": "Australia/Sydney", "utc": end_utc}
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
    
    existing = get_existing_utc_starts()
    slots = make_slots(target_date, schedule["slots"], existing)

    if not slots:
        print("✅ All slots already exist.")
        return

    print(f"Adding {len(slots)} occurrences to {target_date.date()}...")

    # FIX: Use the /dates/ sub-resource and simple payload structure
    url = f"https://www.eventbriteapi.com/v3/series/{SERIES_ID}/dates/"
    payload = {"series_dates": slots}

    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json"
        },
        json=payload
    )

    if response.ok:
        print("✅ Success: Occurrences added.")
    else:
        print(f"❌ Failed: {response.status_code} - {response.text}")

if __name__ == "__main__":
    main()
