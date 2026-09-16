from fin_ai_lab.portfolio_xray.privacy.pii import (
    MASKED,
    classify_pii_columns,
    looks_like_pii_header,
    mask_pii_values,
)


def test_looks_like_pii_header_matches_known_labels() -> None:
    for header in ["Imię i nazwisko", "Name", "PESEL", "E-mail", "Account number", "Adres"]:
        assert looks_like_pii_header(header) is True


def test_looks_like_pii_header_does_not_match_business_columns() -> None:
    for header in ["Instrument/Position", "Ticker", "Category", "Volume", "Value"]:
        assert looks_like_pii_header(header) is False


def test_classify_pii_columns_filters_headers() -> None:
    headers = ["Imię i nazwisko", "Ticker", "Numer rachunku", "Volume"]

    assert classify_pii_columns(headers) == ["Imię i nazwisko", "Numer rachunku"]


def test_mask_pii_values_replaces_only_classified_columns() -> None:
    rows = [{"Imię i nazwisko": "Jan Kowalski", "Ticker": "ISAC.UK", "Volume": 6}]

    masked = mask_pii_values(rows, pii_columns=["Imię i nazwisko"])

    assert masked[0]["Imię i nazwisko"] == MASKED
    assert masked[0]["Ticker"] == "ISAC.UK"
    assert masked[0]["Volume"] == 6


def test_mask_pii_values_leaves_empty_cells_untouched() -> None:
    rows = [{"Imię i nazwisko": None}, {"Imię i nazwisko": ""}]

    masked = mask_pii_values(rows, pii_columns=["Imię i nazwisko"])

    assert masked[0]["Imię i nazwisko"] is None
    assert masked[1]["Imię i nazwisko"] == ""
