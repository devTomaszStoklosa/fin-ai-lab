from collections import defaultdict

from fin_ai_lab.investment_committee.models import Perspective, Thesis

_OUTCOME_VALUE = {"accurate": 1.0, "inaccurate": 0.0}


def brier_score(theses: list[Thesis]) -> float:
    """REQ-011: mean squared error between each thesis's stated confidence
    (the predicted probability of "accurate") and its actual resolved
    outcome. Only resolved theses (accurate/inaccurate) carry a real
    outcome to score against — "not_yet_resolvable" and unresolved (None)
    theses are excluded, same as weights.py's precedent of raising on an
    empty/meaningless input rather than returning a misleading number."""
    resolved = [thesis for thesis in theses if thesis.outcome in _OUTCOME_VALUE]
    if not resolved:
        raise ValueError("No resolved theses to score")

    return sum(
        (thesis.confidence - _OUTCOME_VALUE[thesis.outcome]) ** 2 for thesis in resolved
    ) / len(resolved)


def brier_score_by_perspective(theses: list[Thesis]) -> dict[Perspective, float]:
    """REQ-011: "per subagent perspective, so persistent over/under-
    confidence is visible" — groups theses by perspective and scores each
    group independently, skipping a perspective with nothing resolved yet
    rather than failing the whole report over one incomplete perspective."""
    by_perspective: dict[Perspective, list[Thesis]] = defaultdict(list)
    for thesis in theses:
        by_perspective[thesis.perspective].append(thesis)

    scores = {}
    for perspective, group in by_perspective.items():
        try:
            scores[perspective] = brier_score(group)
        except ValueError:
            continue
    return scores
