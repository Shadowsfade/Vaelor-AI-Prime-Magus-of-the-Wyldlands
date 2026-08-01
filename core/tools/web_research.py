"""Free web research for Vaelor (no paid APIs).

Sources:
  1) DuckDuckGo Instant Answer JSON API
  2) Wikipedia OpenSearch + summary extracts
  3) Optional URL fetch
"""
from __future__ import annotations
import html as html_lib
import json
import re
import urllib.parse
import requests

HEADERS = {
    "User-Agent": "VaelorArchive/1.0 (local assistant; +https://localhost)",
    "Accept": "application/json,text/html,application/xhtml+xml",
}

def _strip_tags(text: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()

def _ddg_instant(query: str) -> list:
    r = requests.get(
        "https://api.duckduckgo.com/",
        params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
        headers=HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    out = []
    if data.get("AbstractText"):
        out.append((
            data.get("Heading") or query,
            data.get("AbstractURL") or "https://duckduckgo.com/",
            data.get("AbstractText"),
        ))
    for t in data.get("RelatedTopics") or []:
        if isinstance(t, dict) and t.get("Text") and t.get("FirstURL"):
            out.append((t.get("Text", "")[:120], t["FirstURL"], t.get("Text", "")))
        elif isinstance(t, dict) and "Topics" in t:
            for st in t.get("Topics") or []:
                if st.get("Text") and st.get("FirstURL"):
                    out.append((st.get("Text", "")[:120], st["FirstURL"], st.get("Text", "")))
        if len(out) >= 6:
            break
    return out

def _wikipedia(query: str, limit: int = 5) -> list:
    r = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "opensearch",
            "search": query,
            "limit": limit,
            "namespace": 0,
            "format": "json",
        },
        headers=HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    titles = data[1] if len(data) > 1 else []
    descs = data[2] if len(data) > 2 else []
    urls = data[3] if len(data) > 3 else []
    out = []
    for i, title in enumerate(titles):
        url = urls[i] if i < len(urls) else ""
        desc = descs[i] if i < len(descs) else ""
        # pull summary extract
        try:
            sr = requests.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}",
                headers=HEADERS,
                timeout=10,
            )
            if sr.ok:
                js = sr.json()
                extract = js.get("extract") or desc
                url = js.get("content_urls", {}).get("desktop", {}).get("page") or url
                out.append((title, url, extract))
            else:
                out.append((title, url, desc))
        except Exception:
            out.append((title, url, desc))
    return out

def web_search(query: str = "", limit: int = 5) -> str:
    query = (query or "").strip()
    if not query:
        return "Refused: no query. Usage: tool: web_search query=your question"
    limit = max(1, min(int(limit or 5), 8))
    results = []
    errors = []
    for fn in (_ddg_instant, lambda q: _wikipedia(q, limit)):
        try:
            got = fn(query)
            for item in got:
                if item not in results:
                    results.append(item)
            if len(results) >= limit:
                break
        except Exception as e:
            errors.append(str(e))
    results = results[:limit]
    if not results:
        err = "; ".join(errors) if errors else "no results"
        return f"No web results found for: {query} ({err})"
    lines = [f"Web research results for: {query}\n"]
    for i, (title, href, snip) in enumerate(results, 1):
        lines.append(f"{i}. {title}\n   {href}")
        if snip:
            lines.append(f"   {snip[:400]}")
    lines.append("\nPrefer archive memory first; use these sources for missing external facts and cite links.")
    return "\n".join(lines)

def fetch_url(url: str = "", max_chars: int = 4000) -> str:
    url = (url or "").strip()
    if not url:
        return "Refused: no url. Usage: tool: fetch_url url=https://..."
    if not (url.startswith("http://") or url.startswith("https://")):
        return "Refused: only http/https URLs allowed."
    max_chars = max(500, min(int(max_chars or 4000), 12000))
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "json" in ctype:
            text = json.dumps(r.json(), indent=2)[:max_chars]
            return f"----- {url} -----\n{text}"
        if not any(x in ctype for x in ("html", "text", "xml")):
            return f"Refused: unsupported content-type {ctype}"
        text = _strip_tags(r.text)
        if len(text) > max_chars:
            text = text[:max_chars] + "…"
        return f"----- {url} -----\n{text}"
    except Exception as e:
        return f"Fetch failed for {url}: {e}"
