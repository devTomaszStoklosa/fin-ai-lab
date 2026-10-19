import httpx

from fin_ai_lab.news_classifier.ingest.news_rss import NEWS_FEEDS, collect_headlines

BANKIER_XML = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
<item>
  <title>Kurs Orlenu rośnie</title>
  <link>https://www.bankier.pl/wiadomosc/orlen</link>
  <description>&lt;p&gt;Kurs Orlenu wzrósł o 5% po publikacji wyników.&lt;/p&gt;</description>
  <pubDate>Thu, 17 Sep 2026 17:22:00 +0100</pubDate>
</item>
</channel></rss>"""

STREFA_XML = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
<item>
  <title>Allegro podsumowuje kwartał</title>
  <link>https://strefainwestorow.pl/wiadomosci/allegro</link>
  <description>Allegro opublikowało wyniki finansowe za ostatni kwartał.</description>
  <pubDate>Tue, 30 Sep 2025 09:11:46 +0000</pubDate>
</item>
</channel></rss>"""


def _patch_transport(monkeypatch, transport: httpx.MockTransport) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


async def test_collect_headlines_parses_both_feeds_with_published_at(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "bankier" in str(request.url):
            return httpx.Response(200, content=BANKIER_XML)
        return httpx.Response(200, content=STREFA_XML)

    _patch_transport(monkeypatch, httpx.MockTransport(handler))

    headlines = await collect_headlines()

    assert len(headlines) == len(NEWS_FEEDS)
    bankier = next(h for h in headlines if h.source == "bankier")
    assert bankier.headline == "Kurs Orlenu rośnie"
    assert "<p>" not in bankier.lead
    assert bankier.published_at.year == 2026


async def test_collect_headlines_skips_a_failed_feed_not_the_whole_collection(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "bankier" in str(request.url):
            raise httpx.ConnectError("boom")
        return httpx.Response(200, content=STREFA_XML)

    _patch_transport(monkeypatch, httpx.MockTransport(handler))
    # Explicit two-feed subset, not the module-level NEWS_FEEDS — this test
    # is about one-feed-fails-the-rest-survive behavior, not the current
    # feed count, so it shouldn't need updating every time a feed is added.
    feeds = {
        "bankier": "https://www.bankier.pl/rss/gielda.xml",
        "strefa-inwestorow": "https://strefainwestorow.pl/rss.xml",
    }

    headlines = await collect_headlines(feeds)

    assert len(headlines) == 1
    assert headlines[0].source == "strefa-inwestorow"
