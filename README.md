# civio-style-investigator

An autonomous agent that investigates questions about Spanish public data and produces structured Markdown reports with cited sources. Ask it a question in natural language; it searches official databases, cross-references what it finds, and writes a report — without any manual steps in between.

---

## Current status

- **Working** — runs end-to-end with Gemini 2.5 Flash-Lite (free tier)
- **Data sources implemented:** datos.gob.es open catalogue + BOE daily summary (last 3 days)
- **Rate limiting handled** — configurable delay between calls (`GEMINI_REQUEST_DELAY`) and automatic retry with 60s backoff on 429 errors
- **Always produces a report** — even when the agent finds no data or hits the iteration limit, a Markdown report is generated with the limitation explained

---

## About this project

This is a learning project built to understand the **ReAct pattern** (Reason → Act → Observe) and how to build tool-using agents with the Gemini API.

It is inspired by the investigative workflow of [CIVIO](https://civio.es), the Spanish data-journalism nonprofit, which routinely combines datos.gob.es, the BOE, and other public sources to hold institutions accountable.

Anyone can use this as a starting point to learn the same concepts: how an LLM decides which tool to call, how results feed back into the context, and how to turn a pile of raw data into a readable report.

---

## How it works

The agent runs a **ReAct loop**: it reasons about the question, picks a tool, observes the result, and reasons again — until it has enough information to write the report.

```
User question
      │
      ▼
 ┌─────────────┐
 │   Reason    │  The model decides what to do next
 └──────┬──────┘
        │ function_call
        ▼
 ┌─────────────┐
 │     Act     │  Execute the chosen tool
 └──────┬──────┘
        │ function_response
        ▼
 ┌─────────────┐
 │   Observe   │  Result added to context
 └──────┬──────┘
        │
        ├── more questions? → back to Reason
        │
        └── done? → write_report → Markdown file saved
```

The loop stops when the agent calls `write_report` (investigation complete), responds with plain text (no data found), or when `MAX_ITERATIONS` is reached. In all three cases a report is generated.

---

## Data sources

| Source | What it provides | How it's searched |
|---|---|---|
| [datos.gob.es](https://datos.gob.es) | Spanish open data catalogue — spending, demographics, contracts, environment | By title and keyword, per significant word in the query |
| [BOE](https://boe.es) | Official State Gazette — legislation, regulations, official dispositions | Daily summary for the last 3 days, filtered by keyword in title |
| Any public URL | Raw content from any endpoint | `fetch_document` downloads and parses HTML, XML, or JSON |

---

## Installation

```bash
git clone https://github.com/your-user/civio-style-investigator.git
cd civio-style-investigator

pip install -r requirements.txt

cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

---

## Usage

```bash
python agent.py "¿cuánto gasta el Ayuntamiento de Madrid en consultoría?"
```

Or use one of the included examples:

```bash
python agent.py "$(cat examples/query_simple.txt)"
python agent.py "$(cat examples/query_complex.txt)"
```

Reports are saved automatically to `reports/` as Markdown files named `YYYYMMDD_HHMMSS_slug.md`.

---

## Project structure

```
civio-style-investigator/
├── agent.py                  # Main ReAct loop — entry point
├── prompts/
│   └── system.md             # System prompt that defines the agent's behaviour
├── tools/
│   ├── search_datasets.py    # Search the datos.gob.es open data catalogue
│   ├── search_boe.py         # Search BOE daily summary by keyword
│   ├── fetch_document.py     # Download any public URL (HTML, XML, JSON)
│   ├── cross_reference.py    # LLM-powered cross-analysis of two sources
│   ├── write_report.py       # Generate and save the final Markdown report
│   └── utils/
│       ├── http.py           # Shared HTTP helpers (fetch with timeout)
│       └── xml_parser.py     # Shared XML text extraction helper
├── examples/
│   ├── query_simple.txt      # Single-source question
│   ├── query_complex.txt     # Multi-source, cross-reference question
│   ├── query_no_data.txt     # Question with likely no available data
│   └── query_ambiguous.txt   # Vague question that needs clarification
├── reports/                  # Generated reports (created on first run)
├── .env.example              # Environment variable template
├── requirements.txt          # Python dependencies
└── PROJECT.md                # Original project specification
```

---

## Included examples

| File | Purpose |
|---|---|
| `query_simple.txt` | A question with a direct answer in datos.gob.es — good for a first smoke test |
| `query_complex.txt` | A question that requires fetching from multiple sources and cross-referencing them |
| `query_no_data.txt` | A hyper-specific question that likely has no public data — tests graceful degradation |
| `query_ambiguous.txt` | A vague question — tests whether the agent asks for clarification or makes assumptions |

---

## Configuration

All settings are read from `.env` at startup. Copy `.env.example` and fill in your API key.

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | — | Your Gemini API key (required) |
| `GEMINI_MODEL` | `gemini-2.5-flash-lite` | Model used for reasoning and cross-referencing |
| `GEMINI_MAX_TOKENS` | `1000` | Max tokens per API response |
| `GEMINI_REQUEST_DELAY` | `12` | Seconds to wait between API calls (free tier rate limiting) |
| `MAX_ITERATIONS` | `10` | Safety limit on ReAct loop iterations |
| `MAX_TOKENS_PER_TOOL` | `5000` | Max characters returned by each tool (fetch, BOE) |

---

## Known limitations

- **search_boe** — only searches dispositions from the last 3 days. The BOE does not offer full-text search over its historical archive via its open data API.
- **search_datasets** — searches by keyword in dataset titles, not full-text across dataset contents. Queries are split into significant words (stopwords filtered) and searched individually.
- **No session memory** — each run starts from scratch. Results are not cached between executions.
- **Gemini free tier** — Flash-Lite allows 15 RPM. The default 12-second delay between calls keeps usage within limits; adjust `GEMINI_REQUEST_DELAY` if you have a paid plan.

---

## Lessons learned

These are the non-obvious things discovered while building this, documented so the next person doesn't have to rediscover them.

**datos.gob.es has no free-text search.** The API uses semantic path routes: `/dataset/title/{query}`, `/dataset/keyword/{query}`, `/dataset/theme/{id}`, etc. A `?q=` parameter does not exist. Multi-word queries need to be split and searched per word.

**The BOE open data API has no historical full-text search.** The `/legislacion-consolidada` endpoint supports structured queries but not keyword search across the full archive. The daily summary (`/boe/sumario/YYYYMMDD`) is the most reliable endpoint — it returns all dispositions published on a given day and can be filtered locally by keyword in the title.

**Read the API docs before writing code.** Both of the above cost significant refactoring time. The correct endpoint structure was only found by reading the official open data documentation, not by guessing from parameter names or trying common REST conventions.

**LLM provider swaps are cheap if the abstraction is right.** Migrating from Anthropic Claude to Gemini required changes in exactly two files: `agent.py` (tool call format, message history format, client initialization) and `tools/cross_reference.py` (the only tool that calls an LLM directly). All other tools — search, fetch, write — are pure Python and are completely provider-agnostic.

**The agent's intelligence is bounded by its toolset.** The ReAct loop itself is simple; the quality of the investigation depends entirely on what tools are available and how well they cover the question's domain. Adding a new source (e.g. INE) improves results without touching the loop logic.

---

## Roadmap

**v2 — More data sources**
- `search_ine()` — INE has a documented REST API for demographic and economic statistics
- `search_hacienda()` — MINHACIENDA transparency portal for public spending data
- BOE historical search via SPARQL endpoint (when available)

**v3 — Memory and UX**
- Session memory with SQLite to cache results and avoid re-fetching the same documents
- Simple web UI to submit queries and browse reports without a terminal
