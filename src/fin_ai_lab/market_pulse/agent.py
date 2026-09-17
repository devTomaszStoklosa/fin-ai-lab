from fin_ai_lab.core.llm.client import LlmClient, LlmRequest
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.market_pulse.sources.fred import FredClient
from fin_ai_lab.market_pulse.sources.nbp import NbpClient
from fin_ai_lab.market_pulse.tools import build_tools


async def ask(
    question: str,
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
    fred_client: FredClient,
    nbp_client: NbpClient,
) -> str:
    """P3-S2: the model decides which data source(s) to query, instead of
    P3-S1's fixed indicator list — via the SDK's automatic function
    calling (see core.llm.client.LlmRequest.tools)."""
    tools = build_tools(fred_client, nbp_client)
    prompt = prompt_registry.get("ask", 1)
    rendered = prompt.render(question=question)

    request = LlmRequest(
        model=model,
        messages=[{"role": "user", "text": rendered}],
        tools=tools,
        prompt_id="ask",
        prompt_version=1,
    )
    result = await llm_client.complete(request)
    return result.text
