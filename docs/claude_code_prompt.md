# Claude Code Build Prompt — AI Content Summarizer

Paste this entire file into Claude Code as your first message.

---

## PROMPT

You are Claude Code acting as a senior engineer. Build a small personal AI content summarizer pipeline end-to-end in one pass.

### GOAL
- Daily job pulls new items from the source list below into SQLite
- Summarizes new items using Claude Haiku (Anthropic API) with OpenAI as fallback toggle
- Generates a single static HTML page at `site/index.html` showing the latest summaries
- Runs daily via GitHub Actions and commits updated `site/index.html`

### CONSTRAINTS
- Check once per day only
- No tags, priorities, or fetch intervals
- Two item states only: `new` and `summarized`
- No email digest
- Single page output only (no detail pages, no tag pages)
- Robust: retries/backoff, timeouts, strict dedupe, clear logging

---

### FILES TO CREATE

```
/
  feeds.yaml
  fetcher.py
  summarizer.py
  generator.py
  requirements.txt
  .env.example
  .github/workflows/daily.yml
  site/index.html   ← generated; add placeholder initially
  README.md
```

---

### RUNTIME & ENV

- Python 3.11+
- SQLite file: `data.sqlite` in repo root
- Minimal dependencies — prefer stdlib where reasonable
- Use: `requests`, `feedparser`, `beautifulsoup4`, `anthropic`, `openai` (optional)

---

### SECURITY & COST CONTROLS (non-negotiable)

- API keys from env vars only — never hardcode
- Store only: title, url, published_at, cleaned/truncated text excerpt
- `MAX_NEW_ITEMS_PER_RUN` = 25 (hard cap)
- Max tokens per item: 2000 input, 500 output
- Exponential backoff on all network and API calls
- 15-second timeout on all HTTP requests

---

### DB SCHEMA (two tables only)

**sources**
```
id INTEGER PRIMARY KEY
name TEXT
source_url TEXT
feed_url TEXT
type TEXT              (rss|youtube|substack|medium|site)
active INTEGER         (1/0)
last_fetch_at TEXT
etag TEXT NULL
last_modified TEXT NULL
```

**items**
```
id INTEGER PRIMARY KEY
source_id INTEGER
title TEXT
url TEXT
guid TEXT NULL
published_at TEXT NULL
fetched_at TEXT
content_text TEXT      (cleaned, truncated to 8000 chars)
url_hash TEXT UNIQUE   (sha256 of url)
status TEXT            ("new"|"summarized")
summary_json TEXT NULL
model_used TEXT NULL
```

---

### PIPELINE BEHAVIOR

#### fetcher.py
1. Load `feeds.yaml`
2. Upsert sources into DB
3. Fetch each feed using ETag/Last-Modified headers if available
4. Dedupe by `url_hash` — insert new items only
5. Extract readable text:
   - Prefer RSS content field if present
   - Otherwise fetch article page and extract main text with BeautifulSoup heuristics
   - Truncate to 8000 chars
6. Set `status = "new"`

#### summarizer.py
1. Select up to `MAX_NEW_ITEMS_PER_RUN` items where `status = "new"`
2. For each item, call model and produce **strict JSON** with these fields:
   - `eli5` — explain like I'm 5
   - `eli16` — explain like I'm 16 (more technical)
   - `why_this_matters`
   - `what_changed`
   - `key_quotes` — optional array, only if genuinely useful quotes exist
   - `confidence_unknowns` — what the model isn't sure about
3. If JSON is invalid, retry once with a "fix JSON" prompt
4. Save `summary_json`, `model_used`, set `status = "summarized"`

**Model config:**
- Primary: Anthropic Claude Haiku via `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` (default: `claude-haiku-4-5-20251001`)
- Fallback: OpenAI via `OPENAI_API_KEY` / `OPENAI_MODEL` if Anthropic not set

#### generator.py
1. Read most recent 100 summarized items sorted by `published_at` desc
2. Write `site/index.html` with:
   - Page title + last updated timestamp
   - For each item: title (linked), source name, date, ELI5, ELI16, why this matters, what changed, confidence/unknowns
   - Clean minimal inline CSS — readable on desktop and mobile
   - Optional expand/collapse per item (simple HTML `<details>` tag is fine)

#### GitHub Action (`.github/workflows/daily.yml`)
- Trigger: daily cron + manual dispatch (`workflow_dispatch`)
- Steps: checkout → install deps → run `fetcher.py` → `summarizer.py` → `generator.py` → commit `site/index.html`
- **Do NOT commit `data.sqlite`** — cache it between runs using `actions/cache` keyed on a stable key
- Secrets needed: `ANTHROPIC_API_KEY` (and optionally `OPENAI_API_KEY`)

---

### PRE-RESOLVED YOUTUBE CHANNEL IDs
The following channels have been pre-resolved and should be used directly in feeds.yaml without any resolution step:
- Underfitted (Santiago): `UCgLxmJ8xER7Y7sywMN5SfWg`
- AI Jason Z: `UCAnJ6_Zjv7PzVTKtbG8nH8A`
- IndyDevDan: `UC_x36zCEGilGpB1m-V4gmjg`
- Andrej Karpathy: `UCXUPKJO5MZQN11PqgIvyuvQ`
- Dwarkesh Patel: `UCXl4i9dYBrFOabk0xGmbkRA`

These 4 YouTube channels still need resolution at setup time (run once, then hardcode result):
- `@sabrina_ramonov`
- `@AlexFinnOfficial`
- `@AcquiredFM`
- `@ryanlpeterman`

To resolve them, write a one-time `setup_youtube.py` script that fetches `https://www.youtube.com/@HANDLE`, parses the HTML for `"channelId":"UC..."` or `"externalId":"UC..."`, and prints the RSS feed URL. If bot detection blocks it, print a clear fallback message: "Open https://www.youtube.com/@HANDLE in your browser, right-click → View Source, search for channelId, and paste the UC... value into feeds.yaml".

---

### FEED DISCOVERY RULES

For each source URL, resolve the correct RSS feed:

- **Substack**: `source_url` trimmed to root + `/feed`
- **Medium profile**: `https://medium.com/feed/@USERNAME`
- **Medium publication**: `https://medium.com/feed/PUBLICATION`
- **Website**: check for `<link rel="alternate" type="application/rss+xml">`, then try `/feed`, `/rss`, `/rss.xml`, `/atom.xml`, `/feed.xml`
- **YouTube handle or URL**: resolve `channel_id` from page HTML (no API key required), then build: `https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID`

Validate each `feed_url` by fetching it and confirming feedparser parses it with entries.
If a feed fails validation, mark `active=0` and log it in README under "Known Feed Issues".

---

### SOURCE LIST

Build `feeds.yaml` from this list:

```
# Blogs & Newsletters
- name: Anthropic
  url: https://www.anthropic.com/

- name: Sebastian Raschka
  url: https://www.svpino.com/

- name: Allie K. Miller
  url: https://www.alliekmiller.com/

- name: Sabrina Ramonov (Blog)
  url: https://www.sabrina.dev/

- name: Lilian Weng
  url: https://lilianweng.github.io/

- name: Andrej Karpathy (Blog)
  url: https://karpathy.ai/

- name: Boris Cherny
  url: https://borischerny.com/

- name: The Vibe Marketer
  url: https://www.thevibemarketer.com/

- name: Developing Dev
  url: https://www.developing.dev/

- name: Social Growth Engineers
  url: https://www.socialgrowthengineers.com/

- name: Thariq
  url: https://www.thariq.io/

- name: Alex Finn (Blog)
  url: https://www.alexfinn.ai/

# Substacks
- name: Regy Perlera
  url: https://regyperlera.substack.com/

- name: Erik J. Larson
  url: https://erikjlarson.substack.com/

- name: Gary Marcus
  url: https://garymarcus.substack.com/

- name: Zara Zhang
  url: https://zarazhang.substack.com/

- name: RSS DS+AI Section
  url: https://rssdsaisection.substack.com/

# Newsletters (RSS available)
- name: Ethan Mollick – One Useful Thing
  url: https://www.oneusefulthing.org/

- name: DeepLearning.AI – The Batch
  url: https://www.deeplearning.ai/the-batch/

- name: Aakash Gupta
  url: https://www.news.aakashg.com/

- name: AI Hero
  url: https://www.aihero.dev/newsletter

- name: AI Supremacy
  url: https://www.ai-supremacy.com/

- name: Scott Galloway – No Mercy No Malice
  url: https://profgmedia.com/no-mercy-no-malice/

# Medium
- name: Ross W. Green
  url: https://medium.com/@Ross_W_Green

- name: GoPubby AI
  url: https://ai.gopubby.com/

# Research & Institutions
- name: Google Research Blog
  url: https://research.google/blog/

- name: MIT News – AI
  url: https://news.mit.edu/topic/artificial-intelligence

- name: Startup Archive
  url: https://www.startuparchive.org/

- name: Founders Tribune
  url: https://www.founderstribune.org/

# YouTube Channels (channel IDs pre-resolved where confirmed)
- name: Underfitted (Santiago)
  url: https://www.youtube.com/@underfitted
  feed_url: https://www.youtube.com/feeds/videos.xml?channel_id=UCgLxmJ8xER7Y7sywMN5SfWg
  channel_id: UCgLxmJ8xER7Y7sywMN5SfWg

- name: Sabrina Ramonov (YouTube)
  url: https://www.youtube.com/@sabrina_ramonov
  # channel_id: NEEDS RESOLUTION — use page source scrape of @sabrina_ramonov

- name: Alex Finn (YouTube)
  url: https://www.youtube.com/@AlexFinnOfficial
  # channel_id: NEEDS RESOLUTION — use page source scrape of @AlexFinnOfficial

- name: Acquired
  url: https://www.youtube.com/@AcquiredFM
  # channel_id: NEEDS RESOLUTION — use page source scrape of @AcquiredFM

- name: AI Jason Z
  url: https://www.youtube.com/@AIJasonZ
  feed_url: https://www.youtube.com/feeds/videos.xml?channel_id=UCAnJ6_Zjv7PzVTKtbG8nH8A
  channel_id: UCAnJ6_Zjv7PzVTKtbG8nH8A

- name: IndyDevDan
  url: https://www.youtube.com/@indydevdan
  feed_url: https://www.youtube.com/feeds/videos.xml?channel_id=UC_x36zCEGilGpB1m-V4gmjg
  channel_id: UC_x36zCEGilGpB1m-V4gmjg

- name: Andrej Karpathy (YouTube)
  url: https://www.youtube.com/@AndrejKarpathy
  feed_url: https://www.youtube.com/feeds/videos.xml?channel_id=UCXUPKJO5MZQN11PqgIvyuvQ
  channel_id: UCXUPKJO5MZQN11PqgIvyuvQ

- name: Dwarkesh Patel
  url: https://www.youtube.com/@DwarkeshPatel
  feed_url: https://www.youtube.com/feeds/videos.xml?channel_id=UCXl4i9dYBrFOabk0xGmbkRA
  channel_id: UCXl4i9dYBrFOabk0xGmbkRA

- name: Ryan L. Peterman
  url: https://www.youtube.com/@ryanlpeterman
  # channel_id: NEEDS RESOLUTION — use page source scrape of @ryanlpeterman
```

**Skip for now (requires paid API or unreliable):**
- Alexandr Wang (X/Twitter — skip)
- Stratechery (paywalled RSS — skip)
- Tom Doerr (verify feed exists before including)

---

### DELIVERABLE QUALITY BAR

- Pipeline runs locally with: `python fetcher.py && python summarizer.py && python generator.py`
- `site/index.html` is produced after those three commands
- README includes: setup steps, how to add new sources, troubleshooting
- `.env.example` documents all required env vars
- Feed validation failures are documented, not silently swallowed

---

### .env.example contents

```
ANTHROPIC_API_KEY=your_key_here
ANTHROPIC_MODEL=claude-haiku-4-5-20251001
OPENAI_API_KEY=optional_fallback
OPENAI_MODEL=gpt-4o-mini
MAX_NEW_ITEMS_PER_RUN=25
MAX_CHARS_PER_ITEM=8000
```
