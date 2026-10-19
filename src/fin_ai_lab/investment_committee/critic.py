import json
from decimal import Decimal

from pydantic import BaseModel

from fin_ai_lab.core.llm.client import LlmClient, LlmRequest
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.investment_committee.budget import BudgetGuard
from fin_ai_lab.investment_committee.models import Brief

_BUDGET_REJECTION = "Budżet komitetu wyczerpany przed weryfikacją źródeł przez krytyka."
_UNSOURCED_REJECTION = "Twierdzenie bez wystarczającego wsparcia zostało usunięte przez krytyka."


class _ClaimVerdict(BaseModel):
    has_identifiable_source: bool
    reason: str


class _CriticVerdict(BaseModel):
    claim_verdicts: list[_ClaimVerdict]


async def critique_brief(
    brief: Brief,
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
    budget: BudgetGuard,
) -> Brief:
    """P5-S4, REQ-041: the critic only judges whether each of a brief's
    claims has an identifiable source — per 02-spec.md it never writes new
    claims or rewrites the conclusion itself ("ocena, nie generuje nowych
    twierdzeń"). Every rewrite below (stripping an unsourced claim,
    zeroing confidence) is done in code, from the critic's yes/no verdicts,
    never by asking the model to regenerate the brief."""
    if brief.confidence <= 0:
        return brief  # nothing asserted, nothing to source (e.g. a P2/P4 stub)
    if not brief.claims:
        return _reject(brief, _UNSOURCED_REJECTION)
    if not budget.check(Decimal(0)):
        return _reject(brief, _BUDGET_REJECTION)

    prompt = prompt_registry.get("critic", 1)
    request = LlmRequest(
        model=model,
        messages=[
            {
                "role": "user",
                "text": prompt.render(
                    perspective=brief.perspective, claims_json=_claims_payload(brief)
                ),
            }
        ],
        response_schema=_CriticVerdict,
        prompt_id="critic",
        prompt_version=1,
    )
    result = await llm_client.complete(request)
    budget.record(result.cost_usd)

    verdict = result.parsed
    if not isinstance(verdict, _CriticVerdict) or len(verdict.claim_verdicts) != len(brief.claims):
        raise ValueError(f"critic verdict for perspective '{brief.perspective}' malformed")

    sourced_claims = [
        claim
        for claim, claim_verdict in zip(brief.claims, verdict.claim_verdicts, strict=True)
        if claim_verdict.has_identifiable_source
    ]
    if len(sourced_claims) == len(brief.claims):
        return brief
    if sourced_claims:
        return brief.model_copy(update={"claims": sourced_claims})
    return _reject(brief, _UNSOURCED_REJECTION)


def _reject(brief: Brief, reason: str) -> Brief:
    return brief.model_copy(
        update={
            "conclusion": f"[ODRZUCONE PRZEZ KRYTYKA] {reason}",
            "confidence": 0.0,
            "claims": [],
        }
    )


def _claims_payload(brief: Brief) -> str:
    return json.dumps(
        [
            {"text": claim.text, "source_type": claim.source_type, "source_ref": claim.source_ref}
            for claim in brief.claims
        ],
        ensure_ascii=False,
    )
