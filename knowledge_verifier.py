"""
knowledge_verifier.py — Multi-source truth verification engine for Atherix Red.
Standalone: no imports from other Atherix files (to avoid circular deps with intelligence.py).
"""

import re
import json
import hashlib
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

try:
    from duckduckgo_search import DDGS
    DDG_AVAILABLE = True
except ImportError:
    DDG_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

# ---------------------------------------------------------------------------
# Source tier definitions
# ---------------------------------------------------------------------------

TIER_1 = [
    "nvd.nist.gov", "cvedetails.com", "cve.mitre.org",
    "docs.python.org", "developer.mozilla.org", "learn.microsoft.com",
    "man7.org", "linux.die.net",
    "portswigger.net/web-security", "owasp.org", "attack.mitre.org",
    "sans.org", "cisa.gov", "github.com/advisories", "exploit-db.com",
]

TIER_2 = [
    "hacktricks.xyz", "book.hacktricks.xyz", "gtfobins.github.io",
    "lolbas-project.github.io", "stackoverflow.com", "github.com",
    "pentestmonkey.net", "swisskyrepo.github.io", "infosecwriteups.com",
    "0xdf.gitlab.io", "0xdf.com",
]

TIER_3 = [
    "medium.com", "dev.to", "hashnode.dev", "reddit.com", "youtube.com",
]

# Cache file — extends knowledge_base.py cache format
KB_DIR = os.path.join("C:\\atherix-red", "knowledge_base")
CACHE_FILE = os.path.join(KB_DIR, "cache.json")

# ---------------------------------------------------------------------------
# Source tier classification
# ---------------------------------------------------------------------------

def classify_source_tier(url: str) -> int:
    """Return tier 1-4 for a URL. 4 = unknown/untrusted."""
    try:
        host = urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return 4

    for domain in TIER_1:
        if host == domain or host.endswith("." + domain) or domain in host:
            return 1

    for domain in TIER_2:
        if host == domain or host.endswith("." + domain) or domain in host:
            return 2

    for domain in TIER_3:
        if host == domain or host.endswith("." + domain) or domain in host:
            return 3

    return 4


# ---------------------------------------------------------------------------
# Fetch a single source
# ---------------------------------------------------------------------------

def fetch_source(url: str, max_chars: int = 8000) -> dict:
    """Fetch a URL and return structured result."""
    tier = classify_source_tier(url)
    result = {
        "url": url,
        "tier": tier,
        "content": "",
        "title": "",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "success": False,
        "error": None,
    }

    if not REQUESTS_AVAILABLE:
        result["error"] = "requests library not available"
        return result

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        resp.raise_for_status()

        raw = resp.text

        if BS4_AVAILABLE:
            soup = BeautifulSoup(raw, "html.parser")
            # Remove script/style noise
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            title_tag = soup.find("title")
            result["title"] = title_tag.get_text(strip=True) if title_tag else ""
            text = soup.get_text(separator="\n", strip=True)
        else:
            # Naive strip
            text = re.sub(r"<[^>]+>", " ", raw)
            text = re.sub(r"\s+", " ", text).strip()
            result["title"] = url

        result["content"] = text[:max_chars]
        result["success"] = True

    except Exception as exc:
        result["error"] = str(exc)

    return result


# ---------------------------------------------------------------------------
# Extract content most relevant to a topic
# ---------------------------------------------------------------------------

def extract_relevant_content(raw_content: str, topic: str, max_chars: int = 3000) -> str:
    """Return the most topic-relevant excerpt from raw_content."""
    if not raw_content:
        return ""

    keywords = set(re.findall(r"\b\w{3,}\b", topic.lower()))
    if not keywords:
        return raw_content[:max_chars]

    lines = raw_content.split("\n")
    scored: list[tuple[float, int]] = []

    for i, line in enumerate(lines):
        line_lower = line.lower()
        hits = sum(1 for kw in keywords if kw in line_lower)
        if hits:
            scored.append((hits, i))

    if not scored:
        return raw_content[:max_chars]

    scored.sort(key=lambda x: -x[0])

    # Collect top-scoring lines with context
    included: set[int] = set()
    for _, idx in scored[:15]:
        for offset in range(-2, 3):
            ni = idx + offset
            if 0 <= ni < len(lines):
                included.add(ni)

    selected = [lines[i] for i in sorted(included) if lines[i].strip()]
    result = "\n".join(selected)
    return result[:max_chars]


# ---------------------------------------------------------------------------
# Search DuckDuckGo for topic sources
# ---------------------------------------------------------------------------

def search_for_topic(topic: str, num_sources: int = 5) -> list[dict]:
    """Search DuckDuckGo, classify tiers, return list of source dicts (skip T4)."""
    sources: list[dict] = []

    if not DDG_AVAILABLE:
        return sources

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(topic, max_results=num_sources * 2))
    except Exception:
        return sources

    seen_urls: set[str] = set()
    for r in results:
        url = r.get("href") or r.get("url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        tier = classify_source_tier(url)
        if tier == 4:
            continue  # Never fetch/store T4

        sources.append({
            "url": url,
            "tier": tier,
            "snippet": r.get("body", "")[:500],
            "title": r.get("title", ""),
        })

        if len(sources) >= num_sources:
            break

    return sources


# ---------------------------------------------------------------------------
# Cross-validate sources for a topic
# ---------------------------------------------------------------------------

def cross_validate(sources: list[dict], topic: str) -> dict:
    """
    Given fetched sources, determine verdict and confidence.

    Verdict rules:
    - T1 alone → VERIFIED, confidence 90+
    - T2 + 1 corroborating (T1 or T2) → VERIFIED, confidence 75+
    - T3 + 2 corroborating (T1 or T2) → VERIFIED, confidence 60+
    - T3 alone or T4 → UNVERIFIED
    - Conflicting claims → DISPUTED
    """
    tier_breakdown = {"t1": 0, "t2": 0, "t3": 0}
    supporting: list[str] = []
    conflicting: list[str] = []
    summaries: list[str] = []

    contradiction_keywords = [
        r"\bdoes not\b", r"\bcannot\b", r"\bis not\b", r"\bno longer\b",
        r"\bincorrect\b", r"\binvalid\b", r"\bdeprecated\b",
    ]

    # Track which sources contain contradictory signals independently
    positive_urls: list[str] = []
    negative_urls: list[str] = []

    for src in sources:
        if not src.get("success") or not src.get("content"):
            continue
        tier = src.get("tier", 4)
        text = src.get("content", "")[:2000].lower()
        url = src.get("url", "")

        # Score this source's signal
        neg_hits = sum(1 for pat in contradiction_keywords if re.search(pat, text))
        pos_hits = 5 - neg_hits  # Rough inverse

        if tier == 1:
            tier_breakdown["t1"] += 1
            if neg_hits >= 2:
                negative_urls.append(url)
            else:
                positive_urls.append(url)
                supporting.append(url)
        elif tier == 2:
            tier_breakdown["t2"] += 1
            if neg_hits >= 2:
                negative_urls.append(url)
            else:
                positive_urls.append(url)
                supporting.append(url)
        elif tier == 3:
            tier_breakdown["t3"] += 1
            # T3 only adds to supporting if backed by T1/T2

        excerpt = extract_relevant_content(src.get("content", ""), topic, max_chars=800)
        if excerpt:
            summaries.append(f"[{url}]\n{excerpt}")

    # Real conflict: both positive and negative signals from credible sources
    is_disputed = bool(positive_urls) and bool(negative_urls) and (len(negative_urls) >= 1)

    conflicting = negative_urls
    t1 = tier_breakdown["t1"]
    t2 = tier_breakdown["t2"]
    t3 = tier_breakdown["t3"]
    high_quality = t1 + t2

    if is_disputed:
        verdict = "DISPUTED"
        confidence = max(50, min(70, 50 + high_quality * 5))
    elif t1 >= 1:
        verdict = "VERIFIED"
        confidence = min(98, 90 + t1 * 2 + t2)
    elif t2 >= 1 and high_quality >= 2:
        verdict = "VERIFIED"
        confidence = min(88, 75 + high_quality * 2)
    elif t3 >= 1 and high_quality >= 2:
        verdict = "VERIFIED"
        confidence = min(72, 60 + high_quality * 3)
    else:
        verdict = "UNVERIFIED"
        confidence = 30

    summary = "\n\n---\n\n".join(summaries[:3])  # Top 3 source excerpts
    if not summary:
        summary = f"No verifiable content found for: {topic}"

    return {
        "verdict": verdict,
        "confidence": confidence,
        "summary": summary,
        "supporting_sources": supporting,
        "conflicting_sources": conflicting,
        "tier_breakdown": tier_breakdown,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Cache helpers (mirror knowledge_base.py cache format)
# ---------------------------------------------------------------------------

def _load_cache() -> dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    os.makedirs(KB_DIR, exist_ok=True)
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def _query_hash(topic: str) -> str:
    return hashlib.sha256(topic.lower().strip().encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def verify_and_store(topic: str, context: str = "") -> dict:
    """
    Main entry: search → fetch → cross-validate → cache if VERIFIED/DISPUTED.
    Returns the cross_validate result dict.
    """
    qhash = _query_hash(topic)

    # Check cache first
    cache = _load_cache()
    if qhash in cache:
        entry = cache[qhash]
        verification = entry.get("verification", {})
        if verification.get("verdict") in ("VERIFIED", "DISPUTED"):
            return verification

    # Search for sources
    search_query = topic if not context else f"{topic} {context[:100]}"
    raw_sources = search_for_topic(search_query, num_sources=6)

    # Fetch each source
    fetched: list[dict] = []
    for src in raw_sources:
        time.sleep(0.3)  # Polite crawl delay
        fetched_src = fetch_source(src["url"])
        fetched_src["tier"] = src["tier"]  # Use tier from classification (already done)
        fetched.append(fetched_src)

    # Cross-validate
    result = cross_validate(fetched, topic)

    # Cache if worthy
    if result["verdict"] in ("VERIFIED", "DISPUTED"):
        cache[qhash] = {
            "content": result["summary"][:4000],
            "source": "verified_knowledge",
            "topic": topic,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "ttl_days": 5,
            "verification": {
                "verdict": result["verdict"],
                "confidence": result["confidence"],
                "tier_breakdown": result["tier_breakdown"],
                "sources": result["supporting_sources"],
                "verified_at": result["verified_at"],
            },
        }
        _save_cache(cache)

    return result


def verify_existing_knowledge(knowledge_text: str, topic: str) -> dict:
    """
    Verify a piece of knowledge text against live sources.
    Returns the cross_validate result, treating the existing text as context.
    """
    return verify_and_store(topic, context=knowledge_text[:300])