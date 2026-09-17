from decimal import Decimal

import httpx

from fin_ai_lab.market_pulse.models import Alert
from fin_ai_lab.market_pulse.notifications.ntfy import send_alerts


def _alert(series_id: str = "DGS10") -> Alert:
    return Alert(
        series_id=series_id, previous_value=Decimal("4.5"), new_value=Decimal("4.7"),
        threshold=Decimal("0.1"), message=f"{series_id} zmiana",
    )


async def test_send_alerts_posts_one_request_per_alert_to_the_topic(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    await send_alerts([_alert("DGS10"), _alert("DGS2")], topic="my-secret-topic")

    assert len(requests) == 2
    assert all(str(request.url) == "https://ntfy.sh/my-secret-topic" for request in requests)
    assert requests[0].content == b"DGS10 zmiana"
