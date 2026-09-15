from decimal import Decimal

from pydantic import BaseModel

from fin_ai_lab.core.evals.models import RunContext


class SmokeOutput(BaseModel):
    sum: int


async def target(case_input: dict, ctx: RunContext) -> dict:
    return {"sum": case_input["a"] + case_input["b"]}


async def estimate(case_input: dict, ctx: RunContext) -> Decimal:
    return Decimal(0)
