"""Full-text reading page: fetch each article, extract its text, and build one HTML page."""
import html
import re
from concurrent.futures import ThreadPoolExecutor

import requests
import trafilatura

USER_AGENT = "Mozilla/5.0 (DailyBriefingBot)"
FETCH_TIMEOUT = 20  # seconds per article
MIN_ARTICLE_CHARS = 200  # shorter extractions are treated as failed (paywall, cookie wall, ...)
MAX_ARTICLE_CHARS = 100_000


def html_to_text(fragment):
    """Plain text from a small HTML fragment such as an RSS summary, keeping paragraph breaks."""
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", fragment or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def rss_text(entry):
    """The longest text the feed itself gives for an entry (full content or summary)."""
    candidates = [c.get("value", "") for c in entry.get("content", [])]
    candidates.append(entry.get("summary", ""))
    return max((html_to_text(c) for c in candidates), key=len, default="")


def is_podcast(entry):
    return any(enc.get("type", "").startswith("audio/") for enc in entry.get("enclosures", []))


def fetch_article_text(url):
    """Main text of the page at url, or None if it can't be fetched or extracted."""
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=FETCH_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"Could not fetch {url}: {exc}")
        return None
    text = trafilatura.extract(
        resp.text, url=url, include_comments=False, include_tables=True, favor_precision=True
    )
    if not text or len(text) < MIN_ARTICLE_CHARS:
        return None
    return text[:MAX_ARTICLE_CHARS]


def article_body(entry):
    """(text, note) for one entry: the full article if possible, else what the feed provides."""
    summary = rss_text(entry)
    if is_podcast(entry):
        return summary, "Podcast episode: show notes below. Use the link to listen."
    text = fetch_article_text(entry.link)
    if text and len(text) >= len(summary):
        return text, ""
    return summary, "Full text not available (paywall or blocked). Showing the feed's summary."


def add_bodies(items, workers=5):
    """Fill item["text"] and item["note"] for each item, fetching articles in parallel."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for item, (text, note) in zip(items, pool.map(lambda i: article_body(i["entry"]), items)):
            item["text"], item["note"] = text, note
    return items


PAGE_CSS = """
:root { --bg: #fbfaf7; --fg: #1f1f1f; --muted: #6b6b6b; --rule: #e3e0d8; --link: #1a5fb4; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #161616; --fg: #e8e6e1; --muted: #9a9a9a; --rule: #333; --link: #8ab4f8; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 1.125rem/1.7 Georgia, "Noto Serif", "Songti TC", "PMingLiU", serif; }
main { max-width: 42rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
h1 { font-size: 1.6rem; line-height: 1.3; margin: 0 0 .25rem; }
h2 { font-size: 1.35rem; line-height: 1.35; margin: 0 0 .25rem; }
a { color: var(--link); }
.meta, .note, nav li span { color: var(--muted); font-size: .9rem; }
.note { font-style: italic; }
.warn { border-left: 3px solid #d97706; padding: .25rem .75rem; font-size: .95rem; }
nav ol { padding-left: 1.25rem; }
nav li { margin: .35rem 0; }
article { border-top: 1px solid var(--rule); margin-top: 2.5rem; padding-top: 1.5rem; }
article p { margin: 0 0 1em; overflow-wrap: anywhere; }
.top { font-size: .9rem; }
"""


def build_page(items, today, warnings=()):
    """One self-contained HTML page with a contents list and every article in full."""
    esc = html.escape
    toc, articles = [], []
    for n, item in enumerate(items, 1):
        anchor = f"a{n}"
        toc.append(
            f'<li><a href="#{anchor}">{esc(item["title"])}</a> <span>· {esc(item["source"])}</span></li>'
        )
        meta = " · ".join(esc(part) for part in (item["source"], item["published"]) if part)
        lines = [p.strip() for p in item["text"].split("\n") if p.strip()]
        if lines and lines[0].casefold() == item["title"].strip().casefold():
            lines = lines[1:]  # extracted text often repeats the headline
        paragraphs = "\n".join(f"<p>{esc(p)}</p>" for p in lines)
        note = f'<p class="note">{esc(item["note"])}</p>' if item["note"] else ""
        articles.append(f"""<article id="{anchor}">
<h2>{esc(item["title"])}</h2>
<p class="meta">{meta}</p>
{note}
{paragraphs or '<p class="note">No text available.</p>'}
<p><a href="{esc(item["link"])}">Open original ↗</a> · <a class="top" href="#top">Back to top ↑</a></p>
</article>""")

    count = f"{len(items)} new item{'s' if len(items) != 1 else ''}" if items else "No new items today."
    notices = "\n".join(f'<p class="warn">⚠️ {esc(w)}</p>' for w in warnings)
    contents = f"<nav><ol>\n{chr(10).join(toc)}\n</ol></nav>" if toc else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Briefing – {esc(today)}</title>
<style>{PAGE_CSS}</style>
</head>
<body>
<main id="top">
<h1>Daily Briefing – {esc(today)}</h1>
<p class="meta">{count}</p>
{notices}
{contents}
{chr(10).join(articles)}
</main>
</body>
</html>
"""
