"""Tax on a dividend by account type and issuer country (fin-ai-lab#267) --
pure rules, no database, no network.

Two figures per instrument and account:
- `withheld`: what is taken before the money reaches the account -- the
  withholding tax abroad, or the 19% a Polish broker takes from a Polish
  company's dividend on a regular account;
- `top_up`: what is still due in the Polish tax return -- on a regular
  account, foreign withholding below 19% leaves the difference to pay.

IKE and IKZE pay no Polish tax on dividends: a Polish company's dividend
arrives whole, a foreign one loses only its withholding tax at source.

For a foreign company the withholding rate comes from the account's own
statements when it has been paid before (that reflects the broker's actual
practice, W-8BEN included, and the issuer's real country behind a US
listing), otherwise from OBSERVED_WITHHOLDING. A description for the
estimate, not a tax settlement.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
POLISH_TAX = Decimal("0.19")
TAX_FREE_ACCOUNTS = frozenset({"ike", "ikze"})

# Withholding at source as the owner's own statements show it (XTB "WHT x%",
# Bossa "netto x%"/"brutto", 2024-2026), by the issuer's country -- used only
# for a company that hasn't paid this account yet. Treaties and broker
# paperwork (W-8BEN) change these; a country not seen there stays unknown.
OBSERVED_WITHHOLDING: dict[str, Decimal] = {
    "US": Decimal("0.15"),
    "GB": Decimal(0),
    "IE": Decimal(0),
    "FR": Decimal("0.25"),
    "DE": Decimal("0.26375"),
    "DK": Decimal("0.27"),
    "MX": Decimal("0.10"),
}

# XTB's symbol suffix -> the country of the exchange, a stand-in for the
# issuer's country when there's no ISIN (XTB exports have none). A foreign
# company listed in the US reads as "US" here; its own statements correct it.
_XTB_SUFFIX_COUNTRY = {
    "US": "US",
    "PL": "PL",
    "UK": "GB",
    "DE": "DE",
    "FR": "FR",
    "NL": "NL",
    "BE": "BE",
}

TaxBasis = Literal["statement", "rule", "unknown"]


@dataclass(frozen=True)
class DividendTax:
    withheld: Decimal | None  # fraction taken before payout; None: unknown
    top_up: Decimal  # fraction still due in the Polish tax return
    basis: TaxBasis  # where `withheld` comes from


UNKNOWN_TAX = DividendTax(None, Decimal(0), "unknown")


def issuer_country(*, isin: str | None, xtb_symbol: str | None) -> str | None:
    """The ISIN's country prefix, else the country of XTB's exchange suffix."""
    if isin is not None and _ISIN.match(isin):
        return isin[:2]
    if xtb_symbol is not None and "." in xtb_symbol:
        return _XTB_SUFFIX_COUNTRY.get(xtb_symbol.rsplit(".", 1)[1])
    return None


def dividend_tax(
    *, account_type: str | None, country: str | None, observed: Decimal | None
) -> DividendTax:
    """`observed`: the withholding rate this account's own statements gave
    the company's last payment, if any."""
    if account_type in TAX_FREE_ACCOUNTS:
        if country == "PL":
            return DividendTax(Decimal(0), Decimal(0), "rule")
        return _foreign(country, observed, top_up_to=None)
    if account_type == "regular":
        if country == "PL":
            return DividendTax(POLISH_TAX, Decimal(0), "rule")
        return _foreign(country, observed, top_up_to=POLISH_TAX)
    return UNKNOWN_TAX


def _foreign(
    country: str | None, observed: Decimal | None, *, top_up_to: Decimal | None
) -> DividendTax:
    if observed is not None:
        withheld, basis = observed, "statement"
    elif country is not None and country in OBSERVED_WITHHOLDING:
        withheld, basis = OBSERVED_WITHHOLDING[country], "rule"
    else:
        return UNKNOWN_TAX
    top_up = max(top_up_to - withheld, Decimal(0)) if top_up_to is not None else Decimal(0)
    return DividendTax(withheld, top_up, basis)
