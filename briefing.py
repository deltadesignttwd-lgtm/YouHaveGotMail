"""Daily briefing bot: reads RSS feeds, sends new items to Telegram, logs them to Google Sheets."""
import datetime
import json
import os
import sys
from zoneinfo import ZoneInfo

import feedparser
import gspread
import requests

FEEDS = [
    "https://www.norges-bank.no/en/rss-feeds/Articles-and-chronicles---Norges-Bank/",
]
MAX_PER_FEED = 10
TIMEZONE = ZoneInfo("Europe/London")
SEND_HOUR = 8  # local London time
TELEGRAM_LIMIT = 4000  # Telegram caps messages at 4096 chars


def should_run(now):
    """The workflow fires at 07:00 and 08:00 UTC; only the one matching 08:00 London today should send.

    Decided from which cron fired (not the clock), so a late-starting run never doubles up.
    """
    if os.environ.get("FORCE_RUN") == "true":
        return True
    schedule = os.environ.get("SCHEDULE", "")
    if not schedule:
        return now.hour == SEND_HOUR
    utc_hour = int(schedule.split()[1])
    offset_hours = int(now.utcoffset().total_seconds() // 3600)
    return utc_hour + offset_hours == SEND_HOUR


def collect(feeds, seen, today):
    rows, sections = [], []
    for url in feeds:
        feed = feedparser.parse(url, agent="Mozilla/5.0 (DailyBriefingBot)")
        if feed.bozo and not feed.entries:
            sections.append(f"⚠️ Could not read feed: {url}")
            continue
        source = feed.feed.get("title", url)
        new = [e for e in feed.entries[:MAX_PER_FEED] if e.get("link") and e.link not in seen]
        if not new:
            continue
        lines = [f"<b>{escape(source)}</b>"]
        for e in new:
            lines.append(f'• <a href="{escape(e.link)}">{escape(e.get("title", e.link))}</a>')
            rows.append([today, source, e.get("title", ""), e.link, e.get("published", "")])
        sections.append("\n".join(lines))
    return rows, sections


def escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def chunk(text, limit=TELEGRAM_LIMIT):
    """Split on line boundaries so no message exceeds Telegram's limit."""
    chunks, current = [], ""
    for line in text.split("\n"):
        if current and len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


def send_telegram(text):
    for part in chunk(text):
        resp = requests.post(
            f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage",
            json={
                "chat_id": os.environ["TG_CHAT_ID"],
                "text": part,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        resp.raise_for_status()


def main():
    now = datetime.datetime.now(TIMEZONE)
    if not should_run(now):
        print(f"Not the {SEND_HOUR}:00 London slot today (London time {now:%H:%M}), skipping.")
        return

    gc = gspread.service_account_from_dict(json.loads(os.environ["GOOGLE_CREDS"]))
    ws = gc.open_by_key(os.environ["SHEET_ID"]).sheet1
    if not ws.row_values(1):
        ws.append_row(["date", "source", "title", "link", "published"])
    seen = set(ws.col_values(4))

    today = now.date().isoformat()
    rows, sections = collect(FEEDS, seen, today)

    header = f"📰 <b>Daily Briefing – {today}</b>"
    body = "\n\n".join(sections) if sections else "No new items today."
    send_telegram(f"{header}\n\n{body}")

    if rows:
        ws.append_rows(rows, value_input_option="RAW")
    print(f"Sent briefing with {len(rows)} new item(s).")


if __name__ == "__main__":
    sys.exit(main())
