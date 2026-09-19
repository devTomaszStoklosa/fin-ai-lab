from fin_ai_lab.news_classifier.metrics import confusion_matrix, macro_f1, per_class_metrics


def test_per_class_metrics_reports_zero_support_for_unseen_class() -> None:
    pairs = [("positive", "positive"), ("negative", "positive")]
    labels = ["positive", "negative", "neutral"]

    result = per_class_metrics(pairs, labels)

    assert result["neutral"]["support"] == 0
    assert result["neutral"]["f1"] == 0.0
    assert result["positive"]["support"] == 1
    assert result["positive"]["precision"] == 0.5


def test_macro_f1_excludes_classes_with_zero_support() -> None:
    pairs = [("positive", "positive"), ("negative", "negative")]
    labels = ["positive", "negative", "neutral"]

    result = macro_f1(pairs, labels)

    assert result == 1.0


def test_macro_f1_is_perfect_for_all_correct_predictions() -> None:
    pairs = [("a", "a"), ("b", "b"), ("a", "a")]
    labels = ["a", "b"]

    assert macro_f1(pairs, labels) == 1.0


def test_confusion_matrix_counts_expected_vs_actual() -> None:
    pairs = [("positive", "positive"), ("positive", "negative"), ("negative", "negative")]
    labels = ["positive", "negative"]

    matrix = confusion_matrix(pairs, labels)

    assert matrix == {
        "positive": {"positive": 1, "negative": 1},
        "negative": {"positive": 0, "negative": 1},
    }
