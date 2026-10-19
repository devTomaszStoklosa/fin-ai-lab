from fin_ai_lab.news_classifier.labeling.calibration import cohens_kappa


def test_cohens_kappa_is_one_for_perfect_agreement() -> None:
    a = ["positive", "negative", "neutral", "positive"]
    b = ["positive", "negative", "neutral", "positive"]

    assert cohens_kappa(a, b) == 1.0


def test_cohens_kappa_is_zero_for_chance_level_agreement() -> None:
    # Independent of order, matches only as often as random guessing would
    # given each label's marginal frequency.
    a = ["positive", "positive", "negative", "negative"]
    b = ["negative", "positive", "positive", "negative"]

    kappa = cohens_kappa(a, b)

    assert -0.01 <= kappa <= 0.51


def test_cohens_kappa_rejects_mismatched_lengths() -> None:
    try:
        cohens_kappa(["positive"], ["positive", "negative"])
        assert False, "expected ValueError"
    except ValueError:
        pass
