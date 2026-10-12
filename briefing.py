"""Daily briefing bot: reads RSS feeds, sends new items to Telegram, logs them to Google Sheets."""
import calendar
import datetime
import json
import os
import sys
from zoneinfo import ZoneInfo

import feedparser
import gspread
import requests

# The feed list lives in the "Feeds" tab of the Google Sheet (columns: url | name | on).
# The bot creates that tab on first run and fills it with these starting feeds.
FEEDS_TAB = "Feeds"
FEEDS_HEADER = ["url", "name", "on"]
STARTING_FEEDS = [
    ["https://anchor.fm/s/f380feb4/podcast/rss", "我要做富翁", "yes"],
]
OFF_VALUES = {"no", "n", "off", "false", "0", "pause", "paused"}
LOG_HEADER = ["date", "source", "title", "link", "published"]
MAX_PER_FEED = 10
MAX_AGE_DAYS = 14  # ignore anything published longer ago than this
TIMEZONE = ZoneInfo("Europe/London")
TELEGRAM_LIMIT = 4000  # Telegram caps messages at 4096 chars


def published_at(entry):
    """Publish time as an aware UTC datetime, or None if the feed gives no date."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime.datetime.fromtimestamp(calendar.timegm(parsed), datetime.timezone.utc)


def recent_entries(entries, now, max_age_days=MAX_AGE_DAYS):
    """Newest first, dropping items older than max_age_days. Feeds may list oldest first."""
    cutoff = now - datetime.timedelta(days=max_age_days)
    dated = [(published_at(e), e) for e in entries]
    fresh = [(d, e) for d, e in dated if d is None or d >= cutoff]
    fresh.sort(key=lambda pair: pair[0] or cutoff, reverse=True)  # undated last
    return [e for _, e in fresh]


def parse_feed_rows(values):
    """Turn the Feeds tab's cells into (url, name) pairs that are switched on, plus warnings.

    Blank rows are ignored; a blank "on" cell counts as on, so pasting a link is enough.
    """
    feeds, warnings = [], []
    for row in values[1:]:  # skip header
        url, name, on = (list(row) + ["", "", ""])[:3]
        url, name, on = url.strip(), name.strip(), on.strip().lower()
        if not url or on in OFF_VALUES:
            continue
        if not url.startswith(("http://", "https://")):
            warnings.append(f"⚠️ Not a web link in the {FEEDS_TAB} tab: {escape(url)}")
            continue
        feeds.append((url, name))
    return feeds, warnings


def load_feeds(spreadsheet):
    """Read the Feeds tab, creating it with STARTING_FEEDS if it doesn't exist yet."""
    try:
        tab = spreadsheet.worksheet(FEEDS_TAB)
    except gspread.WorksheetNotFound:
        tab = spreadsheet.add_worksheet(title=FEEDS_TAB, rows=100, cols=len(FEEDS_HEADER))
        tab.append_rows([FEEDS_HEADER] + STARTING_FEEDS, value_input_option="RAW")
    return parse_feed_rows(tab.get_all_values())


def log_worksheet(spreadsheet):
    """The record of sent items: the first tab that isn't the Feeds tab."""
    for tab in spreadsheet.worksheets():
        if tab.title != FEEDS_TAB:
            return tab
    return spreadsheet.add_worksheet(title="Log", rows=1000, cols=len(LOG_HEADER))


def collect(feeds, seen, today, now):
    rows, sections = [], []
    for url, name in feeds:
        feed = feedparser.parse(url, agent="Mozilla/5.0 (DailyBriefingBot)")
        if feed.bozo and not feed.entries:
            sections.append(f"⚠️ Could not read feed: {escape(name or url)}")
            continue
        source = name or feed.feed.get("title", url)
        candidates = recent_entries(feed.entries, now)
        new = [e for e in candidates if e.get("link") and e.link not in seen][:MAX_PER_FEED]
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
    gc = gspread.service_account_from_dict(json.loads(os.environ["GOOGLE_CREDS"]))
    spreadsheet = gc.open_by_key(os.environ["SHEET_ID"])
    feeds, warnings = load_feeds(spreadsheet)
    ws = log_worksheet(spreadsheet)
    if not ws.row_values(1):
        ws.append_row(LOG_HEADER)
    seen = set(ws.col_values(4))

    today = now.date().isoformat()
    rows, sections = collect(feeds, seen, today, now)
    sections = warnings + sections

    header = f"📰 <b>Daily Briefing – {today}</b>"
    if not feeds:
        sections.append(f"No feeds are switched on. Add links to the {FEEDS_TAB} tab of your Google Sheet.")
    elif not rows:
        sections.append("No new items today.")
    body = "\n\n".join(sections)
    send_telegram(f"{header}\n\n{body}")

    if rows:
        ws.append_rows(rows, value_input_option="RAW")
    print(f"Sent briefing with {len(rows)} new item(s).")


if __name__ == "__main__":
    sys.exit(main())
