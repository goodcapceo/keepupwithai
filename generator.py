#!/usr/bin/env python3
"""Stage 3: Generate a static HTML page from summarized items.

Reads the most recent 100 summarized items and writes site/index.html
with a clean, responsive layout using <details> for expand/collapse.
"""
from __future__ import annotations

import html
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("data.sqlite")
OUTPUT_DIR = Path("site")
OUTPUT_PATH = OUTPUT_DIR / "index.html"
MAX_DISPLAY_ITEMS = 100

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------
def esc(text: str) -> str:
    """Escape text for safe HTML output."""
    return html.escape(str(text)) if text else ""


def format_date(iso_str: str | None) -> str:
    if not iso_str:
        return "Unknown date"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%b %d, %Y")
    except (ValueError, TypeError):
        return "Unknown date"


def render_item(item: sqlite3.Row) -> str:
    """Render a single item as an HTML card."""
    title = esc(item["title"])
    url = esc(item["url"])
    source_name = esc(item["source_name"])
    date = format_date(item["published_at"])

    # Parse summary JSON
    try:
        summary = json.loads(item["summary_json"]) if item["summary_json"] else {}
    except json.JSONDecodeError:
        summary = {}

    eli5 = esc(summary.get("eli5", ""))
    eli16 = esc(summary.get("eli16", ""))
    why = esc(summary.get("why_this_matters", ""))
    changed = esc(summary.get("what_changed", ""))
    unknowns = esc(summary.get("confidence_unknowns", ""))
    quotes = summary.get("key_quotes", [])

    quotes_html = ""
    if quotes:
        items_html = "".join(
            f'<li>"{esc(q)}"</li>' for q in quotes if q
        )
        if items_html:
            quotes_html = f"""
            <div class="field">
              <span class="label">Key Quotes</span>
              <ul class="quotes">{items_html}</ul>
            </div>"""

    return f"""
    <article class="item">
      <div class="item-header">
        <h2><a href="{url}" target="_blank" rel="noopener">{title}</a></h2>
        <div class="meta">
          <span class="source">{source_name}</span>
          <span class="date">{date}</span>
        </div>
      </div>
      <div class="eli5">
        <span class="label">ELI5</span>
        <p>{eli5}</p>
      </div>
      <details>
        <summary>More details</summary>
        <div class="expanded">
          <div class="field">
            <span class="label">ELI16</span>
            <p>{eli16}</p>
          </div>
          <div class="field">
            <span class="label">Why This Matters</span>
            <p>{why}</p>
          </div>
          <div class="field">
            <span class="label">What Changed</span>
            <p>{changed}</p>
          </div>{quotes_html}
          <div class="field unknowns">
            <span class="label">Confidence / Unknowns</span>
            <p>{unknowns}</p>
          </div>
        </div>
      </details>
    </article>"""


def render_page(items: list[sqlite3.Row]) -> str:
    """Render the full HTML page."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    items_html = "\n".join(render_item(item) for item in items)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Keep Up With AI</title>
  <style>
    :root {{
      --bg: #0f1117;
      --surface: #1a1d27;
      --border: #2a2d3a;
      --text: #e1e4ed;
      --text-dim: #8b8fa3;
      --accent: #6c8aff;
      --accent-dim: #4a5f99;
      --label-bg: #252838;
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
      padding: 2rem 1rem;
      max-width: 48rem;
      margin: 0 auto;
    }}
    header {{
      margin-bottom: 2.5rem;
      padding-bottom: 1.5rem;
      border-bottom: 1px solid var(--border);
    }}
    header h1 {{
      font-size: 1.75rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }}
    header .updated {{
      color: var(--text-dim);
      font-size: 0.85rem;
      margin-top: 0.25rem;
    }}
    header .count {{
      color: var(--text-dim);
      font-size: 0.85rem;
    }}
    .item {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1.25rem;
      margin-bottom: 1rem;
    }}
    .item-header h2 {{
      font-size: 1.05rem;
      font-weight: 600;
      line-height: 1.4;
    }}
    .item-header h2 a {{
      color: var(--accent);
      text-decoration: none;
    }}
    .item-header h2 a:hover {{
      text-decoration: underline;
    }}
    .meta {{
      display: flex;
      gap: 0.75rem;
      font-size: 0.8rem;
      color: var(--text-dim);
      margin-top: 0.25rem;
    }}
    .label {{
      display: inline-block;
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--accent);
      background: var(--label-bg);
      padding: 0.15rem 0.5rem;
      border-radius: 3px;
      margin-bottom: 0.35rem;
    }}
    .eli5 {{
      margin-top: 0.75rem;
    }}
    .eli5 p {{
      font-size: 0.95rem;
    }}
    details {{
      margin-top: 0.75rem;
    }}
    details summary {{
      cursor: pointer;
      font-size: 0.85rem;
      color: var(--accent-dim);
      user-select: none;
    }}
    details summary:hover {{
      color: var(--accent);
    }}
    .expanded {{
      margin-top: 0.75rem;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
    }}
    .field p {{
      font-size: 0.9rem;
      color: var(--text);
    }}
    .unknowns p {{
      color: var(--text-dim);
      font-style: italic;
    }}
    .quotes {{
      list-style: none;
      padding: 0;
    }}
    .quotes li {{
      font-size: 0.9rem;
      color: var(--text-dim);
      font-style: italic;
      padding-left: 1rem;
      border-left: 2px solid var(--border);
      margin-bottom: 0.4rem;
    }}
    .empty {{
      text-align: center;
      color: var(--text-dim);
      padding: 3rem 1rem;
    }}
    @media (max-width: 640px) {{
      body {{ padding: 1rem 0.75rem; }}
      .item {{ padding: 1rem; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Keep Up With AI</h1>
    <div class="updated">Last updated: {now}</div>
    <div class="count">{len(items)} summaries</div>
  </header>
  <main>
    {items_html if items_html.strip() else '<div class="empty"><p>No summaries yet. Run the pipeline to get started.</p></div>'}
  </main>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    log.info("=== Generator starting ===")

    if not DB_PATH.exists():
        log.error("Database not found at %s — run fetcher.py first", DB_PATH)
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    items = conn.execute(
        """SELECT items.*, sources.name as source_name
           FROM items
           JOIN sources ON items.source_id = sources.id
           WHERE items.status = 'summarized'
           ORDER BY items.published_at DESC
           LIMIT ?""",
        (MAX_DISPLAY_ITEMS,),
    ).fetchall()

    log.info("Found %d summarized items", len(items))

    OUTPUT_DIR.mkdir(exist_ok=True)
    page_html = render_page(items)
    OUTPUT_PATH.write_text(page_html, encoding="utf-8")
    log.info("Wrote %s (%d bytes)", OUTPUT_PATH, len(page_html))

    conn.close()
    log.info("=== Generator done ===")


if __name__ == "__main__":
    main()
