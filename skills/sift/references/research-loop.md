# sift research loop architecture

## Overview

The research loop combines planning, web search, embedding-based relevance ranking,
deep scraping (quality mode), streaming synthesis, and auto-save persistence.

```
User query
    |
    v
loop.py::run()          -- iterative tool-calling researcher
    |-- plan tool        -- LLM states reasoning
    |-- search tool      -- SearXNG queries -> embed-rank results
    |-- scrape_url tool  -- crawl4ai fetch (quality mode)
    |-- done tool        -- terminates loop
    |
    v
writer.py::write()      -- streams synthesis
    |-- first turn:      get_writer_prompt (fresh answer)
    |-- follow-up:       get_document_revision_prompt (merge into existing doc)
    |
    v
persist.py::save()      -- writes .ai/research/<scope>/<file>.md with frontmatter
```

## Components

### loop.py

`run()` drives an OpenAI tool-calling chat until `done` or max iterations.

Accepts `document: str | None` — when set, the existing research document is
injected into the researcher's first message so it can decide what new searches
to run without re-covering already-known ground.

Returns `ResearcherResult` with `actions[]`, `sources[]` (deduped by URL), `usage{}`.

### writer.py

`write()` generates the synthesis.

| Mode | Trigger | Behavior |
|------|---------|----------|
| First turn | `existing_doc=None` | Standard writer prompt; fresh answer |
| Follow-up | `existing_doc=<body>` | Revision prompt; merges new findings into existing doc |

**Follow-up merge rules (revision prompt):**
1. PRESERVE — copy every heading, paragraph, citation from existing doc verbatim
2. ADD — insert new information from new search context
3. CITE — new facts get [n] from new context; existing [n] markers untouched
4. LENGTH — output must be longer than existing doc

In revision mode, conversation history is NOT passed to the writer (it would
cause the model to treat the request as a chat reply instead of a document merge).
The query is embedded in the system prompt instead.

### persist.py

Handles naming and writing of research documents.

- `pick_location(query, llm_cfg)` — asks LLM for (scope, slug); falls back to
  content-word extraction (strips filler words like "give", "how", "what")
- `resolve_path(scope, slug, base, continuing)` — appends -2, -3, ... on collision;
  returns `continuing` path unchanged if it matches
- `save(path, content)` — mkdir + write_text
- `strip_frontmatter(text)` — parses YAML frontmatter block, returns (meta, body)
- `make_frontmatter(meta)` — serializes dict to YAML block; handles list values

### tui.py

Rich Live TUI with two panels:
- **Top:** action log (plan text untruncated, search queries, fetch status, errors)
- **Bottom:** live-updating Markdown synthesis

After the first turn, drops into a follow-up REPL (`followup_loop`):
- Blank line re-prompts (does not exit)
- Ctrl-D (EOF) exits cleanly
- After each turn: `session.save(doc)` and prints `saved -> <path>`

### _Session (cli.py)

Holds per-conversation state:
- `path` — resolved save path (set on first turn or from --continue)
- `document` — full file content including frontmatter
- `body` — property: document with frontmatter stripped (safe for LLM)
- `queries` — list of all questions asked, appended each turn
- `created` — ISO timestamp of first save
- `turns` — cumulative turn count

`save(content)` strips any frontmatter from LLM output, injects fresh frontmatter
(queries list, created, updated, turns), writes to disk, updates self.document.

## Action registry

| Action | Purpose | Available in |
|--------|---------|-------------|
| `plan` | State reasoning before acting | balanced, quality |
| `search` | Run 1-3 web queries via SearXNG | all modes |
| `scrape_url` | Fetch specific URLs | all modes |
| `done` | Terminate the loop | all modes |

## Search behavior by mode

**Speed:** Direct search, embed-rank snippets (cosine > 0.5), top 20.

**Balanced:** Same + plan action.

**Quality:** Search -> LLM picker (best 2-3 results) -> crawl4ai scrape ->
chunk (4000 chars, 500 overlap) -> LLM extractor (facts per chunk).

## Event bus

`EventBus` (events.py) is an asyncio.Queue pub/sub:
- `emit(Event)` — safe from any task
- `iterate()` — async generator, yields until `close()`

Types: `init`, `plan`, `search`, `search_query`, `search_results`, `reading`,
`fetch_url`, `extracted`, `iter_progress`, `response`, `sources`, `done`, `error`

## Max iterations

| Mode | Max |
|------|-----|
| speed | 2 |
| balanced | 6 |
| quality | 25 |
