from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import quote_plus

import httpx

from .base import Tool

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


class WebFetchTool(Tool):
    name = "WebFetch"
    description = (
        "Fetch the content of a URL and return it as plain text. "
        "HTML is stripped to readable text. Useful for reading docs, articles, or APIs."
    )

    def run(self, url: str, timeout: int = 15) -> str:
        """
        Args:
            url: The URL to fetch.
            timeout: Request timeout in seconds.
        """
        try:
            with httpx.Client(follow_redirects=True, timeout=timeout, verify=False) as client:
                resp = client.get(url, headers=_HEADERS)
                resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            text = resp.text

            if "html" in content_type:
                text = _html_to_text(text)

            # Trim excessive blank lines
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            if len(text) > 20_000:
                text = text[:20_000] + f"\n\n[truncated — {len(resp.text)} chars total]"

            return text or "[empty response]"

        except httpx.HTTPStatusError as exc:
            return f"[error] HTTP {exc.response.status_code}: {url}"
        except httpx.TimeoutException:
            return f"[error] request timed out after {timeout}s: {url}"
        except Exception as exc:
            return f"[error] {exc}"


class WebSearchTool(Tool):
    name = "WebSearch"
    description = (
        "Search the web using DuckDuckGo and return a list of results "
        "(title, URL, snippet). No API key required."
    )

    def run(self, query: str, max_results: int = 8) -> str:
        """
        Args:
            query: Search query string.
            max_results: Maximum number of results to return.
        """
        # Try duckduckgo-search library first (better results)
        try:
            from duckduckgo_search import DDGS
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append(
                        f"**{r.get('title', 'No title')}**\n"
                        f"{r.get('href', '')}\n"
                        f"{r.get('body', '')}"
                    )
            if results:
                return "\n\n".join(results)
        except ImportError:
            pass
        except Exception:
            pass

        # Fallback: scrape DuckDuckGo HTML
        return _ddg_html_search(query, max_results)


# ── Helpers ────────────────────────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    """Minimal HTML → plain text converter."""

    SKIP_TAGS = {"script", "style", "noscript", "head", "nav", "footer", "aside"}

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []
        self._current_tag = ""

    def handle_starttag(self, tag, attrs):
        self._current_tag = tag
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag in ("p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"):
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped + " ")

    def get_text(self) -> str:
        return "".join(self._parts)


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        return parser.get_text()
    except Exception:
        # Last resort: strip all tags with regex
        return re.sub(r"<[^>]+>", " ", html)


def _ddg_html_search(query: str, max_results: int) -> str:
    """Scrape DuckDuckGo HTML search page."""
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    try:
        with httpx.Client(follow_redirects=True, timeout=10, verify=False) as client:
            resp = client.get(url, headers=_HEADERS)
            resp.raise_for_status()

        # Extract result blocks with simple regex
        # DDG HTML uses <a class="result__a"> for titles and <a class="result__url"> for URLs
        titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', resp.text, re.S)
        urls   = re.findall(r'class="result__url"[^>]*>\s*(.*?)\s*</a>', resp.text, re.S)
        snips  = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', resp.text, re.S)

        results = []
        for i, (title, url, snip) in enumerate(zip(titles, urls, snips)):
            if i >= max_results:
                break
            title = re.sub(r"<[^>]+>", "", title).strip()
            url   = re.sub(r"<[^>]+>", "", url).strip()
            snip  = re.sub(r"<[^>]+>", "", snip).strip()
            results.append(f"**{title}**\n{url}\n{snip}")

        return "\n\n".join(results) if results else f"[no results for: {query!r}]"

    except Exception as exc:
        return f"[error] web search failed: {exc}"
