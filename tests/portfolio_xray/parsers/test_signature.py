from fin_ai_lab.portfolio_xray.parsers.signature import compute_signature


def test_signature_is_stable_for_same_headers() -> None:
    left = compute_signature(["A", "B"], delimiter=";", encoding="utf-8")
    right = compute_signature(["a", " b "], delimiter=";", encoding="utf-8")

    assert left == right


def test_signature_differs_for_different_sheet_name() -> None:
    left = compute_signature(["A", "B"], delimiter=None, encoding="utf-8", sheet_name="Sheet1")
    right = compute_signature(["A", "B"], delimiter=None, encoding="utf-8", sheet_name="Sheet2")

    assert left != right


def test_signature_ignores_empty_headers() -> None:
    left = compute_signature(["A", "", "B"], delimiter=None, encoding="utf-8")
    right = compute_signature(["A", "B"], delimiter=None, encoding="utf-8")

    assert left == right
