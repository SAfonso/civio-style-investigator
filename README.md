# civio-style-investigator

An autonomous agent that investigates questions about Spanish public data and produces structured Markdown reports with cited sources. Ask it a question in natural language; it searches official databases, cross-references what it finds, and writes a report — without any manual steps in between.

---

## About this project

This is a learning project built to understand the **ReAct pattern** (Reason → Act → Observe) and how to build tool-using agents with the Anthropic API.

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
 │   Reason    │  Claude decides what to do next
 └──────┬──────┘
        │ tool_use
        ▼
 ┌─────────────┐
 │     Act     │  Execute the chosen tool
 └──────┬──────┘
        │ tool_result
        ▼
 ┌─────────────┐
 │   Observe   │  Result added to context
 └──────┬──────┘
        │
        ├── more questions? → back to Reason
        │
        └── done? → write_report → Markdown file saved
```

The loop stops when the agent calls `write_report` (investigation complete) or when `MAX_ITERATIONS` is reached (safety limit).

---

## Data sources

| Source | What it provides |
|---|---|
| [datos.gob.es](https://datos.gob.es) | Spanish open data catalogue — spending, demographics, contracts, environment, and more |
| [BOE](https://boe.es) | Official State Gazette — legislation, regulations, and official dispositions |
| Any public URL | `fetch_document` downloads and extracts text from any HTML, XML, or JSON endpoint |

---

## Installation

```bash
git clone https://github.com/your-user/civio-style-investigator.git
cd civio-style-investigator

pip install -r requirements.txt

cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
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
│   ├── search_boe.py         # Search and fetch documents from the BOE
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
| `ANTHROPIC_API_KEY` | — | Your Anthropic API key (required) |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Claude model used for reasoning and cross-referencing |
| `ANTHROPIC_MAX_TOKENS` | `1000` | Max tokens per API response |
| `MAX_ITERATIONS` | `10` | Safety limit on ReAct loop iterations |
| `MAX_TOKENS_PER_TOOL` | `5000` | Max characters returned by each tool (fetch, BOE) |

---

## Roadmap

- **More data sources** — INE (National Statistics Institute), municipal transparency portals, Contratación del Estado
- **Session memory** — SQLite cache so repeated queries don't re-fetch the same documents
- **Simple web UI** — a minimal interface to submit queries and browse reports without touching the terminal
