#!/usr/bin/env python3
"""
main.py – Entry point for the Reminder Bot.

Flow:
  1. Print startup banner
  2. Load reminders from reminders.yaml
  3. Determine which reminders are due (scheduler)
  4. For each due reminder:
      a. Render template variables
      b. Send notifications to configured channels
      c. Log the result
  5. Exit
"""

import os
import sys

from notifier import send_notification
from scheduler import get_due_reminders, get_next_run
from utils import (
    append_log,
    load_reminders,
    print_banner,
    render_template,
)


def main() -> None:
    print_banner()

    # 1. Load config
    reminders = load_reminders()
    print(f"\n📋 Loaded {len(reminders)} reminder(s) from config.\n")

    # Show next-run preview for each reminder
    for r in reminders:
        status = "🟢 enabled" if r.get("enabled", True) else "🔴 disabled"
        try:
            nxt = get_next_run(r)
        except Exception:
            nxt = "invalid schedule"
        print(f"   • {r['id']:30s} {status:15s} next → {nxt}")

    print()

    # 2. Find due reminders (or a specific one for testing)
    test_id = os.environ.get("TEST_REMINDER_ID", "").strip()
    if test_id:
        due = [r for r in reminders if r["id"] == test_id]
        if not due:
            print(f"❌ Test reminder '{test_id}' not found.\n")
            sys.exit(1)
        print(f"🧪 Test mode – running '{test_id}' regardless of schedule.\n")
    else:
        due = get_due_reminders(reminders)

    if not due:
        print("💤 No reminders due at this time.\n")
        return

    print(f"🔔 {len(due)} reminder(s) due – processing …\n")

    # 3. Process each due reminder
    all_ok = True
    for reminder in due:
        rid = reminder["id"]
        tz = reminder.get("timezone", "Asia/Kolkata")
        raw_msg = reminder.get("message", "")
        channels = reminder.get("channels", [])
        gchat_webhook = reminder.get("gchat_webhook") or None
        email_recipients = reminder.get("email_recipients") or None

        # Render template variables
        message = render_template(raw_msg, tz)
        print(f"── {rid} ──")
        print(f"   Message : {message}")
        print(f"   Channels: {', '.join(channels)}")

        # Send notifications
        results = send_notification(message, channels, gchat_webhook=gchat_webhook, email_recipients=email_recipients)

        # Log results
        for channel, ok in results.items():
            if ok:
                append_log(rid, "success", f"Sent via {channel}")
            else:
                append_log(rid, "failure", f"Failed via {channel}")
                all_ok = False

        print()

    # Summary
    if all_ok:
        print("✅ All notifications sent successfully.")
    else:
        print("⚠️  Some notifications failed – check logs.json for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
