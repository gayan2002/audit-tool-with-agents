# Page Audit Tool - v3 Agentic

An AI-powered single-page website auditor with a Plan - Act - Reflect agent loop.
Works on all tech stacks. Drop in a URL and get factual metrics plus grounded AI insights.

Built for EIGHT25MEDIA's AI-Native Software Engineer assignment.

---

## Live Demo

| Link | Description |
|------|-------------|
| **App** | https://audit-tool-with-agents-production.up.railway.app |
| **Prompt Logs** | https://audit-tool-with-agents-production.up.railway.app/logs |
| **GitHub** | https://github.com/gayan2002/audit-tool-with-agents |

> The `/logs` endpoint returns the last 5 prompt logs as JSON - showing the full system prompt, every tool call and result, structured metrics payload, and raw model output before parsing.

---

## Quick Start

```bash
git clone https://github.com/gayan2002/audit-tool-with-agents.git
cd audit-tool-with-agents

pip install -r requirements.txt
python -m playwright install chromium

cp .env.example .env
# Edit .env and add your key:
# OPENROUTER_API_KEY=your-key-here
# OPENROUTER_MODEL=mistralai/mistral-small-3.1-24b-instruct:free

python main.py
# Open http://localhost:8000
```

---

## Architecture Overview

Four clearly separated layers - each with one job, no cross-contamination.

```
User (browser)
     |  POST /audit { url }
     v
+----------------------------------------------------------+
|  main.py - FastAPI                                        |
|  Validates input, calls agent, strips internal fields,    |
|  returns { metrics, insights, agent_steps, render_method }|
+----------------------+-----------------------------------+
                       |
                       v
+----------------------------------------------------------+
|  ai_engine.py - Agent Orchestrator                        |
|                                                           |
|  1. PLAN    - seeds messages array, instructs tool order  |
|  2. ACT     - calls tools one at a time via tool registry |
|  3. REFLECT - appends observations, decides next tool     |
|  4. CRITIQUE - self-scores each insight 0-100, flags low  |
|                                                           |
|  Saves full reasoning trace to prompt_logs/               |
+------------------+----------------------------------------+
                   |  tool calls by name
                   v
+----------------------------------------------------------+
|  tools.py - Tool Registry                                 |
|                                                           |
|  Maps tool names to scraper functions for the agent.      |
|  The agent sees the tool schema; Python runs the code.    |
|                                                           |
|  scrape_page / fetch_videos / get_content_sample          |
|  extract_ctas / fetch_links / fetch_images / check_seo_tags|
+------------------+----------------------------------------+
                   |
                   v
+----------------------------------------------------------+
|  scraper.py - 3-Tier Metric Extractor                     |
|                                                           |
|  Tier 1: requests + BeautifulSoup  (static HTML)          |
|  Tier 2: __NEXT_DATA__ detection   (Next.js / Gatsby SSR) |
|  Tier 3: Playwright headless       (React / Vue / Angular)|
|                                                           |
|  Returns plain dict of factual metrics. Zero AI knowledge.|
+----------------------------------------------------------+
```

---

## How the Agent Loop Works

The agent is not a single prompt-response pair. It runs a conversation loop where
the model decides what to do next at each step.

```
messages = [system_prompt, user: "audit https://..."]

loop:
  response = call_llm(messages)          # full history sent every call

  if response is tool call:
    result = TOOL_REGISTRY[name](url)    # Python runs the function
    messages.append(tool_result)         # observation injected into history
    continue

  if response is done:
    final_audit = response.audit
    break

self_critique(final_audit)               # AI scores its own output
save_prompt_log()
```

The model sees its full observation history on every call - this is what gives
it memory across steps without any external database.

---

## 3-Tier Scraping Strategy

| Tier | Method | Works For | Speed |
|------|--------|-----------|-------|
| 1 | requests + BeautifulSoup | WordPress, PHP, Django, plain HTML | ~0.5s |
| 2 | `__NEXT_DATA__` JSON detection | Next.js, Gatsby, React SSR | ~0.5s |
| 3 | Playwright headless Chromium | React SPA, Vue, Angular, Svelte | ~5-8s |

Playwright uses `wait_until='load'` (never `networkidle`) and blocks 15+ analytics
domains to prevent timeout hangs on heavy e-commerce sites. Falls back to
`domcontentloaded` if `load` also times out.

---

## Metrics Extracted

**SEO**
- Meta title + character length + flag (optimal / too_short / truncated)
- Meta description + character length + flag
- Canonical tag presence and URL
- Schema.org markup detected (`application/ld+json`)
- Open Graph title and description
- Robots meta / noindex flag
- Viewport meta tag presence
- H1 actual text content

**Content**
- Word count (nav, header, footer, aside excluded - main content only)
- H1 / H2 / H3 counts
- Heading hierarchy issues (missing_h1, duplicate_h1, h3_before_h2)

**Conversion**
- Primary CTAs (high-intent: "Get Started", "Book a Demo", "Free Trial"...)
- Secondary CTAs (discovery: "Learn More", "Explore", "Watch Video"...)
- Raw CTA total including repeated instances
- CTA density per 1000 words
- Internal vs external link counts

**Accessibility / Images**
- Total images + % missing alt text

**Video**
- Native `<video>` tags
- YouTube + Vimeo iframe embeds
- Missing captions (`<track kind="captions">` absent)
- Missing poster image attribute
- Missing ARIA labels on native video
- Embeds missing `title` attribute (WCAG requirement)

---

## AI Design Decisions

### Agentic Architecture vs Single-Shot

The previous version sent all metrics in one prompt and received one response.
This version uses an agent loop so the model can:

- Request more data before forming opinions (e.g. call `extract_ctas` when CTA count looks unusual)
- Build up an observation history before scoring
- Verify its own output in a separate self-critique pass

The prompt log now shows a full reasoning trace - not a single prompt/response pair.

### Hallucination Reduction Techniques

**1. Metrics injected as structured JSON ground truth**
Metrics are sent as a grouped JSON object (`seo`, `content`, `conversion`, `accessibility`, `video`)
rather than a plain text block. The system prompt labels this block as ground truth.
The model reasons from data, not from prior knowledge about the site.

**2. Tool-calling forces data collection before reasoning**
The agent cannot write insights until it has called at least `scrape_page`, `fetch_videos`,
and `get_content_sample`. It cannot skip straight to conclusions.

**3. `metric_cited` field on every insight**
The output schema requires the model to name the exact `key: value` from tool results
that supports each claim. This makes hallucinations instantly visible in prompt logs -
any cited value that does not match a tool result is a fabrication.

**4. Self-critique pass with confidence scores**
After producing the draft audit, a second prompt asks the model to assign a confidence
score (0-100) to each section. Sections scoring below 70 are flagged in
`_low_confidence_sections` in the prompt log and displayed as warnings in the UI.

**5. Industry benchmarks injected into system prompt**
Rather than letting the model invent thresholds, the prompt provides them explicitly:

| Benchmark | Source |
|-----------|--------|
| Meta title 50-60 chars | Google Search Central |
| Meta description 120-155 chars | Google Search Central / John Mueller |
| H1 = exactly 1 | Google Search Central best practice |
| Schema.org markup | schema.org (Google / Microsoft / Yahoo / Yandex) |
| Word count 300 / 600 thresholds | Backlinko, HubSpot aggregate studies |
| CTA density 1-5 per 1000 words | NNGroup, CXL Institute |
| Alt text < 10% missing | WCAG, Google Lighthouse |

**6. `temperature: 0.2`**
Low temperature keeps the model close to its most probable output, reducing
creative but incorrect responses across repeated runs.

**7. Retry loop on empty / null responses**
Free models occasionally return a null `content` field under load. The `call_llm`
function retries up to 3 times with exponential backoff before raising an error,
so a single bad response does not crash the audit.

**8. Explicit unknown boundary in system prompt**
The system prompt lists what the model does NOT have access to: page speed, mobile
responsiveness, analytics data, search rankings. Without this, models fill knowledge
gaps with plausible-sounding inventions.

---

## Prompt Log Format

Every audit writes a timestamped JSON to `prompt_logs/`. Each log contains:

```json
{
  "timestamp": "2026-03-22T15:37:24Z",
  "url": "https://example.com",
  "model": "mistralai/mistral-small-3.1-24b-instruct:free",
  "system_prompt": "...",
  "steps": [
    {
      "step": 1,
      "tool_called": "scrape_page",
      "reason": "Get base metrics before analysis",
      "tool_result": { "word_count": 263, "h1_count": 1 }
    },
    {
      "step": 2,
      "tool_called": "fetch_videos",
      "reason": "Audit video accessibility coverage",
      "tool_result": { "total": 9, "native_missing_captions_pct": 100.0 }
    }
  ],
  "raw_final_output": { "seo_structure": { "score": 55 } },
  "total_steps": 4,
  "full_messages": []
}
```

Prompt logs are gitignored by default. Copy to `prompt_logs/examples/` to include
sample logs in the repository.

---

## Trade-offs

**Scores are model-generated, not formula-based.**
The AI assigns integer scores based on the benchmarks provided in the prompt.
Two runs on the same page may return slightly different scores. The production-grade
fix is Python rubrics that calculate scores deterministically - the AI would then
only write finding and recommendation text. This is the highest-priority improvement
for a v4.

**CTA detection is heuristic.**
The scraper detects CTAs using class-name patterns and known action text. It will
miss CTAs using non-semantic markup or generic class names like `class="link"`.

**Word count accuracy.**
Excludes nav / header / footer / aside but may still include sidebars or cookie
banners depending on site structure.

**Bot-protected sites.**
Sites that detect headless browsers return empty pages even with Playwright. Full
coverage requires residential proxy rotation, which is out of scope.

**JS-heavy sites may scrape as Static.**
If a site responds with enough server-side HTML to pass the 200-character content
check, the scraper stops at Tier 1 even if most content is client-rendered. Word
counts and link counts on heavy SPA sites may be lower than the visible page shows.

**Free OpenRouter models.**
Model IDs change frequently and rate limits are low. Production use should pin a
specific paid model via `OPENROUTER_MODEL` in `.env`.

---

## What I Would Improve With More Time

1. **Deterministic scoring rubrics in Python** - move score calculation out of the AI
   and into hardcoded Python functions for each metric. AI only writes finding and
   recommendation text. Eliminates score variance between runs entirely.

2. **Core Web Vitals via Google PageSpeed Insights API** - adds LCP, CLS, FID to the
   factual metrics layer without any AI estimation.

3. **Competitor comparison mode** - run the PAR loop on two URLs in parallel, then
   a third synthesis call diffs the metrics and scores section by section.

4. **Redis caching by URL + content hash** - repeat audits are instant and do not
   burn API credits.

5. **Playwright with residential proxies** - handles bot-protected e-commerce sites
   properly.

6. **Scoring rubric as YAML config** - lets non-engineers tune what "good" means
   for different site types (e-commerce vs SaaS vs local service).

7. **Confidence threshold retry** - if self-critique flags a section below 70,
   automatically re-run only that section with a targeted tool call rather than
   just flagging it as a warning.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + Uvicorn |
| Scraping - static | requests + BeautifulSoup4 + lxml |
| Scraping - JS | Playwright (Chromium) |
| Agent loop | Custom PAR loop in ai_engine.py |
| Tool registry | Plain Python dict in tools.py |
| AI | OpenRouter API (model configurable via `.env`) |
| Frontend | Vanilla HTML / CSS / JS - no build step |
| Config | python-dotenv |

---

## File Reference

| File | Purpose |
|------|---------|
| `scraper.py` | 3-tier scraper. Extracts all metrics including video. Returns nested dict. Zero AI knowledge. |
| `tools.py` | Tool registry mapping names to scraper functions. The AI sees the schema; Python runs the code. |
| `ai_engine.py` | PAR loop. Manages messages array, dispatches tool calls, runs self-critique, saves prompt log. |
| `main.py` | FastAPI server. GET / serves UI. POST /audit runs the agent. Windows asyncio fix included. |
| `static/index.html` | Single-file dashboard. Metrics, video section, AI insights, recommendations, agent trace. |
| `prompt_logs/` | Auto-created. One timestamped JSON per run with full reasoning trace. Gitignored. |
| `.env.example` | Config template. Copy to `.env` and add your OpenRouter API key. |
