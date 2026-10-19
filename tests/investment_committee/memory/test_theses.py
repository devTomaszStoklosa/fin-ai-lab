from datetime import date
from decimal import Decimal
from pathlib import Path

from fin_ai_lab.investment_committee.memory.theses import append_theses, load_theses, reckon_theses
from fin_ai_lab.investment_committee.models import Thesis
from fin_ai_lab.portfolio_xray.canonical import Portfolio, Position


def _portfolio(valuation_date: date) -> Portfolio:
    return Portfolio(
        valuation_date=valuation_date,
        positions=[
            Position(
                broker="xtb", account_type="regular", instrument_name="Orlen",
                asset_class="equity", quantity=Decimal("10"),
                market_value=Decimal("1000"), market_currency="PLN",
                valuation_date=valuation_date,
            )
        ],
    )


def _thesis(**overrides) -> Thesis:
    defaults = {
        "statement": "Reżim neutralny utrzyma się.",
        "made_at": date(2026, 1, 1),
        "horizon": "1 month",
        "perspective": "macro",
        "confidence": 0.7,
    }
    return Thesis(**{**defaults, **overrides})


def test_append_and_load_theses_round_trip(tmp_path: Path) -> None:
    theses = [_thesis(), _thesis(statement="Sentyment pozostanie słaby.")]

    append_theses("data/private/xtb/portfolio.xlsx", theses, directory=tmp_path)
    loaded = load_theses("data/private/xtb/portfolio.xlsx", directory=tmp_path)

    assert loaded == theses


def test_load_theses_returns_empty_list_when_no_file_exists(tmp_path: Path) -> None:
    assert load_theses("unknown-portfolio", directory=tmp_path) == []


def test_append_theses_is_additive_across_calls(tmp_path: Path) -> None:
    append_theses("portfolio-1", [_thesis()], directory=tmp_path)
    append_theses("portfolio-1", [_thesis(statement="Druga teza.")], directory=tmp_path)

    assert len(load_theses("portfolio-1", directory=tmp_path)) == 2


def test_reckon_theses_marks_not_yet_resolvable_before_horizon_elapses() -> None:
    thesis = _thesis(made_at=date(2026, 1, 1), horizon="1 year")

    reckoned = reckon_theses([thesis], _portfolio(date(2026, 2, 1)))

    assert reckoned[0].outcome == "not_yet_resolvable"


def test_reckon_theses_leaves_outcome_unset_once_horizon_has_elapsed() -> None:
    thesis = _thesis(made_at=date(2026, 1, 1), horizon="1 month")

    reckoned = reckon_theses([thesis], _portfolio(date(2026, 6, 1)))

    # Horizon elapsed, but this function makes no truth judgment on its own.
    assert reckoned[0].outcome is None


def test_reckon_theses_never_overwrites_an_already_resolved_thesis() -> None:
    thesis = _thesis(made_at=date(2026, 1, 1), horizon="1 month", outcome="accurate")

    reckoned = reckon_theses([thesis], _portfolio(date(2026, 6, 1)))

    assert reckoned[0].outcome == "accurate"


def test_reckon_theses_marks_unparseable_horizon_as_not_yet_resolvable() -> None:
    thesis = _thesis(horizon="do odwołania")

    reckoned = reckon_theses([thesis], _portfolio(date(2026, 9, 19)))

    assert reckoned[0].outcome == "not_yet_resolvable"
