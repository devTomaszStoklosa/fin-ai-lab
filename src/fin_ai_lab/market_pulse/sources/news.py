import asyncio
import html
import re
from xml.etree import ElementTree

import httpx

from fin_ai_lab.market_pulse.models import NewsItem

# Trimming limits per docs/DATA-SOURCES.md art. 15 DSM note: title <= 120,
# summary <= 150 chars. Strefa Inwestorów's <description> is close to the
# full article, so trimming there is critical, not optional.
TITLE_MAX_CHARS = 120
SUMMARY_MAX_CHARS = 150
MAX_ITEMS_PER_FEED = 5

NEWS_FEEDS: dict[str, str] = {
    "bankier": "https://www.bankier.pl/rss/gielda.xml",
    "strefa-inwestorow": "https://strefainwestorow.pl/rss.xml",
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")


async def fetch_news() -> tuple[list[NewsItem], list[str]]:
    """Fetches both configured PL market news RSS feeds in parallel.
    Deliberately bypasses ThrottledHttpClient's disk cache — like
    nbp.fetch_reference_rate(), an RSS feed always reflects "now", so
    caching it would silently go stale between runs (03-design.md risk)."""

    async def fetch_one(source: str, url: str) -> list[NewsItem] | str:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
        except httpx.HTTPError:
            return f"news:{source}"

        root = ElementTree.fromstring(response.content)
        items = []
        for item in root.findall(".//item")[:MAX_ITEMS_PER_FEED]:
            title = _clean(item.findtext("title") or "")[:TITLE_MAX_CHARS]
            summary = _clean(item.findtext("description") or "")[:SUMMARY_MAX_CHARS]
            link = item.findtext("link") or ""
            items.append(NewsItem(title=title, summary=summary, source=source, link=link))
        return items

    results = await asyncio.gather(*(fetch_one(source, url) for source, url in NEWS_FEEDS.items()))

    news: list[NewsItem] = []
    missing: list[str] = []
    for result in results:
        if isinstance(result, str):
            missing.append(result)
        else:
            news.extend(result)
    return news, missing


def _clean(raw_html: str) -> str:
    return html.unescape(_HTML_TAG_RE.sub("", raw_html)).strip()
