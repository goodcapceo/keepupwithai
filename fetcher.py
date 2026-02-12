#!/usr/bin/env python3
"""Stage 1: Fetch feeds and insert new items into the database.

Loads sources from feeds.yaml, discovers RSS feed URLs, fetches entries,
deduplicates by url_hash, and stores new items with status="new".
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_PATH = Path("data.sqlite")
FEEDS_PATH = Path("feeds.yaml")
REQUEST_TIMEOUT = 15
MAX_CHARS_PER_ITEM = int(os.environ.get("MAX_CHARS_PER_ITEM", "8000"))
MAX_RETRIES = 3
BACKOFF_BASE = 2  # seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    feed_url TEXT,
    type TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    last_fetch_at TEXT,
    etag TEXT,
    last_modified TEXT
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    guid TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    content_text TEXT,
    url_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'new',
    summary_json TEXT,
    model_used TEXT,
    FOREIGN KEY (source_id) REFERENCES sources(id)
);

CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_items_url_hash ON items(url_hash);
CREATE INDEX IF NOT EXISTS idx_items_published_at ON items(published_at);
"""


def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
})

# Track domains that fail with non-retryable errors (DNS, connection refused)
# so we skip all subsequent URLs on the same domain within this run.
_failed_domains: set[str] = set()


def _get_domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _is_non_retryable_error(exc: requests.RequestException) -> bool:
    """Check if the error is non-retryable (DNS failure, connection refused)."""
    cause = exc.__cause__ or exc
    name = type(cause).__name__
    # Walk the exception chain for wrapped errors (urllib3 → socket)
    while hasattr(cause, "__cause__") and cause.__cause__:
        cause = cause.__cause__
        name = type(cause).__name__
    # DNS resolution failures, connection refused, etc.
    return any(k in name for k in ("NameResolution", "gaierror", "ConnectionRefused"))


def fetch_with_backoff(url: str, **kwargs) -> requests.Response | None:
    """GET with exponential backoff. Returns None on total failure.

    Does not retry on: 4xx (except 429), DNS failures, connection refused.
    Only retries on: timeouts, 5xx, and transient network errors.
    """
    domain = _get_domain(url)
    if domain in _failed_domains:
        log.info("  Skipping %s (domain previously failed)", url)
        return None

    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    for attempt in range(MAX_RETRIES):
        try:
            resp = SESSION.get(url, **kwargs)
            if resp.status_code == 304:
                return resp
            # 4xx (except 429) are definitive — don't retry
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                log.warning("%s returned %d", url, resp.status_code)
                return None
            resp.raise_for_status()
            return resp
        except requests.ConnectionError as e:
            if _is_non_retryable_error(e):
                _failed_domains.add(domain)
                log.warning("%s failed (non-retryable: %s) — domain blacklisted for this run",
                            url, type(e.__cause__ or e).__name__)
                return None
            # Other ConnectionErrors (reset, broken pipe) are retryable
            wait = BACKOFF_BASE ** attempt
            log.warning("Attempt %d/%d for %s failed: %s (retry in %ds)",
                        attempt + 1, MAX_RETRIES, url, e, wait)
            if attempt < MAX_RETRIES - 1:
                time.sleep(wait)
        except requests.RequestException as e:
            wait = BACKOFF_BASE ** attempt
            log.warning("Attempt %d/%d for %s failed: %s (retry in %ds)",
                        attempt + 1, MAX_RETRIES, url, e, wait)
            if attempt < MAX_RETRIES - 1:
                time.sleep(wait)
    log.error("All %d attempts failed for %s", MAX_RETRIES, url)
    _failed_domains.add(domain)  # also blacklist after exhausting retries (e.g. timeouts)
    return None


# ---------------------------------------------------------------------------
# Feed URL discovery
# ---------------------------------------------------------------------------
def discover_feed_url(source: dict) -> str | None:
    """Resolve the RSS feed URL for a source based on its type."""
    src_type = source.get("type", "site")
    url = source["url"].rstrip("/")

    # If feed_url is explicitly provided (e.g. YouTube), use it directly
    if source.get("feed_url"):
        return source["feed_url"]

    # If html_fallback_url is set, skip discovery — we know there's no RSS
    if source.get("html_fallback_url"):
        return None

    if src_type == "substack":
        return url + "/feed"

    if src_type == "medium":
        # Medium profile: https://medium.com/@USER → /feed/@USER
        # Medium publication: https://ai.gopubby.com/ → https://medium.com/feed/PUBLICATION
        match = re.match(r"https?://medium\.com/(@[\w.-]+)", url)
        if match:
            return f"https://medium.com/feed/{match.group(1)}"
        # Publication on custom domain — try /feed path
        match = re.match(r"https?://([\w.-]+\.[\w]+)", url)
        if match:
            return f"https://medium.com/feed/{match.group(0).split('//')[1].split('.')[0]}"
        return None

    if src_type == "youtube":
        # Should have feed_url already, but just in case
        return None

    # Generic site: probe for RSS
    return _discover_site_feed(url)


def _discover_site_feed(url: str) -> str | None:
    """Try to find an RSS feed for a generic website."""
    resp = fetch_with_backoff(url)
    if resp is None:
        return None

    # Check for <link rel="alternate" type="application/rss+xml">
    soup = BeautifulSoup(resp.text, "html.parser")
    for link_tag in soup.find_all("link", rel="alternate"):
        link_type = (link_tag.get("type") or "").lower()
        if "rss" in link_type or "atom" in link_type:
            href = link_tag.get("href", "")
            if href.startswith("/"):
                href = url + href
            elif not href.startswith("http"):
                href = url + "/" + href
            return href

    # Probe common paths (including nested /feed/ variants for static-site generators)
    for path in ["/feed", "/rss", "/rss.xml", "/atom.xml", "/feed.xml", "/index.xml",
                 "/feed/feed.xml", "/feed/atom.xml", "/feed/index.xml"]:
        probe_url = url + path
        probe = fetch_with_backoff(probe_url)
        if probe and probe.status_code == 200:
            ct = probe.headers.get("content-type", "").lower()
            if any(t in ct for t in ["xml", "rss", "atom"]):
                return probe_url
            # Some servers return RSS with text/html content-type — try parsing
            parsed = feedparser.parse(probe.text)
            if parsed.entries:
                return probe_url

    return None


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------
def extract_text_from_html(html: str) -> str:
    """Extract readable text from HTML content using BeautifulSoup heuristics."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove script, style, nav, footer, header elements
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # Try to find main content area
    main = soup.find("main") or soup.find("article") or soup.find(class_=re.compile(r"post|content|entry|article", re.I))
    target = main if main else soup.body if soup.body else soup

    text = target.get_text(separator="\n", strip=True)
    # Collapse excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:MAX_CHARS_PER_ITEM]


def get_entry_content(entry: feedparser.FeedParserDict) -> str:
    """Get the best available content from a feed entry."""
    # Prefer content field
    if hasattr(entry, "content") and entry.content:
        html = entry.content[0].get("value", "")
        if html:
            return extract_text_from_html(html)

    # Try summary/description
    if hasattr(entry, "summary") and entry.summary:
        return extract_text_from_html(entry.summary)

    return ""


def fetch_article_text(url: str) -> str:
    """Fetch an article page and extract main text."""
    resp = fetch_with_backoff(url)
    if resp is None:
        return ""
    return extract_text_from_html(resp.text)


# ---------------------------------------------------------------------------
# URL hashing
# ---------------------------------------------------------------------------
def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Parsing feed entry dates
# ---------------------------------------------------------------------------
def parse_entry_date(entry: feedparser.FeedParserDict) -> str | None:
    """Extract a UTC ISO 8601 date string from a feed entry."""
    for attr in ("published_parsed", "updated_parsed"):
        tp = getattr(entry, attr, None)
        if tp:
            try:
                dt = datetime(*tp[:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except (ValueError, TypeError):
                continue
    return None


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def upsert_source(conn: sqlite3.Connection, source: dict, feed_url: str | None) -> int:
    """Insert or update a source. Returns the source ID."""
    active = 1 if feed_url else 0
    row = conn.execute(
        "SELECT id FROM sources WHERE source_url = ?", (source["url"],)
    ).fetchone()

    if row:
        conn.execute(
            "UPDATE sources SET name=?, feed_url=?, type=?, active=? WHERE id=?",
            (source["name"], feed_url, source.get("type", "site"), active, row["id"]),
        )
        return row["id"]
    else:
        cursor = conn.execute(
            "INSERT INTO sources (name, source_url, feed_url, type, active) VALUES (?,?,?,?,?)",
            (source["name"], source["url"], feed_url, source.get("type", "site"), active),
        )
        return cursor.lastrowid


def fetch_feed(conn: sqlite3.Connection, source_id: int, feed_url: str) -> int:
    """Fetch a feed and insert new items. Returns count of new items."""
    # Load cached ETag / Last-Modified
    row = conn.execute(
        "SELECT etag, last_modified FROM sources WHERE id=?", (source_id,)
    ).fetchone()

    headers = {}
    if row["etag"]:
        headers["If-None-Match"] = row["etag"]
    if row["last_modified"]:
        headers["If-Modified-Since"] = row["last_modified"]

    resp = fetch_with_backoff(feed_url, headers=headers)
    if resp is None:
        return 0
    if resp.status_code == 304:
        log.info("  Not modified (304)")
        return 0

    # Update ETag / Last-Modified
    new_etag = resp.headers.get("ETag")
    new_lm = resp.headers.get("Last-Modified")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE sources SET etag=?, last_modified=?, last_fetch_at=? WHERE id=?",
        (new_etag, new_lm, now, source_id),
    )

    parsed = feedparser.parse(resp.text)
    if not parsed.entries:
        log.warning("  No entries found in feed")
        return 0

    new_count = 0
    for entry in parsed.entries:
        entry_url = getattr(entry, "link", None) or getattr(entry, "id", None)
        if not entry_url:
            continue

        entry_hash = url_hash(entry_url)

        # Dedupe check
        exists = conn.execute(
            "SELECT 1 FROM items WHERE url_hash=?", (entry_hash,)
        ).fetchone()
        if exists:
            continue

        title = getattr(entry, "title", "Untitled")
        guid = getattr(entry, "id", None)
        published = parse_entry_date(entry)

        # Get content: prefer feed content, fallback to fetching the page
        content = get_entry_content(entry)
        if not content or len(content.strip()) < 100:
            content = fetch_article_text(entry_url)

        content = content[:MAX_CHARS_PER_ITEM]

        conn.execute(
            """INSERT INTO items
               (source_id, title, url, guid, published_at, fetched_at,
                content_text, url_hash, status)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (source_id, title, entry_url, guid, published,
             now, content, entry_hash, "new"),
        )
        new_count += 1
        log.info("  + %s", title)

    return new_count


def main() -> None:
    log.info("=== Fetcher starting ===")

    # Load feeds.yaml
    with open(FEEDS_PATH) as f:
        config = yaml.safe_load(f)

    sources = config.get("sources", [])
    log.info("Loaded %d sources from %s", len(sources), FEEDS_PATH)

    conn = init_db()
    total_new = 0

    for source in sources:
        log.info("Processing: %s", source["name"])

        # Discover feed URL
        feed_url = discover_feed_url(source)
        if not feed_url:
            fallback = source.get("html_fallback_url")
            if fallback:
                log.info("  No RSS feed — html_fallback_url set: %s (skipping for now)", fallback)
            else:
                log.warning("  Could not discover feed URL — skipping")
            upsert_source(conn, source, None)  # sets active=0 since no feed_url
            conn.commit()
            continue

        # Validate feed by parsing
        source_id = upsert_source(conn, source, feed_url)
        conn.commit()

        log.info("  Feed: %s", feed_url)
        new_count = fetch_feed(conn, source_id, feed_url)
        total_new += new_count
        conn.commit()

        log.info("  New items: %d", new_count)
        time.sleep(0.2)  # Brief pause between sources

    log.info("=== Fetcher done: %d new items ===", total_new)
    conn.close()


if __name__ == "__main__":
    main()
