"""
scheduler.py – Determines which reminders are due to fire.

Uses croniter to parse cron expressions and pytz for timezone handling.
Implements missed-run recovery: if the bot was offline for a window,
any reminders that should have fired in that window are still triggered.
"""

from datetime import datetime, timedelta

import pytz
from croniter import croniter

from utils import load_logs


# How far back (in minutes) to look for missed runs.
# Should be slightly larger than the GitHub Actions cron interval.
LOOKBACK_MINUTES = 20


def get_due_reminders(reminders: list[dict]) -> list[dict]:
    """
    Filter *reminders* to only those that should fire right now
    (or were missed within the lookback window).

    Returns a list of reminder dicts that are due.
    """
    due = []
    now_utc = datetime.now(pytz.utc)

    for reminder in reminders:
        # Skip disabled reminders
        if not reminder.get("enabled", True):
            continue

        tz_name = reminder.get("timezone", "Asia/Kolkata")
        try:
            tz = pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            print(f"⚠️  Unknown timezone '{tz_name}' for {reminder['id']}, skipping.")
            continue

        now_local = now_utc.astimezone(tz)
        schedule_type = reminder.get("schedule_type", "cron")

        if schedule_type == "cron":
            cron_expr = reminder.get("schedule", "")
            if not cron_expr:
                continue

            try:
                if _is_due_cron(cron_expr, now_local, reminder["id"]):
                    due.append(reminder)
            except (ValueError, KeyError) as exc:
                print(f"⚠️  Error checking schedule for {reminder.get('id', '?')}: {exc}")
        elif schedule_type == "interval_days":
            try:
                if _is_due_interval(reminder, now_local):
                    due.append(reminder)
            except Exception as exc:
                print(f"⚠️  Error checking interval for {reminder.get('id', '?')}: {exc}")

    return due


def _is_due_cron(cron_expr: str, now_local: datetime, reminder_id: str) -> bool:
    """
    Check whether the cron expression has a fire time within the
    lookback window ending at *now_local*.

    This provides missed-run recovery: even if the bot ran a few
    minutes late, it will still catch reminders it missed.
    """
    window_start = now_local - timedelta(minutes=LOOKBACK_MINUTES)

    # croniter iterates *forward* from a base time.
    # We start from window_start and check if any fire time falls
    # between window_start and now_local.
    cron = croniter(cron_expr, window_start)

    # Check up to 5 potential fire times in the window (more than enough).
    for _ in range(5):
        next_fire = cron.get_next(datetime)
        # Make timezone-aware if croniter returns naive datetime
        if next_fire.tzinfo is None:
            next_fire = now_local.tzinfo.localize(next_fire)
        if next_fire > now_local:
            break
        if window_start <= next_fire <= now_local:
            # Check if we already ran this one recently
            if not _already_ran(reminder_id, next_fire):
                return True

    return False


def _is_due_interval(reminder: dict, now_local: datetime) -> bool:
    """
    Check whether the interval-based reminder should fire on this day.
    Default execution time is set to 09:00 AM local time.
    """
    start_date_str = reminder.get("start_date")
    interval = int(reminder.get("interval_days", 1))

    if not start_date_str or interval <= 0:
        return False
        
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError:
        print(f"⚠️  Invalid start_date '{start_date_str}' for {reminder.get('id')}.")
        return False

    today = now_local.date()
    # Check if we're on or past the start date
    if today < start_date:
        return False
        
    days_since_start = (today - start_date).days
    if days_since_start % interval != 0:
        return False
        
    # We default the fire time to 09:00 AM on the target day Local Time
    target_time = now_local.replace(hour=9, minute=0, second=0, microsecond=0)
    
    window_start = now_local - timedelta(minutes=LOOKBACK_MINUTES)
    
    if window_start <= target_time <= now_local:
        if not _already_ran(reminder.get("id"), target_time):
            return True
            
    return False


def _already_ran(reminder_id: str, fire_time: datetime) -> bool:
    """
    Check logs.json to see if we already executed this reminder
    within ±2 minutes of the expected fire_time (dedup guard).
    """
    logs = load_logs()
    for entry in reversed(logs.get("runs", [])):
        if entry.get("reminder_id") != reminder_id:
            continue
        try:
            entry_ts = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
            diff = abs((entry_ts - fire_time.astimezone(pytz.utc)).total_seconds())
            if diff < 300:  # within 5 minutes → already handled
                return True
        except (ValueError, KeyError):
            continue
    return False


def get_next_run(reminder: dict) -> str:
    """Return a human-readable string of the next fire time (for debugging)."""
    timezone = reminder.get("timezone", "Asia/Kolkata")
    tz = pytz.timezone(timezone)
    now = datetime.now(tz)

    schedule_type = reminder.get("schedule_type", "cron")

    if schedule_type == "interval_days":
        start_date_str = reminder.get("start_date")
        interval = int(reminder.get("interval_days", 1))
        if not start_date_str or interval <= 0:
            return "invalid interval config"
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        today = now.date()
        days_since_start = max(0, (today - start_date).days)
        days_until_next = interval - (days_since_start % interval)
        if days_until_next == interval and today >= start_date:
            days_until_next = 0
        next_date = today + timedelta(days=days_until_next)
        return f"{next_date.strftime('%Y-%m-%d')} 09:00 {now.strftime('%Z')}"

    cron_expr = reminder.get("schedule", "")
    if not cron_expr:
        return "no schedule defined"
    cron = croniter(cron_expr, now)
    return cron.get_next(datetime).strftime("%Y-%m-%d %H:%M %Z")
