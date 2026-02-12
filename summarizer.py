#!/usr/bin/env python3
"""Stage 2: Summarize new items using Claude Haiku (or OpenAI fallback).

Selects items with status="new", calls the LLM to produce structured JSON
summaries, validates the output, and updates the database.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path

DB_PATH = Path("data.sqlite")
MAX_NEW_ITEMS_PER_RUN = int(os.environ.get("MAX_NEW_ITEMS_PER_RUN", "25"))
MAX_INPUT_TOKENS = 2000
MAX_OUTPUT_TOKENS = 1024
MAX_RETRIES = 3
BACKOFF_BASE = 2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Summary prompt
# ---------------------------------------------------------------------------
SUMMARY_SYSTEM_PROMPT = """You are an AI content summarizer. Given an article title and text, produce a JSON object with exactly these fields:

{
  "eli5": "Explain like I'm 5 — simple, accessible summary",
  "eli16": "Explain like I'm 16 — more technical, includes key details",
  "why_this_matters": "Why this is important or relevant",
  "what_changed": "What's new or different from before",
  "key_quotes": ["Array of genuinely useful quotes from the text, or empty array if none"],
  "confidence_unknowns": "What you're not sure about or what's missing from the source"
}

Rules:
- Output ONLY valid JSON, no markdown fences, no extra text
- All fields are required
- Keep each field to 1-2 sentences max
- key_quotes: max 2 quotes, or empty array [] if none are genuinely useful
- confidence_unknowns: 1 sentence max
- If the content is too short or unclear, do your best and note limitations in confidence_unknowns"""

FIX_JSON_PROMPT = """The following text was supposed to be valid JSON but isn't. Fix it and return ONLY the corrected JSON object. Do not add markdown fences or explanation.

Invalid JSON:
{text}"""


# ---------------------------------------------------------------------------
# LLM clients
# ---------------------------------------------------------------------------
def get_llm_client() -> tuple[str, object]:
    """Return (provider_name, client) for the configured LLM.

    Primary: Anthropic. Fallback: OpenAI.
    """
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        import anthropic
        return "anthropic", anthropic.Anthropic(api_key=anthropic_key)

    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        import openai
        return "openai", openai.OpenAI(api_key=openai_key)

    raise RuntimeError(
        "No LLM API key configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY."
    )


def call_llm(provider: str, client: object, system: str, user: str) -> str:
    """Call the LLM and return the response text. Retries with backoff."""
    for attempt in range(MAX_RETRIES):
        try:
            if provider == "anthropic":
                model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
                resp = client.messages.create(
                    model=model,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                return resp.content[0].text

            else:  # openai
                model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
                resp = client.chat.completions.create(
                    model=model,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                return resp.choices[0].message.content

        except (OSError, ValueError) as e:
            # Network errors, JSON decode errors, etc.
            wait = BACKOFF_BASE ** attempt
            log.warning("LLM attempt %d/%d failed: %s (retry in %ds)",
                        attempt + 1, MAX_RETRIES, e, wait)
            if attempt < MAX_RETRIES - 1:
                time.sleep(wait)
        except Exception as e:
            # SDK-specific errors (APIError, RateLimitError, etc.)
            # Check if it's a retryable error vs. a programming bug
            err_type = type(e).__name__
            if "Error" in err_type and any(
                k in err_type for k in ("API", "Rate", "Timeout", "Connection", "Server")
            ):
                wait = BACKOFF_BASE ** attempt
                log.warning("LLM attempt %d/%d failed (%s): %s (retry in %ds)",
                            attempt + 1, MAX_RETRIES, err_type, e, wait)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(wait)
            else:
                raise  # Don't swallow unexpected errors

    raise RuntimeError(f"All {MAX_RETRIES} LLM attempts failed")


# ---------------------------------------------------------------------------
# JSON validation
# ---------------------------------------------------------------------------
REQUIRED_FIELDS = {"eli5", "eli16", "why_this_matters", "what_changed",
                   "key_quotes", "confidence_unknowns"}


def parse_summary_json(text: str) -> dict | None:
    """Try to parse the LLM response as valid summary JSON."""
    # Strip markdown fences if present
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Try direct parse first
    data = _try_parse(text)
    if data:
        return data

    # Try to repair truncated JSON by closing open strings/arrays/objects
    for suffix in ['"}\n}', '"\n}', '"]\n}', ']\n}', '\n}', '}']:
        data = _try_parse(text + suffix)
        if data:
            log.info("  Repaired truncated JSON")
            return data

    return None


def _try_parse(text: str) -> dict | None:
    """Attempt to parse text as valid summary JSON dict."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    if not REQUIRED_FIELDS.issubset(data.keys()):
        return None
    return data


# ---------------------------------------------------------------------------
# Truncation for token budget
# ---------------------------------------------------------------------------
def truncate_for_input(text: str) -> str:
    """Rough truncation to stay within input token budget.

    ~4 chars per token is a conservative estimate. We allow MAX_INPUT_TOKENS
    for the article content portion of the prompt.
    """
    max_chars = MAX_INPUT_TOKENS * 4
    if len(text) > max_chars:
        return text[:max_chars] + "\n[truncated]"
    return text


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def summarize_item(provider: str, client: object, title: str, content: str) -> tuple[dict, str]:
    """Summarize a single item. Returns (summary_dict, model_used)."""
    content = truncate_for_input(content)
    user_prompt = f"Title: {title}\n\nContent:\n{content}"

    model = (os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
             if provider == "anthropic"
             else os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))

    response = call_llm(provider, client, SUMMARY_SYSTEM_PROMPT, user_prompt)
    summary = parse_summary_json(response)

    if summary is None:
        # Retry once with fix-JSON prompt
        log.warning("Invalid JSON from LLM, attempting fix...")
        fix_prompt = FIX_JSON_PROMPT.format(text=response)
        fixed_response = call_llm(provider, client, "Fix this JSON.", fix_prompt)
        summary = parse_summary_json(fixed_response)

        if summary is None:
            raise ValueError("Could not get valid JSON after retry")

    return summary, model


def main() -> None:
    log.info("=== Summarizer starting ===")

    if not DB_PATH.exists():
        log.error("Database not found at %s — run fetcher.py first", DB_PATH)
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # One-time: mark all pre-October 2025 items as skipped
    old_count = conn.execute(
        """UPDATE items SET status = 'skipped'
           WHERE status = 'new' AND published_at < '2025-10-01'"""
    ).rowcount
    conn.commit()
    if old_count > 0:
        log.info("Marked %d pre-October 2025 items as skipped", old_count)

    # Select new items from October 2025 onward, up to the hard cap
    rows = conn.execute(
        """SELECT id, title, content_text FROM items
           WHERE status = 'new'
             AND (published_at >= '2025-10-01' OR published_at IS NULL)
           ORDER BY published_at DESC
           LIMIT ?""",
        (MAX_NEW_ITEMS_PER_RUN,),
    ).fetchall()

    if not rows:
        log.info("No new items to summarize")
        conn.close()
        return

    log.info("Found %d new items to summarize (cap: %d)", len(rows), MAX_NEW_ITEMS_PER_RUN)

    provider, client = get_llm_client()
    log.info("Using LLM provider: %s", provider)

    success_count = 0
    error_count = 0

    for row in rows:
        log.info("Summarizing: %s", row["title"])
        content = row["content_text"] or ""

        if not content.strip():
            log.warning("  Skipping — no content text")
            conn.execute(
                "UPDATE items SET status='skipped' WHERE id=?", (row["id"],)
            )
            conn.commit()
            continue

        try:
            summary, model_used = summarize_item(
                provider, client, row["title"], content
            )
            conn.execute(
                """UPDATE items
                   SET summary_json=?, model_used=?, status='summarized'
                   WHERE id=?""",
                (json.dumps(summary), model_used, row["id"]),
            )
            conn.commit()
            success_count += 1
            log.info("  Done (%s)", model_used)

        except Exception as e:
            error_count += 1
            log.error("  Failed: %s", e)

        time.sleep(0.5)  # Rate limiting courtesy

    log.info("=== Summarizer done: %d succeeded, %d failed ===",
             success_count, error_count)
    conn.close()


if __name__ == "__main__":
    main()
