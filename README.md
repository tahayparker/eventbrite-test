# Eventbrite Series Occurrence Automation

Automatically creates recurring Eventbrite event occurrences on a weekly schedule using the [Eventbrite API v3](https://www.eventbrite.com/platform/api). Designed to run via GitHub Actions but can also be triggered manually or locally.

## Table of Contents

- [How It Works](#how-it-works)
- [Quick Start](#quick-start)
- [Prerequisites](#prerequisites)
- [Getting Your Environment Variables](#getting-your-environment-variables)
- [Local Setup](#local-setup)
- [Usage](#usage)
- [Skipping Dates](#skipping-dates)
- [GitHub Actions (Automated Schedule)](#github-actions-automated-schedule)
- [Adapting the Schedule](#adapting-the-schedule)
- [Project Structure](#project-structure)
- [Logging](#logging)
- [Troubleshooting](#troubleshooting)

---

## How It Works

The GitHub Action triggers at **12:00 PM Sydney time** on Monday, Wednesday, and Thursday, and creates event occurrences for the **next day**:

| Trigger Day | Creates Slots For | Time Slots (Sydney)        |
|-------------|-------------------|----------------------------|
| Monday      | Tuesday           | 10:30, 11:00, 11:30        |
| Wednesday   | Thursday          | 14:00, 14:30, 15:00        |
| Thursday    | Friday            | 10:30, 11:00, 11:30        |

Each occurrence is 30 minutes long. The script automatically:

- Checks for existing occurrences to **avoid duplicates**
- Skips dates listed in `skip_dates.txt`
- Converts Sydney local times to UTC for the API

---

## Quick Start

The fastest way to get up and running is to use this repo as a **template**:

1. Click **[Use this template](https://github.com/tahayparker/eventbrite-test/generate)** at the top of this repo (or **Fork** it)
2. In your new repo, go to **Settings** → **Secrets and variables** → **Actions**
3. Add two secrets: `EVENTBRITE_TOKEN` and `SERIES_ID` (see [Getting Your Environment Variables](#getting-your-environment-variables) below)
4. The workflow will start running automatically on schedule, or trigger it manually from the **Actions** tab

That's it - no local setup required if you just want the automation.

---

## Prerequisites

- Python 3.11+
- An [Eventbrite account](https://www.eventbrite.com/) with an existing **event series**
- A **private token** from Eventbrite

---

## Getting Your Environment Variables

You need two values: `EVENTBRITE_TOKEN` and `SERIES_ID`.

### `EVENTBRITE_TOKEN`

This is your **private token** used to authenticate API requests. This is _not_ the same as an API key or client secret.

1. Go to [eventbrite.com/account-settings/apps](https://www.eventbrite.com/account-settings/apps)
2. Sign in with the account that owns the event series
3. Click your app name to open its details
4. Copy the **Private token** value (a long alphanumeric string)

**Don't have an app yet?**

1. Go to [eventbrite.com/account-settings/apps](https://www.eventbrite.com/account-settings/apps) and click **Create API Key**
2. Fill in the required fields:
   | Field | Value |
   |---|---|
   | **Application Name** | `Event Automation` |
   | **Application URL** | `http://localhost` |
   | **Description** | `Automates adding weekly occurrences to recurring events` |

   You may fill these values with anything; they don't affect API functionality.
3. Save - the **Private token** will appear on the next page

**Verify your token works:**

```powershell
Invoke-RestMethod "https://www.eventbriteapi.com/v3/users/me/" -Headers @{ Authorization = "Bearer YOUR_PRIVATE_TOKEN_HERE" }
```

```bash
curl "https://www.eventbriteapi.com/v3/users/me/" \
  -H "Authorization: Bearer YOUR_PRIVATE_TOKEN_HERE"
```

A valid token returns your account name, email, and ID.

> **Note:** This token has full access to your Eventbrite account. **NEVER** commit it to version control or share it with anyone.

### `SERIES_ID`

This is the numeric ID of your event series. You can find it in one of two ways:

**From the dashboard URL:**

1. Open your event series in the Eventbrite dashboard
2. Look at the URL - it will look like: `https://www.eventbrite.com.au/events/1234567890/dashboard/`
3. The number (`1234567890`) is your `SERIES_ID`

**Via the API:**

First, get your organization ID:

```powershell
Invoke-RestMethod "https://www.eventbriteapi.com/v3/users/me/organizations/" -Headers @{ Authorization = "Bearer YOUR_PRIVATE_TOKEN_HERE" }
```

```bash
curl -s "https://www.eventbriteapi.com/v3/users/me/organizations/" \
  -H "Authorization: Bearer YOUR_PRIVATE_TOKEN_HERE" | python -m json.tool
```

Or extract just the ID directly:

```powershell
(Invoke-RestMethod "https://www.eventbriteapi.com/v3/users/me/organizations/" -Headers @{ Authorization = "Bearer YOUR_PRIVATE_TOKEN_HERE" }).organizations[0].id
```

```bash
curl -s "https://www.eventbriteapi.com/v3/users/me/organizations/" \
  -H "Authorization: Bearer YOUR_PRIVATE_TOKEN_HERE" | python -c "import sys,json; print(json.load(sys.stdin)['organizations'][0]['id'])"
```

Copy the `"id"` from the response, then list your live events:

```powershell
Invoke-RestMethod "https://www.eventbriteapi.com/v3/organizations/YOUR_ORG_ID/events/?status=live" -Headers @{ Authorization = "Bearer YOUR_PRIVATE_TOKEN_HERE" } | ConvertTo-Json -Depth 10
```

```bash
curl -s "https://www.eventbriteapi.com/v3/organizations/YOUR_ORG_ID/events/?status=live" \
  -H "Authorization: Bearer YOUR_PRIVATE_TOKEN_HERE" | python -m json.tool
```

Or extract just the unique series IDs directly:

```powershell
(Invoke-RestMethod "https://www.eventbriteapi.com/v3/organizations/YOUR_ORG_ID/events/?status=live" -Headers @{ Authorization = "Bearer YOUR_PRIVATE_TOKEN_HERE" }).events | Select-Object -Property series_id, @{N='name';E={$_.name.text}} -Unique
```

```bash
curl -s "https://www.eventbriteapi.com/v3/organizations/YOUR_ORG_ID/events/?status=live" \
  -H "Authorization: Bearer YOUR_PRIVATE_TOKEN_HERE" | python -c "import sys,json; [print(f'{e[\"series_id\"]}  {e[\"name\"][\"text\"]}') for e in {d['series_id']: d for d in json.load(sys.stdin)['events']}.values()]"
```

> **Note:** Use the `series_id` field, not `id`. The `id` is for individual occurrences - the `series_id` is what this script needs.

---

## Local Setup

### 1. Clone the repository

```bash
git clone https://github.com/tahayparker/eventbrite-test.git
cd eventbrite-test
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

> `python-dotenv` is only needed for local/test runs. The GitHub Action installs `requests` and `pytz` directly.

### 3. Set up environment variables

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

```
EVENTBRITE_TOKEN="your_private_token_here"
SERIES_ID="your_series_id_here"
```

> `.env` is in `.gitignore` and will not be committed.

---

## Usage

### Run the production script locally

```bash
python add_occurrences.py
```

This will only create occurrences if today is a scheduled trigger day (Mon, Wed, or Thu). On other days it exits with a log message.

### Run the test script

The test script **bypasses the day-of-week guard** and defaults to **dry-run mode** (no API calls):

```bash
python test_occurrences.py
```

This will show you what payloads _would_ be submitted without actually creating anything. To make real API calls:

```bash
python test_occurrences.py --live
```

---

## Skipping Dates

To prevent occurrences from being created on specific dates (e.g. public holidays), add them to `skip_dates.txt` in `dd-mm-yyyy` format:

```
# Public holidays
25-12-2026
01-01-2027

# Week off
14-04-2026
15-04-2026
```

- One date per line
- Lines starting with `#` are treated as comments
- Blank lines are ignored
- If the file is missing, no dates are skipped

The skip check runs **before** any API calls, so the script exits early if the target date is in the list.

---

## GitHub Actions (Automated Schedule)

The included workflow at `.github/workflows/add-occurrences.yml` runs the script automatically on a cron schedule. It triggers at **12:00 PM Sydney time** on Monday, Wednesday, and Thursday.

Because GitHub Actions cron uses UTC and Sydney's UTC offset changes with daylight saving:

| Period      | Offset | Cron (UTC)    |
|-------------|--------|---------------|
| AEDT (Oct–Apr) | UTC+11 | `0 1 * * 1,3,4` |
| AEST (Apr–Oct) | UTC+10 | `0 2 * * 1,3,4` |

Both cron entries are defined to cover both periods. The script itself handles the timezone logic, so running at either time is safe - the duplicate check ensures nothing is created twice.

### Setting up secrets

1. Go to your GitHub repository → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret** and add:
   - `EVENTBRITE_TOKEN` - your private OAuth token
   - `SERIES_ID` - your event series ID
3. The workflow reads these automatically via `${{ secrets.EVENTBRITE_TOKEN }}` and `${{ secrets.SERIES_ID }}`

### Manual trigger

You can also trigger the workflow manually from the **Actions** tab → **Add Weekly Occurrences** → **Run workflow**. This is useful for testing or creating occurrences outside the normal schedule.

---

## Adapting the Schedule

To change which days or time slots are used, edit the `DAY_SCHEDULE` dict in `add_occurrences.py`:

```python
DAY_SCHEDULE = {
    0: {"target_weekday": 1, "slots": [(10, 30), (11, 0), (11, 30)]},  # Mon run -> Tue slots
    2: {"target_weekday": 3, "slots": [(14, 0), (14, 30), (15, 0)]},   # Wed run -> Thu slots
    3: {"target_weekday": 4, "slots": [(10, 30), (11, 0), (11, 30)]},  # Thu run -> Fri slots
}
```

- Keys are Python weekday indices: `0`=Monday, `1`=Tuesday, ..., `6`=Sunday
- `target_weekday` is the day the occurrence is created _for_
- `slots` is a list of `(hour, minute)` tuples in **Sydney local time**

If you change the trigger days, also update the cron expressions in `.github/workflows/add-occurrences.yml`.

---

## Project Structure

```
.
├── .env.example                      # Template for environment variables
├── .github/workflows/
│   └── add-occurrences.yml           # GitHub Actions workflow (cron + manual)
├── add_occurrences.py                # Production script (runs on schedule)
├── test_occurrences.py               # Test harness with dry-run mode
├── skip_dates.txt                    # Dates to skip (dd-mm-yyyy)
└── .gitignore
```

---

## Logging

Both scripts use Python's `logging` module at `INFO` level by default. Log output includes timestamps and severity levels:

```
2026-04-14 12:00:01 [INFO] Script started -- Sydney time: 2026-04-14 12:00:01 (Monday)
2026-04-14 12:00:01 [INFO] Target date for new occurrences: 2026-04-15
2026-04-14 12:00:02 [INFO] Found 3 existing occurrence(s) in the series
2026-04-14 12:00:02 [INFO] Built 2 new payload(s) to submit
```

For more verbose output (pagination details, response bodies), set the log level to `DEBUG` in the script:

```python
logging.basicConfig(level=logging.DEBUG, ...)
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `KeyError: 'EVENTBRITE_TOKEN'` | Missing environment variable | Create `.env` file or set the variable in your shell |
| `HTTP 401` | Invalid or expired token | Regenerate your token at [eventbrite.com/platform/api-keys](https://www.eventbrite.com/platform/api-keys) |
| `HTTP 403` | Token doesn't have access to the series | Ensure the token belongs to the account that owns the event |
| `HTTP 404` | Wrong `SERIES_ID` | Double-check the event ID from the Eventbrite dashboard URL |
| Script exits with "No schedule configured" | Today is not a trigger day | Expected behavior - run `test_occurrences.py` to bypass this |
| Duplicate occurrences | Shouldn't happen - the script checks existing events | Check the API response; the dedup logic relies on matching UTC start times |

---
