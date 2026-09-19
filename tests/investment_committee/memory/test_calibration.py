from datetime import date

import pytest

from fin_ai_lab.investment_committee.memory.calibration import (
    brier_score,
    brier_score_by_perspective,
)
from fin_ai_lab.investment_committee.models import Thesis


def _thesis(**overrides) -> Thesis:
    defaults = {
        "statement": "Reżim neutralny utrzyma się.",
        "made_at": date(2026, 1, 1),
        "horizon": "1 month",
        "perspective": "macro",
        "confidence": 0.7,
        "outcome": "accurate",
    }
    return Thesis(**{**defaults, **overrides})


def test_brier_score_is_zero_for_a_perfectly_calibrated_confident_correct_thesis() -> None:
    thesis = _thesis(confidence=1.0, outcome="accurate")

    assert brier_score([thesis]) == 0.0


def test_brier_score_is_one_for_a_maximally_wrong_confident_thesis() -> None:
    thesis = _thesis(confidence=1.0, outcome="inaccurate")

    assert brier_score([thesis]) == 1.0


def test_brier_score_excludes_not_yet_resolvable_theses() -> None:
    resolved = _thesis(confidence=1.0, outcome="accurate")
    unresolved = _thesis(confidence=0.9, outcome="not_yet_resolvable")

    assert brier_score([resolved, unresolved]) == 0.0


def test_brier_score_raises_when_nothing_is_resolved() -> None:
    unresolved = _thesis(outcome="not_yet_resolvable")

    with pytest.raises(ValueError, match="No resolved theses"):
        brier_score([unresolved])


def test_brier_score_by_perspective_groups_and_skips_perspectives_with_nothing_resolved() -> None:
    theses = [
        _thesis(perspective="macro", confidence=1.0, outcome="accurate"),
        _thesis(perspective="sentiment", confidence=0.5, outcome="not_yet_resolvable"),
    ]

    scores = brier_score_by_perspective(theses)

    assert scores == {"macro": 0.0}
