import httpx

from fin_ai_lab.market_pulse.models import Alert

NTFY_BASE_URL = "https://ntfy.sh"


async def send_alerts(alerts: list[Alert], topic: str) -> None:
    """Sends one push notification per alert via ntfy.sh (verified live,
    docs.ntfy.sh/publish/): a plain POST with the message as the body, no
    account or API key — the topic itself acts as the shared secret."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        for alert in alerts:
            response = await client.post(
                f"{NTFY_BASE_URL}/{topic}",
                content=alert.message.encode("utf-8"),
                headers={"Title": f"Market Pulse: {alert.series_id}"},
            )
            response.raise_for_status()
