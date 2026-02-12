# Keep Up With AI

A personal AI content summarizer that aggregates 30+ AI/tech blogs, newsletters, and YouTube channels into a single daily digest page.

## How it works

1. **`fetcher.py`** pulls new items from RSS feeds into SQLite
2. **`summarizer.py`** sends new items to Claude Haiku for structured summaries
3. **`generator.py`** renders summaries into a static HTML page at `site/index.html`
4. **GitHub Actions** runs the pipeline daily and commits the updated page

## Setup

```bash
# Clone and install
git clone <repo-url>
cd keepupwithai
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# Run the pipeline
python fetcher.py
python summarizer.py
python generator.py

# Open the result
open site/index.html
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes* | — | Anthropic API key for Claude Haiku |
| `ANTHROPIC_MODEL` | No | `claude-haiku-4-5-20251001` | Model override |
| `OPENAI_API_KEY` | No | — | Fallback if Anthropic not set |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | Fallback model override |
| `MAX_NEW_ITEMS_PER_RUN` | No | `25` | Hard cap on items per run |
| `MAX_CHARS_PER_ITEM` | No | `8000` | Max content length per item |

\* Either `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` must be set.

## Adding new sources

Edit `feeds.yaml` and add an entry:

```yaml
- name: Source Name
  url: https://example.com/
  type: site  # one of: rss, youtube, substack, medium, site
```

For YouTube channels, include the `feed_url`:

```yaml
- name: Channel Name
  url: https://www.youtube.com/@handle
  type: youtube
  feed_url: https://www.youtube.com/feeds/videos.xml?channel_id=UC...
```

Use `setup_youtube.py` to resolve channel IDs from handles.

## GitHub Actions

The pipeline runs daily at 06:00 UTC via `.github/workflows/daily.yml`.

**Required secrets:** `ANTHROPIC_API_KEY`

The SQLite database is cached between runs. `site/index.html` is committed automatically.

To trigger manually: Actions tab → "Daily AI Digest" → "Run workflow".

## Summary format

Each item gets a structured summary with:

- **ELI5** — simple, accessible explanation
- **ELI16** — more technical summary
- **Why This Matters** — relevance and importance
- **What Changed** — what's new
- **Key Quotes** — notable quotes (when present)
- **Confidence / Unknowns** — what the model isn't sure about

## Troubleshooting

- **No items fetched**: Check that the source's RSS feed is accessible. The fetcher logs failed URLs.
- **Feed not found**: Some sites don't have RSS. The fetcher probes common paths (`/feed`, `/rss`, `/rss.xml`) and checks for `<link rel="alternate">` tags.
- **Summarizer errors**: Check your API key is valid and has credits. The summarizer retries 3 times with backoff.
- **Empty page**: Run all three scripts in order. The generator needs summarized items in the database.

## Known Feed Issues

Some sources may not have discoverable RSS feeds. If a source fails during `fetcher.py`, it will be marked `active=0` in the database and logged. Check the fetcher output for details.
