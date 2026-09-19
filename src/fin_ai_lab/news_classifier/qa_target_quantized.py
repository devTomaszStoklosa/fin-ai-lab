from functools import lru_cache
from pathlib import Path

from fin_ai_lab.core.evals.models import RunContext
from fin_ai_lab.news_classifier.inference.quantized import ChatCompletionClient, classify_quantized
from fin_ai_lab.news_classifier.models import Headline

# Separate module from qa_target.py, same reason as qa_target_herbert.py —
# majority/tfidf/few-shot must stay runnable without the `quantized` extra
# (llama-cpp-python, ~12 min source build on this machine) installed.
#
# scripts/news_classifier_quantize_bielik.py writes here — never committed
# (.gitignore's data/private/), same private-checkpoint pattern as
# data/private/herbert_checkpoints/.
MODEL_PATH = Path("data/private/bielik_quantized/model.gguf")


@lru_cache(maxsize=1)
def _llm() -> ChatCompletionClient:
    from fin_ai_lab.news_classifier.inference.quantized import load_llm

    return load_llm(MODEL_PATH)


async def quantized_target(case_input: dict, _ctx: RunContext) -> dict:
    headline = Headline(**case_input)
    label = classify_quantized(headline, llm=_llm())
    return label.model_dump()
