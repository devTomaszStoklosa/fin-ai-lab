from decimal import Decimal

from fin_ai_lab.core.evals.models import RunContext
from fin_ai_lab.portfolio_xray.privacy.injection import looks_like_injection


async def target(case_input: dict, ctx: RunContext) -> dict:
    return {"flagged": looks_like_injection(case_input["text"])}


async def estimate(case_input: dict, ctx: RunContext) -> Decimal:
    return Decimal(0)
