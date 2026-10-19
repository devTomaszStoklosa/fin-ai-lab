from functools import lru_cache

from fin_ai_lab.core.evals.models import RunContext
from fin_ai_lab.news_classifier.baselines.few_shot_llm import classify_few_shot
from fin_ai_lab.news_classifier.baselines.majority import classify_majority
from fin_ai_lab.news_classifier.baselines.tfidf_logreg import (
    TfidfLogRegModel,
    classify_tfidf_logreg,
)
from fin_ai_lab.news_classifier.corpus_store import load_labeled
from fin_ai_lab.news_classifier.models import Headline, LabeledHeadline
from fin_ai_lab.news_classifier.split import split_chronological


# P4-S7 (REQ-020/022): every non-fine-tuned model is compared against the
# same training data — the corpus's chronological train split, the same
# one herbert_finetune.ipynb trains on — so nothing here has ever seen a
# headline from the test split cases.jsonl is built from.
@lru_cache(maxsize=1)
def _train_split() -> list[LabeledHeadline]:
    train, _dev, _test = split_chronological(load_labeled())
    return train


@lru_cache(maxsize=1)
def _tfidf_model() -> TfidfLogRegModel:
    return TfidfLogRegModel.fit(_train_split())


async def majority_target(case_input: dict, _ctx: RunContext) -> dict:
    headline = Headline(**case_input)
    training_labels = [item.label for item in _train_split()]
    label = classify_majority(headline, training_labels=training_labels)
    return label.model_dump()


async def tfidf_target(case_input: dict, _ctx: RunContext) -> dict:
    headline = Headline(**case_input)
    label = classify_tfidf_logreg(headline, _tfidf_model())
    return label.model_dump()


async def few_shot_target(case_input: dict, ctx: RunContext) -> dict:
    headline = Headline(**case_input)
    label = await classify_few_shot(
        headline,
        ctx.llm_client,
        ctx.prompts,
        ctx.model or "openai/gpt-oss-120b",
        training=_train_split(),
    )
    return label.model_dump()
