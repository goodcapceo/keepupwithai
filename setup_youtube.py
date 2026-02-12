#!/usr/bin/env python3
"""One-time script to resolve YouTube channel IDs from handles.

Fetches the YouTube channel page for each handle, parses the HTML
for the channelId, and prints the RSS feed URL to use in feeds.yaml.
"""

from __future__ import annotations

import re
import sys
import time
import urllib.request
import urllib.error

HANDLES_TO_RESOLVE = [
    "sabrina_ramonov",
    "AlexFinnOfficial",
    "AcquiredFM",
    "ryanlpeterman",
]

FEED_URL_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={}"

# Patterns that YouTube embeds in page HTML
CHANNEL_ID_PATTERNS = [
    re.compile(r'"channelId"\s*:\s*"(UC[a-zA-Z0-9_-]{22})"'),
    re.compile(r'"externalId"\s*:\s*"(UC[a-zA-Z0-9_-]{22})"'),
    re.compile(r'<meta\s+itemprop="channelId"\s+content="(UC[a-zA-Z0-9_-]{22})"'),
    re.compile(r'"browseId"\s*:\s*"(UC[a-zA-Z0-9_-]{22})"'),
]


def resolve_channel_id(handle: str) -> str | None:
    """Fetch a YouTube channel page and extract the channel ID from HTML."""
    url = f"https://www.youtube.com/@{handle}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} fetching {url}")
        return None
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return None

    for pattern in CHANNEL_ID_PATTERNS:
        match = pattern.search(html)
        if match:
            return match.group(1)

    return None


def main() -> None:
    print("Resolving YouTube channel IDs...\n")
    results: dict[str, str | None] = {}

    for handle in HANDLES_TO_RESOLVE:
        print(f"@{handle}:")
        channel_id = resolve_channel_id(handle)

        if channel_id:
            feed_url = FEED_URL_TEMPLATE.format(channel_id)
            print(f"  channel_id: {channel_id}")
            print(f"  feed_url:   {feed_url}")
            results[handle] = channel_id
        else:
            print(f"  FAILED — could not extract channel ID.")
            print(f"  Fallback: Open https://www.youtube.com/@{handle} in your browser,")
            print(f"            right-click → View Source, search for channelId,")
            print(f"            and paste the UC... value into feeds.yaml")
            results[handle] = None

        print()
        time.sleep(1)  # Be polite between requests

    # Print summary for easy copy-paste into feeds.yaml
    print("=" * 60)
    print("SUMMARY — paste into feeds.yaml:\n")
    for handle, cid in results.items():
        if cid:
            print(f"- name: {handle}")
            print(f"  channel_id: {cid}")
            print(f"  feed_url: {FEED_URL_TEMPLATE.format(cid)}")
            print()
        else:
            print(f"- name: {handle}")
            print(f"  channel_id: MANUAL RESOLUTION NEEDED")
            print()

    failed = [h for h, cid in results.items() if cid is None]
    if failed:
        print(f"⚠ {len(failed)} channel(s) need manual resolution: {', '.join(failed)}")
        sys.exit(1)
    else:
        print("All channels resolved successfully!")


if __name__ == "__main__":
    main()
