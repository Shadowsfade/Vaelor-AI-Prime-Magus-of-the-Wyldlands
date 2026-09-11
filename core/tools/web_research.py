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
import ipaddress
import socket
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor


class _SearchLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and 'result__a' in attrs.get('class', '').split():
            href = attrs.get('href', '')
            parsed = urllib.parse.urlparse(href)
            href = urllib.parse.parse_qs(parsed.query).get('uddg', [href])[0]
            if href.startswith(('http://', 'https://')):
                self.current = [href, []]

    def handle_data(self, data):
        if self.current is not None:
            self.current[1].append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.current is not None:
            url, title = self.current
            self.results.append((''.join(title).strip() or url, url, ''))
            self.current = None


def _ddg_search(query):
    response = requests.get('https://html.duckduckgo.com/html/',
                            params={'q': query}, headers=HEADERS, timeout=15)
    response.raise_for_status()
    parser = _SearchLinks()
    parser.feed(response.text)
    return parser.results


def research_context(query, limit=4):
    """Return bounded page evidence with URLs; unavailable sources stay explicit."""
    query = (query or '').strip()
    limit = max(1, min(int(limit), 5))
    if not query:
        return {'sources': [], 'context': ''}
    if query.startswith(('https://', 'http://')) and not any(c.isspace() for c in query):
        results = [(query, query, '')]
    else:
        results = []
        for search in (_ddg_search, _ddg_instant, lambda q: _wikipedia(q, limit)):
            try:
                results = search(query)
                if results:
                    break
            except requests.RequestException:
                continue
    unique = {}
    for title, url, snippet in results:
        if url and url not in unique:
            unique[url] = (title, url, snippet)
    def read(item):
        title, url, snippet = item
        page = fetch_url(url, max_chars=3500)
        unavailable = page.startswith(('Fetch failed', 'Refused:'))
        if unavailable and not snippet:
            return None
        return {'title': title, 'url': url,
                'text': ('Search summary only: ' + snippet) if unavailable else page}
    with ThreadPoolExecutor(max_workers=limit) as pool:
        sources = [source for source in pool.map(read, list(unique.values())[:limit]) if source]
    context = '\n\n'.join(f"[{i}] {s['title']}\nURL: {s['url']}\n{s['text']}"
                          for i, s in enumerate(sources, 1))
    return {'sources': sources, 'context': context}

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
        current = url
        for _ in range(6):
            parsed = urllib.parse.urlsplit(current)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                return 'Refused: only public HTTP(S) URLs without credentials are supported.'
            addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                return 'Refused: research cannot access private or local network addresses.'
            with requests.get(current, headers=HEADERS, timeout=20, stream=True, allow_redirects=False) as r:
                if r.is_redirect:
                    current = urllib.parse.urljoin(current, r.headers['Location'])
                    continue
                r.raise_for_status()
                ctype = (r.headers.get('Content-Type') or '').lower()
                if not any(x in ctype for x in ('html', 'text', 'xml', 'json')):
                    return f'Refused: unsupported content-type {ctype}'
                chunks = []
                total = 0
                for chunk in r.iter_content(16384):
                    total += len(chunk)
                    if total > 2_000_000:
                        break
                    chunks.append(chunk)
                raw = b''.join(chunks).decode(r.encoding or 'utf-8', errors='replace')
                text = raw if 'json' in ctype else _strip_tags(raw)
                break
        else:
            return 'Fetch failed: too many redirects'
        if len(text) > max_chars:
            text = text[:max_chars] + "…"
        return f"----- {url} -----\n{text}"
    except Exception as e:
        return f"Fetch failed for {url}: {e}"
