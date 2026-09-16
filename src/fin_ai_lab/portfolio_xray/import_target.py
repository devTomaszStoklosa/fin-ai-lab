from datetime import date
from decimal import Decimal

from fin_ai_lab.core.evals.models import RunContext
from fin_ai_lab.portfolio_xray.importer import build_position


async def target(case_input: dict, ctx: RunContext) -> dict:
    row = case_input["raw_row"]
    column_mapping = case_input["column_mapping"]
    position = build_position(
        row,
        column_mapping,
        broker=case_input["broker"],
        account_type=case_input["account_type"],
        market_currency=case_input["market_currency"],
        valuation_date=date.fromisoformat(case_input["valuation_date"]),
    )
    return position.model_dump(mode="json")


async def estimate(case_input: dict, ctx: RunContext) -> Decimal:
    return Decimal(0)
