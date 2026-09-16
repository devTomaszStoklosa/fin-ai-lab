from fin_ai_lab.core.evals.models import RunContext
from fin_ai_lab.portfolio_xray.canonical import Position
from fin_ai_lab.portfolio_xray.sectors.classifier import classify_sector

# No estimate() here on purpose: unlike the other eval targets in this repo,
# this one makes a real LLM call, so its cost is genuinely unknown ahead of
# time — the runner's cost guard should ask before spending, not be told 0.


async def target(case_input: dict, ctx: RunContext) -> dict:
    position = Position(**case_input["position"])
    model = ctx.model or "gemini-2.5-flash"
    sector = await classify_sector(position, ctx.llm_client, ctx.prompts, model)
    return {"sector": sector}
