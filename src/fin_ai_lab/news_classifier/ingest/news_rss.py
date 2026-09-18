import asyncio
import html
import re
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import httpx

from fin_ai_lab.news_classifier.models import Headline

# 02-spec.md REQ-004: lead kept, full article body never stored.
LEAD_MAX_CHARS = 150

# Same feeds as market_pulse/sources/news.py, different purpose: this
# collects for the training/eval corpus, not a daily brief, so there is no
# per-run item cap — RSS itself has no deep history, so repeated collection
# runs over time (not one big pull) is what actually builds the corpus
# (01-story.md's 150-300 headlines/day volume).
NEWS_FEEDS: dict[str, str] = {
    "bankier": "https://www.bankier.pl/rss/gielda.xml",
    "strefa-inwestorow": "https://strefainwestorow.pl/rss.xml",
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")


async def collect_headlines(feeds: dict[str, str] = NEWS_FEEDS) -> list[Headline]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        results = await asyncio.gather(
            *(_fetch_one(client, source, url) for source, url in feeds.items()),
            return_exceptions=True,
        )

    headlines: list[Headline] = []
    for result in results:
        if isinstance(result, BaseException):
            continue
        headlines.extend(result)
    return headlines


async def _fetch_one(client: httpx.AsyncClient, source: str, url: str) -> list[Headline]:
    response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()

    root = ElementTree.fromstring(response.content)
    headlines: list[Headline] = []
    for item in root.findall(".//item"):
        title = _clean(item.findtext("title") or "")
        pub_date_raw = item.findtext("pubDate")
        if not title or not pub_date_raw:
            continue
        lead = _clean(item.findtext("description") or "")[:LEAD_MAX_CHARS] or None
        headlines.append(
            Headline(
                headline=title,
                lead=lead,
                source=source,
                published_at=parsedate_to_datetime(pub_date_raw),
            )
        )
    return headlines


def _clean(raw_html: str) -> str:
    return html.unescape(_HTML_TAG_RE.sub("", raw_html)).strip()
