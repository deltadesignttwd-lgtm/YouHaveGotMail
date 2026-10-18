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

import reader

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
MAX_PER_DAY = 20  # across all feeds; feeds take turns so a busy one can't crowd out the rest
# Items whose link contains any of these are ignored (never sent or recorded).
SKIP_LINKS = [
    "bloomberg.com/news/videos/",  # video clips: no article text to read
]
MAX_AGE_DAYS = 14  # ignore anything published longer ago than this
TIMEZONE = ZoneInfo("Europe/London")


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
            warnings.append(f"Not a web link in the {FEEDS_TAB} tab: {url}")
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


def skipped(link):
    return any(pattern in link for pattern in SKIP_LINKS)


def take_turns(per_feed, limit):
    """Pick up to limit items, one from each feed in turn (newest first), keeping feed order."""
    picked, depth = [], 0
    while len(picked) < limit and any(depth < len(entries) for entries in per_feed):
        for feed_no, entries in enumerate(per_feed):
            if depth < len(entries) and len(picked) < limit:
                picked.append((feed_no, depth))
        depth += 1
    return [per_feed[f][d] for f, d in sorted(picked)]


def collect(feeds, seen, today, now):
    """New items across feeds: (sheet rows, items for the reading page, warnings)."""
    per_feed, warnings, taken = [], [], set()
    for url, name in feeds:
        feed = feedparser.parse(url, agent="Mozilla/5.0 (DailyBriefingBot)")
        if feed.bozo and not feed.entries:
            warnings.append(f"Could not read feed: {name or url}")
            continue
        source = name or feed.feed.get("title", url)
        new = []
        for e in recent_entries(feed.entries, now):
            link = e.get("link")
            if link and link not in seen and link not in taken and not skipped(link):
                taken.add(link)
                new.append((source, e))
        per_feed.append(new[:MAX_PER_FEED])

    rows, items = [], []
    for source, e in take_turns(per_feed, MAX_PER_DAY):
        rows.append([today, source, e.get("title", ""), e.link, e.get("published", "")])
        items.append({"entry": e, "source": source, "title": e.get("title", e.link),
                      "link": e.link, "published": e.get("published", "")})
    return rows, items, warnings


def send_telegram_file(filename, content, caption):
    resp = requests.post(
        f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendDocument",
        data={"chat_id": os.environ["TG_CHAT_ID"], "caption": caption[:1024]},
        files={"document": (filename, content, "text/html")},
        timeout=60,
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
    rows, items, feed_warnings = collect(feeds, seen, today, now)
    warnings += feed_warnings
    if not feeds:
        warnings.append(f"No feeds are switched on. Add links to the {FEEDS_TAB} tab of your Google Sheet.")

    # The reading page is the whole briefing; it is sent every day, even with nothing new.
    page = reader.build_page(reader.add_bodies(items), today, warnings)
    count = f"{len(items)} new item{'s' if len(items) != 1 else ''}" if items else "No new items today"
    send_telegram_file(f"briefing-{today}.html", page.encode("utf-8"),
                       f"📰 Daily Briefing – {today} · {count}. Tap to open.")

    # Recorded only after sending, so a failed send is retried tomorrow instead of lost.
    if rows:
        ws.append_rows(rows, value_input_option="RAW")
    print(f"Sent reading page with {len(items)} new item(s), {len(page) // 1024} KB.")


if __name__ == "__main__":
    sys.exit(main())
