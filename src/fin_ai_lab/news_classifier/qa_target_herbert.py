from functools import lru_cache
from pathlib import Path
from typing import get_args

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from fin_ai_lab.core.evals.models import RunContext
from fin_ai_lab.news_classifier.models import EventType, Headline, Sentiment
from fin_ai_lab.news_classifier.ticker_catalog import TICKER_CATALOG

# `torch`/`transformers` are a separate module (not `qa_target.py`) on
# purpose — the majority/tfidf/few-shot suites must stay runnable without
# the `herbert` extra installed (ext = ["torch", "transformers"], ~1 GB).
MODEL_ID = "allegro/herbert-base-cased"
SENTIMENTS = list(get_args(Sentiment))
EVENT_TYPES = list(get_args(EventType))

# `herbert_finetune.ipynb` saves checkpoints to Google Drive, never to
# this repo (training/README.md) — REQ-021 needs them on the local disk
# that will actually run inference, so copy the two checkpoint folders
# from Drive into this gitignored path (.gitignore's data/private/)
# before running the `p4-classifier-herbert` suite.
CHECKPOINT_DIR = Path("data/private/herbert_checkpoints")


@lru_cache(maxsize=1)
def _tokenizer() -> AutoTokenizer:
    return AutoTokenizer.from_pretrained(MODEL_ID)


@lru_cache(maxsize=1)
def _sentiment_model() -> AutoModelForSequenceClassification:
    model = AutoModelForSequenceClassification.from_pretrained(CHECKPOINT_DIR / "sentiment")
    model.eval()
    return model


@lru_cache(maxsize=1)
def _event_type_model() -> AutoModelForSequenceClassification:
    model = AutoModelForSequenceClassification.from_pretrained(CHECKPOINT_DIR / "event_type")
    model.eval()
    return model


def _match_tickers(text: str) -> list[str]:
    lowered = text.lower()
    return [ticker for ticker, name in TICKER_CATALOG.items() if name.lower() in lowered]


async def herbert_target(case_input: dict, _ctx: RunContext) -> dict:
    headline = Headline(**case_input)
    text = f"{headline.headline} {headline.lead or ''}".strip()

    tokenizer = _tokenizer()
    inputs = tokenizer(text, truncation=True, max_length=128, return_tensors="pt")

    sentiment_model = _sentiment_model()
    event_type_model = _event_type_model()
    with torch.no_grad():
        # Same fix as predict_one() in herbert_finetune.ipynb: a fresh
        # tokenizer() call returns CPU tensors, but a model can be on a
        # different device (not relevant on this CPU-only machine, but
        # keeps this target correct if it's ever run on a GPU box too).
        sentiment_inputs = {k: v.to(sentiment_model.device) for k, v in inputs.items()}
        sentiment_id = sentiment_model(**sentiment_inputs).logits.argmax(dim=1).item()

        event_type_inputs = {k: v.to(event_type_model.device) for k, v in inputs.items()}
        event_type_id = event_type_model(**event_type_inputs).logits.argmax(dim=1).item()

    return {
        "sentiment": SENTIMENTS[sentiment_id],
        "event_type": EVENT_TYPES[event_type_id],
        "tickers": _match_tickers(text),
    }
