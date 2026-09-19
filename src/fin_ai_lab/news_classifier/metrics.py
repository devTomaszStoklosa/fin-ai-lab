from typing import TypedDict


class ClassMetrics(TypedDict):
    precision: float
    recall: float
    f1: float
    support: int


def per_class_metrics(pairs: list[tuple[str, str]], labels: list[str]) -> dict[str, ClassMetrics]:
    """`pairs` is (expected, actual) per case. `labels` is the full label
    space (e.g. all 13 event types), not just the ones seen in `pairs` —
    same fix as `herbert_finetune.ipynb`'s `classification_report` bug: a
    small test set can miss a class entirely, and that has to show up as
    zero support, not silently disappear from the report (REQ-020 edge
    case, docs/EVALS.md rule 5)."""
    result: dict[str, ClassMetrics] = {}
    for label in labels:
        true_positives = sum(
            1 for expected, actual in pairs if expected == label and actual == label
        )
        false_positives = sum(
            1 for expected, actual in pairs if expected != label and actual == label
        )
        false_negatives = sum(
            1 for expected, actual in pairs if expected == label and actual != label
        )
        support = sum(1 for expected, _ in pairs if expected == label)

        precision = (
            true_positives / (true_positives + false_positives)
            if (true_positives + false_positives)
            else 0.0
        )
        recall = (
            true_positives / (true_positives + false_negatives)
            if (true_positives + false_negatives)
            else 0.0
        )
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

        result[label] = ClassMetrics(precision=precision, recall=recall, f1=f1, support=support)
    return result


def macro_f1(pairs: list[tuple[str, str]], labels: list[str]) -> float:
    """Unweighted mean F1 over classes actually present in `pairs`
    (support > 0) — a class with zero support in a tiny test set has no
    F1 to average in, and including it as 0.0 would understate the
    model's real performance on the classes it was actually tested on."""
    per_class = per_class_metrics(pairs, labels)
    present = [metrics["f1"] for metrics in per_class.values() if metrics["support"] > 0]
    return sum(present) / len(present) if present else 0.0


def confusion_matrix(pairs: list[tuple[str, str]], labels: list[str]) -> dict[str, dict[str, int]]:
    """Rows are expected, columns are actual — `matrix[expected][actual]`."""
    matrix = {expected: {actual: 0 for actual in labels} for expected in labels}
    for expected, actual in pairs:
        matrix[expected][actual] += 1
    return matrix
