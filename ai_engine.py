"""
ai_engine.py — Agentic audit engine
Plan → Act → Reflect loop with self-critique.
"""

import json, re, os, time, requests
from datetime import datetime
from tools import TOOL_REGISTRY, TOOL_SCHEMA, clear_cache

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
MODEL = os.getenv("OPENROUTER_MODEL", "mistralai/mistral-small-3.1-24b-instruct:free")
MAX_STEPS = 10


SYSTEM_PROMPT = f"""You are a senior web strategist at a digital marketing agency.
Audit the given webpage and produce a structured, grounded analysis.

WORKFLOW:
1. Call scrape_page first to get base metrics.
2. Call fetch_videos — modern marketing pages rely heavily on video; always audit it.
3. Call get_content_sample to read the page text.
4. Call additional tools if data warrants (low CTAs → extract_ctas; SEO concerns → check_seo_tags).
5. Produce the final audit JSON when you have enough data.

{TOOL_SCHEMA}

AUDIT OUTPUT SCHEMA (use exactly when responding with done:true):
{{
  "seo_structure": {{
    "score": int (0-100),
    "finding": str (cite exact numbers),
    "metric_cited": str
  }},
  "messaging_clarity": {{
    "score": int,
    "finding": str,
    "metric_cited": str
  }},
  "cta_usage": {{
    "score": int,
    "finding": str,
    "metric_cited": str
  }},
  "content_depth": {{
    "score": int,
    "finding": str,
    "metric_cited": str
  }},
  "ux_concerns": {{
    "score": int,
    "finding": str,
    "metric_cited": str
  }},
  "video_analysis": {{
    "score": int,
    "finding": str,
    "metric_cited": str
  }},
  "recommendations": [
    {{
      "priority": 1,
      "action": str,
      "reasoning": str,
      "metric_cited": str
    }}
  ]
}}

SCORING: 80-100 strong · 50-79 needs work · 0-49 critical issue
RULES:
- Every finding must cite a real number from tool results.
- Scores are integers 0-100. Never use words like "good" or "poor".
- video_analysis score should be 50 if no videos found (neutral — not penalised).
- Return ONLY raw JSON. No markdown fences, no preamble.
"""


# ── LLM call with retry on empty / rate-limited response ─────────────────────

def call_llm(messages: list) -> str:
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY not set in .env")

    for attempt in range(3):
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://audit-tool.local",
                },
                json={
                    "model": MODEL,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 2500,
                },
                timeout=60,
            )

            # Rate limit — wait and retry
            if r.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f"Rate limited. Waiting {wait}s (retry {attempt+1}/3)...")
                time.sleep(wait)
                continue

            r.raise_for_status()

            content = r.json().get("choices", [{}])[0].get("message", {}).get("content")

            # Empty content — wait and retry
            if not content or not isinstance(content, str) or not content.strip():
                if attempt < 2:
                    print(f"Empty response. Retry {attempt+1}/3 in 5s...")
                    time.sleep(5)
                    continue
                raise ValueError("Model returned empty response after 3 attempts — try switching model")

            return content

        except requests.HTTPError as e:
            code = e.response.status_code if e.response else 0
            if attempt < 2 and code in (429, 500, 502, 503):
                wait = 10 * (attempt + 1)
                print(f"HTTP {code}. Waiting {wait}s (retry {attempt+1}/3)...")
                time.sleep(wait)
                continue
            raise

    raise ValueError("Failed to get a valid response after 3 attempts")


# ── Parse AI response ─────────────────────────────────────────────────────────

def parse_response(text: str) -> dict:
    if not text or not isinstance(text, str):
        raise ValueError("Cannot parse empty or non-string response")

    clean = re.sub(r"```json|```", "", text).strip()

    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass

    m = re.search(r'\{.*\}', clean, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Cannot parse JSON from response: {text[:300]}")


# ── Self-critique pass ────────────────────────────────────────────────────────

def self_critique(messages: list, draft: dict) -> dict:
    msg = (
        "Review your audit. For each section add a 'confidence' integer 0-100. "
        "If a finding is not traceable to a tool result number, set confidence to 0. "
        "Return the same JSON with confidence fields added. ONLY JSON.\n\n"
        + json.dumps(draft, indent=2)
    )
    messages.append({"role": "user", "content": msg})

    try:
        raw = call_llm(messages)
        messages.append({"role": "assistant", "content": raw})
        reviewed = parse_response(raw)
    except Exception:
        draft["_critique_warning"] = "Self-critique failed — review manually"
        return draft

    low = [
        k for k, v in reviewed.items()
        if isinstance(v, dict) and v.get("confidence", 100) < 70
    ]
    if low:
        reviewed["_low_confidence_sections"] = low

    return reviewed


# ── Main agent entry point ────────────────────────────────────────────────────

def run_agent_audit(url: str) -> dict:
    clear_cache()

    log = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "url":    url,
        "model":  MODEL,
        "system_prompt": SYSTEM_PROMPT,
        "steps":  [],
    }

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Audit this webpage: {url}\n\n"
                "Start with scrape_page, then fetch_videos, then get_content_sample. "
                "Call more tools if needed, then produce the final audit."
            ),
        },
    ]

    base_metrics = {}
    final_audit  = None

    # ── Agent loop ────────────────────────────────────────────────────────────
    for step in range(MAX_STEPS):

        # Retry getting a valid non-empty response up to 3 times per step
        raw = None
        for attempt in range(3):
            try:
                raw = call_llm(messages)
                if raw:
                    break
            except ValueError as e:
                if attempt == 2:
                    raise
                print(f"Step {step+1} attempt {attempt+1} failed: {e}. Retrying in 5s...")
                time.sleep(5)

        messages.append({"role": "assistant", "content": raw})

        try:
            parsed = parse_response(raw)
        except ValueError as e:
            messages.append({
                "role": "user",
                "content": 'Respond with {"tool":"name","reason":"..."} or {"done":true,"audit":{...}}'
            })
            log["steps"].append({"step": step + 1, "error": str(e)})
            continue

        # ── Tool call ─────────────────────────────────────────────────────────
        if "tool" in parsed:
            name   = parsed.get("tool", "")
            reason = parsed.get("reason", "")

            if name not in TOOL_REGISTRY:
                result = {"error": f"Unknown tool '{name}'. Available: {list(TOOL_REGISTRY.keys())}"}
            else:
                result = TOOL_REGISTRY[name](url)

            if name == "scrape_page" and "error" not in result:
                base_metrics = result

            log["steps"].append({
                "step":        step + 1,
                "tool_called": name,
                "reason":      reason,
                "tool_result": result,
            })

            messages.append({
                "role": "user",
                "content": (
                    f"Tool result for {name}:\n"
                    f"{json.dumps(result, indent=2)}\n\n"
                    "Continue. Call another tool or produce the final audit."
                ),
            })

        # ── Final answer ──────────────────────────────────────────────────────
        elif parsed.get("done"):
            final_audit = parsed.get("audit", parsed)
            break

        # ── Unexpected format — nudge the model ───────────────────────────────
        else:
            messages.append({
                "role": "user",
                "content": 'Respond with {"tool":"...","reason":"..."} or {"done":true,"audit":{...}}',
            })

    # ── Self-critique ─────────────────────────────────────────────────────────
    if final_audit:
        final_audit = self_critique(messages, final_audit)
    else:
        final_audit = {"error": "Agent did not produce a final audit within step limit"}

    # ── Save prompt log ───────────────────────────────────────────────────────
    log["raw_final_output"] = final_audit
    log["total_steps"]      = len(log["steps"])
    log["full_messages"]    = messages

    os.makedirs("prompt_logs", exist_ok=True)
    ts       = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log_path = f"prompt_logs/audit_{ts}.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

    return {
        "metrics":         base_metrics,
        "insights":        final_audit,
        "render_method":   base_metrics.get("render_method", "unknown"),
        "steps_taken":     log["total_steps"],
        "agent_steps":     log["steps"],
        "prompt_log_file": log_path,
    }
