"""
scraper.py
3-tier page scraper: static → Next.js SSR → Playwright
Returns a nested metrics dict matching the UI's expected structure.
Zero AI knowledge — pure factual extraction.
"""

import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

BLOCKED_DOMAINS = [
    "google-analytics.com", "googletagmanager.com", "hotjar.com",
    "facebook.net", "hubspot.com", "intercom.io", "segment.io",
    "amplitude.com", "clarity.ms", "doubleclick.net", "ads.twitter.com",
]

# ── CTA classification ────────────────────────────────────────────────────────
PRIMARY_CTA_TEXTS = {
    "get started", "book a demo", "contact us", "free trial", "start free",
    "sign up", "signup", "try free", "buy now", "shop now", "download",
    "subscribe", "get a quote", "request demo", "get demo", "see pricing",
    "start today", "get access", "join now", "try now", "schedule a call",
    "start a free trial", "get started free", "request a demo", "book demo",
    "talk to sales", "talk to us", "get in touch", "apply now", "register now",
    "claim your free trial", "start your free trial",
}
SECONDARY_CTA_TEXTS = {
    "learn more", "discover", "explore", "see how", "read more",
    "find out", "watch video", "view more", "see all", "browse",
    "see features", "see how it works", "find out more", "see examples",
    "watch the video", "watch now", "view case study",
}
PRIMARY_CTA_CLASSES = re.compile(
    r"btn-(primary|cta|main|hero)|cta|get-started|sign-up|signup|contact|demo|trial|start|book|buy|shop",
    re.I
)
ANY_CTA_CLASSES = re.compile(
    r"btn|button|cta|action|hero|primary|secondary|get-started|sign-up",
    re.I
)


# ─── Tier 1: Static fetch ────────────────────────────────────────────────────

def fetch_static(url: str):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        return soup if len(soup.get_text(strip=True)) > 200 else None
    except Exception:
        return None


# ─── Tier 2: Next.js SSR ─────────────────────────────────────────────────────

def fetch_nextjs_ssr(url: str):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "lxml")
        if soup.find("script", id="__NEXT_DATA__"):
            return soup
        return None
    except Exception:
        return None


# ─── Tier 3: Playwright ──────────────────────────────────────────────────────

def fetch_playwright(url: str):
    try:
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        async def _fetch():
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(user_agent=HEADERS["User-Agent"])

                await page.route(
                    "**/*",
                    lambda route: route.abort()
                    if any(d in route.request.url for d in BLOCKED_DOMAINS)
                    else route.continue_()
                )
                try:
                    await page.goto(url, wait_until="load", timeout=20000)
                except Exception:
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    except Exception:
                        await browser.close()
                        return None

                await page.wait_for_timeout(2500)
                html = await page.content()
                await browser.close()
                return html

        with ThreadPoolExecutor() as ex:
            html = ex.submit(asyncio.run, _fetch()).result(timeout=35)

        if not html:
            return None
        soup = BeautifulSoup(html, "lxml")
        return soup if len(soup.get_text(strip=True)) > 200 else None
    except Exception:
        return None


# ─── Video extraction ────────────────────────────────────────────────────────

def extract_video_metrics(soup: BeautifulSoup) -> dict:
    """Extract all video-related metrics: native, YouTube, Vimeo, accessibility."""
    # Native <video> tags
    native_tags = soup.find_all("video")
    native_count = len(native_tags)

    native_missing_captions = 0
    native_missing_poster = 0
    native_missing_aria = 0

    for v in native_tags:
        has_caption = bool(
            v.find("track", attrs={"kind": re.compile(r"captions|subtitles", re.I)})
        )
        if not has_caption:
            native_missing_captions += 1

        if not v.get("poster"):
            native_missing_poster += 1

        has_aria = bool(v.get("aria-label") or v.get("aria-labelledby") or v.get("title"))
        if not has_aria:
            native_missing_aria += 1

    # YouTube & Vimeo iframes
    all_iframes = soup.find_all("iframe", src=True)
    youtube_embeds = [
        f for f in all_iframes
        if "youtube.com" in (f.get("src") or "") or "youtu.be" in (f.get("src") or "")
    ]
    vimeo_embeds = [
        f for f in all_iframes
        if "vimeo.com" in (f.get("src") or "")
    ]
    embed_count = len(youtube_embeds) + len(vimeo_embeds)

    embeds_missing_title = sum(
        1 for f in (youtube_embeds + vimeo_embeds)
        if not f.get("title") or f.get("title", "").strip() == ""
    )

    total = native_count + embed_count

    def pct(n, d):
        return round(n / d * 100, 1) if d else 0

    return {
        "total": total,
        "native": native_count,
        "youtube_embeds": len(youtube_embeds),
        "vimeo_embeds": len(vimeo_embeds),
        "native_missing_captions": native_missing_captions,
        "native_missing_captions_pct": pct(native_missing_captions, native_count),
        "native_missing_poster": native_missing_poster,
        "native_missing_poster_pct": pct(native_missing_poster, native_count),
        "native_missing_aria": native_missing_aria,
        "embeds_missing_title": embeds_missing_title,
        "embeds_missing_title_pct": pct(embeds_missing_title, embed_count),
    }


# ─── CTA extraction ──────────────────────────────────────────────────────────

def extract_cta_metrics(soup: BeautifulSoup) -> dict:
    """Classify CTAs into primary (high-intent) and secondary (discovery)."""
    primary_texts, secondary_texts, raw_all = [], [], []

    for el in soup.find_all(["a", "button"]):
        text = el.get_text(strip=True)
        if not text or len(text) > 80:
            continue
        el_class = " ".join(el.get("class", []))
        text_lower = text.lower()
        raw_all.append(text)

        if text_lower in PRIMARY_CTA_TEXTS or PRIMARY_CTA_CLASSES.search(el_class):
            primary_texts.append(text)
        elif text_lower in SECONDARY_CTA_TEXTS or ANY_CTA_CLASSES.search(el_class):
            secondary_texts.append(text)

    # Deduplicate preserving order
    def dedup(lst):
        seen, out = set(), []
        for x in lst:
            key = x.lower()
            if key not in seen:
                seen.add(key)
                out.append(x)
        return out

    primary = dedup(primary_texts)
    secondary = dedup(secondary_texts)

    return {
        "cta_primary_count": len(primary),
        "cta_primary_texts": primary[:6],
        "cta_secondary_count": len(secondary),
        "cta_secondary_texts": secondary[:6],
        "cta_raw_total": len(raw_all),
    }


# ─── Full metric extraction ──────────────────────────────────────────────────

def extract_metrics(soup: BeautifulSoup, url: str, render_method: str) -> dict:
    base = urlparse(url).netloc

    # ── Meta tags — BEFORE stripping ────────────────────────────────────────
    title_tag = soup.find("title")
    meta_title = title_tag.get_text(strip=True) if title_tag else ""

    desc_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    meta_desc = desc_tag.get("content", "") if desc_tag else ""

    canonical = soup.find("link", rel="canonical")
    canonical_url = canonical.get("href") if canonical else None

    has_schema = bool(soup.find_all("script", attrs={"type": "application/ld+json"}))

    og_title_tag = soup.find("meta", property="og:title")
    og_title = og_title_tag.get("content", "") if og_title_tag else ""

    viewport = bool(soup.find("meta", attrs={"name": "viewport"}))
    robots = soup.find("meta", attrs={"name": "robots"})
    is_noindex = "noindex" in (robots.get("content", "") if robots else "").lower()

    # ── Headings — BEFORE stripping ──────────────────────────────────────────
    h1_tags = soup.find_all("h1")
    h2_tags = soup.find_all("h2")
    h3_tags = soup.find_all("h3")
    h1_texts = [h.get_text(strip=True) for h in h1_tags]

    heading_issues = []
    if len(h1_tags) == 0:
        heading_issues.append("missing_h1")
    if len(h1_tags) > 1:
        heading_issues.append("duplicate_h1")
    if len(h3_tags) > 0 and len(h2_tags) == 0:
        heading_issues.append("h3_before_h2")

    # ── Images — BEFORE stripping ────────────────────────────────────────────
    imgs = soup.find_all("img")
    img_total = len(imgs)
    img_missing_alt = sum(
        1 for i in imgs if not (i.get("alt") or "").strip()
    )

    # ── Links — BEFORE stripping ─────────────────────────────────────────────
    int_links, ext_links = [], []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(url, href)
        p = urlparse(full)
        if p.netloc == base or not p.netloc:
            int_links.append(full)
        else:
            ext_links.append(full)

    # ── CTAs — BEFORE stripping ──────────────────────────────────────────────
    ctas = extract_cta_metrics(soup)

    # ── Video — BEFORE stripping ─────────────────────────────────────────────
    videos = extract_video_metrics(soup)

    # ── Strip chrome, then word count ────────────────────────────────────────
    for tag in soup.find_all(["nav", "footer", "header", "aside",
                               "script", "style", "noscript", "head"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)
    word_count = len(text.split())
    content_sample = text[:4000]

    # ── Computed flags ───────────────────────────────────────────────────────
    title_len = len(meta_title)
    title_flag = "too_short" if title_len < 50 else "truncated" if title_len > 60 else "optimal"
    desc_len = len(meta_desc)
    desc_flag = "too_short" if desc_len < 120 else "truncated" if desc_len > 155 else "optimal"
    cta_density = round(ctas["cta_primary_count"] / max(word_count, 1) * 1000, 2)
    alt_pct = round(img_missing_alt / img_total * 100, 1) if img_total else 0

    return {
        # Top-level
        "url": url,
        "render_method": render_method,
        "word_count": word_count,
        "heading_issues": heading_issues,
        "h1_texts": h1_texts,
        # Nested groups matching UI expectations
        "headings": {
            "h1": len(h1_tags),
            "h2": len(h2_tags),
            "h3": len(h3_tags),
        },
        "meta": {
            "title": meta_title,
            "title_length": title_len,
            "title_flag": title_flag,
            "description": meta_desc,
            "description_length": desc_len,
            "description_flag": desc_flag,
            "canonical_url": canonical_url,
            "has_schema_markup": has_schema,
            "og_title": og_title,
            "is_noindex": is_noindex,
            "viewport_meta": viewport,
        },
        "links": {
            "internal": len(int_links),
            "external": len(ext_links),
            "total": len(int_links) + len(ext_links),
        },
        "images": {
            "total": img_total,
            "missing_alt": img_missing_alt,
            "missing_alt_pct": alt_pct,
        },
        "videos": videos,
        # CTA fields at top level (UI destructures them directly)
        "cta_primary_count": ctas["cta_primary_count"],
        "cta_primary_texts": ctas["cta_primary_texts"],
        "cta_secondary_count": ctas["cta_secondary_count"],
        "cta_secondary_texts": ctas["cta_secondary_texts"],
        "cta_raw_total": ctas["cta_raw_total"],
        "cta_density_per_1000": cta_density,
        # Content sample for AI (stripped by server before sending to UI)
        "_content_sample": content_sample,
    }


# ─── Public entry point ──────────────────────────────────────────────────────

def scrape_page(url: str) -> dict:
    soup = fetch_static(url)
    if soup:
        return extract_metrics(soup, url, "static")

    soup = fetch_nextjs_ssr(url)
    if soup:
        return extract_metrics(soup, url, "next.js-ssr")

    soup = fetch_playwright(url)
    if soup:
        return extract_metrics(soup, url, "playwright")

    return {"error": "Could not extract content from this URL", "url": url}
