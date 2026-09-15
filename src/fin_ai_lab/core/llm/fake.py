import uuid
from decimal import Decimal

from pydantic import BaseModel

from fin_ai_lab.core.llm.client import LlmRequest, LlmResult, TokenUsage


class FakeLlmClient:
    def __init__(self, responses: dict[str, str]) -> None:
        self._responses = responses
        self.requests: list[LlmRequest] = []
        self.total_cost_usd = Decimal(0)

    async def complete(self, request: LlmRequest) -> LlmResult:
        self.requests.append(request)
        text = self._responses[request.prompt_id or request.model]

        parsed: BaseModel | None = None
        if request.response_schema is not None:
            parsed = request.response_schema.model_validate_json(text)

        return LlmResult(
            text=text,
            parsed=parsed,
            finish_reason="STOP",
            incomplete=False,
            usage=TokenUsage(input_tokens=0, output_tokens=0),
            cost_usd=Decimal(0),
            latency_ms=0,
            trace_id=uuid.uuid4().hex,
            span_id=uuid.uuid4().hex,
        )
