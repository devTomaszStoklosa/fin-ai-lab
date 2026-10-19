from decimal import Decimal

from fin_ai_lab.portfolio_webapp.dividend_tax import (
    UNKNOWN_TAX,
    DividendTax,
    dividend_tax,
    issuer_country,
)

D = Decimal


def test_polish_company_in_ike_or_ikze_is_tax_free() -> None:
    for account in ("ike", "ikze"):
        assert dividend_tax(account_type=account, country="PL", observed=None) == DividendTax(
            D(0), D(0), "rule"
        )


def test_foreign_company_in_ike_loses_only_its_withholding_tax() -> None:
    assert dividend_tax(account_type="ike", country="US", observed=D("0.15")) == DividendTax(
        D("0.15"), D(0), "statement"
    )
    # Not paid yet: the rate seen for the country in the statements.
    assert dividend_tax(account_type="ikze", country="FR", observed=None) == DividendTax(
        D("0.25"), D(0), "rule"
    )


def test_polish_company_on_a_regular_account_pays_19_percent_at_the_broker() -> None:
    assert dividend_tax(account_type="regular", country="PL", observed=None) == DividendTax(
        D("0.19"), D(0), "rule"
    )


def test_foreign_withholding_below_19_percent_leaves_a_top_up_on_a_regular_account() -> None:
    assert dividend_tax(account_type="regular", country="US", observed=D("0.15")) == DividendTax(
        D("0.15"), D("0.04"), "statement"
    )
    # Above 19% nothing is due -- and nothing comes back either.
    assert dividend_tax(account_type="regular", country="DK", observed=None) == DividendTax(
        D("0.27"), D(0), "rule"
    )
    assert dividend_tax(account_type="regular", country="IE", observed=None) == DividendTax(
        D(0), D("0.19"), "rule"
    )


def test_the_statement_beats_the_country_rule() -> None:
    # A Danish company listed in the US: the exchange says US, XTB took 27%.
    tax = dividend_tax(account_type="regular", country="US", observed=D("0.27"))

    assert (tax.withheld, tax.top_up, tax.basis) == (D("0.27"), D(0), "statement")


def test_unknown_account_type_or_country_is_unknown() -> None:
    assert dividend_tax(account_type="other", country="US", observed=D("0.15")) == UNKNOWN_TAX
    assert dividend_tax(account_type=None, country="PL", observed=None) == UNKNOWN_TAX
    assert dividend_tax(account_type="regular", country="JP", observed=None) == UNKNOWN_TAX
    assert dividend_tax(account_type="ike", country=None, observed=None) == UNKNOWN_TAX


def test_issuer_country_from_isin_else_xtb_suffix() -> None:
    assert issuer_country(isin="US40412C1018", xtb_symbol=None) == "US"
    assert issuer_country(isin=None, xtb_symbol="ATR.PL") == "PL"
    assert issuer_country(isin=None, xtb_symbol="ISAC.UK") == "GB"
    assert issuer_country(isin=None, xtb_symbol="ABC.XX") is None
    # An XTB key is not an ISIN, however it's shaped.
    assert issuer_country(isin="xtb:ABCDE.US", xtb_symbol=None) is None
