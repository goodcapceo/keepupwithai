# Claude Code Guidelines for Keep Up With AI

## Project Overview

Keep Up With AI is a personal AI content summarizer pipeline that aggregates RSS feeds from 30+ AI/tech sources, summarizes new items using Claude Haiku (with OpenAI fallback), and generates a static HTML page with the latest summaries.

Pipeline: `fetcher.py` → `summarizer.py` → `generator.py` → `site/index.html`
Stack: Python 3.11+, SQLite, Anthropic API, GitHub Actions for daily cron.

**MUST** rules are enforced by CI. **SHOULD** rules are strongly recommended.

---

## Domain Vocabulary

### Pipeline

- **Source**: An RSS feed, YouTube channel, blog, or newsletter tracked in `feeds.yaml` and the `sources` DB table
- **Item**: A single article, video, or post fetched from a source. Lives in the `items` DB table
- **Summary**: Structured JSON output from the LLM containing ELI5, ELI16, why_this_matters, what_changed, key_quotes, confidence_unknowns
- **Status**: An item is either `"new"` (fetched, not yet summarized) or `"summarized"` (LLM summary complete)

### Feed Types

- **rss**: Standard RSS/Atom feed
- **youtube**: YouTube channel RSS feed (`/feeds/videos.xml?channel_id=...`)
- **substack**: Substack newsletter (RSS at `<root>/feed`)
- **medium**: Medium profile or publication feed
- **site**: Generic website with discoverable RSS

---

## Implementation Best Practices

### Before Coding

- **BP-1 (MUST)** Ask clarifying questions before implementing
- **BP-2 (MUST)** Start complex tasks in plan mode. Draft and confirm approach before writing code. If implementation goes sideways, stop and re-plan
- **BP-3 (SHOULD)** If ≥2 approaches exist, list clear pros and cons
- **BP-4 (MUST)** For API key handling or network request code, always review for security
- **BP-5 (MUST)** Explore the codebase for reusable functions before writing new ones. Check existing modules for shared helpers
- **BP-6 (MUST)** Verify actual file paths and codebase structure using Read/Glob/Grep before making changes
- **BP-7 (MUST)** Do what's asked first. Do not autonomously start adjacent tasks unless explicitly requested
- **BP-8 (MUST)** If an approach fails, try up to 3 alternative strategies. After 3 failed attempts, stop and ask for guidance

### While Coding

- **C-1 (SHOULD)** Write small testable functions over large monolithic ones
- **C-2 (MUST)** Name functions with existing domain vocabulary (source, item, summary, status)
- **C-3 (SHOULD NOT)** Introduce classes when small testable functions suffice
- **C-5 (MUST)** Store all dates in UTC ISO 8601 format
- **C-7 (SHOULD NOT)** Add comments except for critical caveats or non-obvious behavior
- **C-8 (SHOULD NOT)** Extract new function unless reused elsewhere or drastically improves readability

### Testing

- **T-1 (SHOULD)** Colocate tests in a `tests/` directory with `test_<module>.py` naming
- **T-3 (MUST)** Separate pure-logic unit tests from network/DB-touching integration tests
- **T-4 (SHOULD)** Prefer integration tests over heavy mocking
- **T-7 (MUST)** Test error paths, not just happy paths

### Database

- **D-1 (MUST)** Use parameterized queries only — never string-format SQL values
- **D-2 (MUST)** Schema uses INTEGER PRIMARY KEY (auto-increment) per spec
- **D-3 (MUST)** Deduplicate items by `url_hash` (SHA-256 of URL)

### Security

- **S-1 (MUST)** API keys from env vars only — never hardcode, never log
- **S-2 (MUST)** Never log full article content or API responses in production
- **S-3 (MUST)** Enforce `MAX_NEW_ITEMS_PER_RUN` hard cap (default 25)
- **S-4 (MUST)** Enforce token limits: 2000 input, 500 output per item
- **S-5 (MUST)** 15-second timeout on all HTTP requests
- **S-6 (MUST)** Exponential backoff on all network and API calls
- **S-7 (MUST)** Never expose stack traces in generated HTML

### Tooling Gates

- **G-1 (MUST)** `python -m py_compile <file>` passes for all Python files
- **G-2 (SHOULD)** `ruff check` passes (if ruff is installed)
- **G-3 (MUST)** Pipeline runs locally: `python fetcher.py && python summarizer.py && python generator.py`

### Git

- **GH-1 (MUST)** Use Conventional Commits format
- **GH-2 (MUST)** Never reference Claude, Anthropic, or AI in commit messages
- **GH-3 (SHOULD)** Keep commits atomic and reversible

---

## API Integration Patterns

### Anthropic (primary LLM for summarization)

- Use `anthropic` Python SDK
- Model default: `claude-haiku-4-5-20251001` (override via `ANTHROPIC_MODEL` env var)
- Max input tokens: 2000 per item, max output tokens: 500
- Retry with exponential backoff on rate limits (429) and server errors (5xx)
- If JSON response is invalid, retry once with a "fix this JSON" prompt

### OpenAI (fallback LLM)

- Use `openai` Python SDK
- Only used when `ANTHROPIC_API_KEY` is not set
- Model default: `gpt-4o-mini` (override via `OPENAI_MODEL` env var)
- Same token limits and retry behavior as Anthropic

---

## Code Organization Principles

**Architecture:** Sequential pipeline — three standalone scripts sharing a SQLite database.

```
/
  feeds.yaml          # Source definitions
  fetcher.py          # Stage 1: fetch feeds → insert items
  summarizer.py       # Stage 2: summarize new items → update items
  generator.py        # Stage 3: read summaries → write HTML
  setup_youtube.py    # One-time: resolve YouTube channel IDs
  requirements.txt    # Python dependencies
  .env.example        # Required environment variables
  .github/workflows/daily.yml
  site/index.html     # Generated output (committed)
  data.sqlite         # Runtime DB (gitignored, cached in CI)
```

**Key principles:**
- Each pipeline stage is a standalone script, runnable independently
- All shared state goes through SQLite — no in-memory passing between stages
- `feeds.yaml` is the single source of truth for what sources to track
- Keep dependencies minimal — prefer stdlib where reasonable

---

## Writing Functions Checklist

Before marking a function complete, verify:

1. Can you easily follow what it's doing?
2. Does function have high cyclomatic complexity? (If yes, split)
3. Any unused parameters?
4. Is function easily testable without mocking?
5. Brainstorm 3 better function names — is current best?
6. For API/network code: Has security review been done?

---

## Environment Variables

Required:
- `ANTHROPIC_API_KEY` — Anthropic API key for Claude Haiku summarization

Optional:
- `ANTHROPIC_MODEL` — Override default model (default: `claude-haiku-4-5-20251001`)
- `OPENAI_API_KEY` — Fallback LLM if Anthropic not set
- `OPENAI_MODEL` — Override fallback model (default: `gpt-4o-mini`)
- `MAX_NEW_ITEMS_PER_RUN` — Hard cap on items to summarize per run (default: 25)
- `MAX_CHARS_PER_ITEM` — Max content length per item (default: 8000)

Never commit `.env` files. Use `.env.example` as template.

---

## Remember Shortcuts

### QNEW

Understand all BEST PRACTICES listed in CLAUDE.md.
Your code SHOULD ALWAYS follow these best practices.
Read the domain vocabulary and use consistent naming.

### QPLAN

Enter plan mode first. Pour energy into the plan so implementation can be 1-shot.
If something goes sideways during implementation, STOP — switch back to plan mode and re-plan.

**QPLAN produces a plan only. It does NOT start implementation. Wait for explicit approval, then use QCODE to implement.**

Analyze similar parts of codebase and determine whether your plan:
- is consistent with rest of codebase
- introduces minimal changes
- reuses existing code

Output: a numbered implementation plan with files to create/modify, tests to write, and any risks identified. Then STOP and wait for approval.

### QCODE

**Only run after QPLAN has been approved.** Implement the approved plan.

1. Follow the pipeline architecture — standalone scripts sharing SQLite
2. Run `python -m py_compile <file>` on new files
3. Run the pipeline locally to verify
4. Scan for duplicated code — consolidate if found

### QCHECK

You are a SKEPTICAL senior software engineer.
Enter plan mode for this review — analyze, do not modify code.

1. CLAUDE.md checklist Writing Functions Best Practices
2. CLAUDE.md checklist Implementation Best Practices
3. Security review for API key handling and network requests
4. Duplication check — search codebase for similar existing code

### QGIT

Create commit following Conventional Commits format:
`<type>[optional scope]: <description>`

Types: fix, feat, build, chore, ci, docs, style, refactor, perf, test

Remove any `Co-authored-by: Claude` or AI co-authoring signatures from the commit.

Examples:
- `feat(fetcher): add RSS feed ingestion with ETag support`
- `fix(summarizer): handle malformed JSON responses from LLM`
- `ci: add daily GitHub Actions workflow`

---

## Self-Improvement Protocol

When I correct Claude Code on a mistake or pattern:

1. Claude Code should **propose** a new CLAUDE.md rule that prevents the mistake from recurring — do not auto-add it
2. Keep proposed rules concise and actionable
3. Suggest the most relevant existing section for placement
