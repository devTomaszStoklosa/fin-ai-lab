import httpx

from fin_ai_lab.market_pulse.sources.news import NEWS_FEEDS, fetch_news

BANKIER_XML = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
<item>
  <title>Kurs Orlenu rośnie</title>
  <link>https://www.bankier.pl/wiadomosc/orlen</link>
  <description>&lt;p&gt;Kurs Orlenu wzrósł o 5% po publikacji wyników.&lt;/p&gt;</description>
</item>
</channel></rss>"""

STREFA_XML = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
<item>
  <title>Allegro podsumowuje kwartał</title>
  <link>https://strefainwestorow.pl/wiadomosci/allegro</link>
  <description>Allegro opublikowało wyniki finansowe za ostatni kwartał.</description>
</item>
</channel></rss>"""


def _mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if "bankier" in str(request.url):
            return httpx.Response(200, content=BANKIER_XML)
        return httpx.Response(200, content=STREFA_XML)

    return httpx.MockTransport(handler)


async def test_fetch_news_parses_and_trims_both_feeds(monkeypatch) -> None:
    transport = _mock_transport()
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    news, missing = await fetch_news()

    assert missing == []
    assert len(news) == len(NEWS_FEEDS)
    bankier_item = next(item for item in news if item.source == "bankier")
    assert bankier_item.title == "Kurs Orlenu rośnie"
    assert "<p>" not in bankier_item.summary
    assert "wzrósł o 5%" in bankier_item.summary


async def test_fetch_news_reports_a_failed_feed_as_missing_not_a_crash(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "bankier" in str(request.url):
            raise httpx.ConnectError("boom")
        return httpx.Response(200, content=STREFA_XML)

    transport = httpx.MockTransport(handler)
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    news, missing = await fetch_news()

    assert missing == ["news:bankier"]
    assert len(news) == 1
    assert news[0].source == "strefa-inwestorow"
