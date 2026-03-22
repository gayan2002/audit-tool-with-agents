"""
tools.py
Tool registry — wraps scraper functions so the AI agent can call them by name.
"""

from scraper import scrape_page

_cache: dict = {}


def _get(url: str) -> dict:
    if url not in _cache:
        _cache[url] = scrape_page(url)
    return _cache[url]


def clear_cache():
    _cache.clear()


# ─── Tools ───────────────────────────────────────────────────────────────────

def tool_scrape_page(url: str) -> dict:
    """All base metrics: headings, word count, CTAs, links, images, meta tags."""
    d = _get(url)
    return {k: v for k, v in d.items() if k != "_content_sample"}


def tool_get_content_sample(url: str) -> dict:
    """First 4000 chars of visible page text for messaging analysis."""
    d = _get(url)
    return {"content_sample": d.get("_content_sample", ""), "word_count": d.get("word_count", 0)}


def tool_extract_ctas(url: str) -> dict:
    """CTA counts, texts, and density breakdown (primary vs secondary)."""
    d = _get(url)
    return {
        "cta_primary_count":    d.get("cta_primary_count", 0),
        "cta_primary_texts":    d.get("cta_primary_texts", []),
        "cta_secondary_count":  d.get("cta_secondary_count", 0),
        "cta_secondary_texts":  d.get("cta_secondary_texts", []),
        "cta_raw_total":        d.get("cta_raw_total", 0),
        "cta_density_per_1000": d.get("cta_density_per_1000", 0),
    }


def tool_fetch_links(url: str) -> dict:
    """Internal vs external link counts."""
    d = _get(url)
    return d.get("links", {})


def tool_fetch_images(url: str) -> dict:
    """Image count and alt text audit."""
    d = _get(url)
    return d.get("images", {})


def tool_fetch_videos(url: str) -> dict:
    """
    Full video audit: native <video> tags, YouTube/Vimeo iframes,
    missing captions, missing poster images, missing ARIA labels,
    embeds without title attribute.
    """
    d = _get(url)
    return d.get("videos", {})


def tool_check_seo_tags(url: str) -> dict:
    """Meta title/desc with length flags, canonical, schema, OG, heading issues."""
    d = _get(url)
    return {
        **d.get("meta", {}),
        "headings":       d.get("headings", {}),
        "heading_issues": d.get("heading_issues", []),
        "h1_texts":       d.get("h1_texts", []),
    }


# ─── Registry ────────────────────────────────────────────────────────────────

TOOL_REGISTRY = {
    "scrape_page":        tool_scrape_page,
    "get_content_sample": tool_get_content_sample,
    "extract_ctas":       tool_extract_ctas,
    "fetch_links":        tool_fetch_links,
    "fetch_images":       tool_fetch_images,
    "fetch_videos":       tool_fetch_videos,
    "check_seo_tags":     tool_check_seo_tags,
}

TOOL_SCHEMA = """
AVAILABLE TOOLS — respond with ONE tool call JSON per turn:

  scrape_page(url)        → all base metrics (headings, word count, CTAs, links, images, meta)
  get_content_sample(url) → first 4000 chars of visible page text
  extract_ctas(url)       → primary vs secondary CTA breakdown with texts
  fetch_links(url)        → internal / external link counts
  fetch_images(url)       → image count and alt text coverage
  fetch_videos(url)       → native video, YouTube/Vimeo embeds, captions, poster, ARIA audit
  check_seo_tags(url)     → meta title/desc flags, canonical, schema markup, OG tags

TO CALL A TOOL respond with ONLY this JSON:
{"tool": "tool_name", "reason": "one sentence why you need this"}

WHEN DONE respond with ONLY this JSON:
{"done": true, "audit": { ...full audit JSON... }}
"""
