from decimal import Decimal
from uuid import uuid4

from fin_ai_lab.portfolio_webapp.instruments import (
    BrokerInstrument,
    Decision,
    asset_assignments,
    compact_name,
    display_name,
    resolve,
    suggest,
)

D = Decimal
ATR_ISIN = "PLATREM00017"


def _xtb(symbol: str, name: str, **kwargs) -> BrokerInstrument:
    return BrokerInstrument(key=f"xtb:{symbol}", broker="xtb", name=name, symbol=symbol, **kwargs)


def _bossa(isin: str, name: str, **kwargs) -> BrokerInstrument:
    return BrokerInstrument(key=isin, broker="bossa", name=name, isin=isin, **kwargs)


XTB_ATR = _xtb("ATR.PL", "Atrem")
BOSSA_ATR = _bossa(ATR_ISIN, "ATREM")


# --- resolve (REQ-090/091) -------------------------------------------------------


def test_same_figi_is_one_asset_under_its_isin() -> None:
    xtb = _xtb("ATR.PL", "Atrem", figi="BBG000ATR")
    bossa = _bossa(ATR_ISIN, "ATREM", figi="BBG000ATR")

    identities = resolve([xtb, bossa], [])

    assert identities.asset_key(xtb.key) == ATR_ISIN
    assert identities.asset_key(bossa.key) == ATR_ISIN
    assert identities.linked_by == {xtb.key: "figi", ATR_ISIN: "figi"}
    assert sorted(identities.members(ATR_ISIN)) == sorted([xtb.key, ATR_ISIN])


def test_owner_saying_different_overrides_a_shared_figi() -> None:
    xtb = _xtb("ATR.PL", "Atrem", figi="BBG000ATR")
    bossa = _bossa(ATR_ISIN, "ATREM", figi="BBG000ATR")

    identities = resolve([xtb, bossa], [Decision(ATR_ISIN, xtb.key, same=False)])

    assert identities.asset_key(xtb.key) == xtb.key
    assert identities.linked_by == {}


def test_owner_decisions_join_transitively() -> None:
    other = _xtb("ATRX.PL", "Atrem bis")
    decisions = [Decision(XTB_ATR.key, ATR_ISIN, same=True), Decision(other.key, XTB_ATR.key, True)]

    identities = resolve([XTB_ATR, BOSSA_ATR, other], decisions)

    assert {identities.asset_key(k) for k in (XTB_ATR.key, ATR_ISIN, other.key)} == {ATR_ISIN}
    assert identities.linked_by[other.key] == "owner"


def test_without_an_isin_the_asset_key_is_an_imported_members_own() -> None:
    manual = BrokerInstrument(key="manual:1", broker="manual", name="Atrem")

    identities = resolve([manual, XTB_ATR], [Decision("manual:1", XTB_ATR.key, same=True)])

    assert identities.asset_key("manual:1") == XTB_ATR.key


def test_decision_about_an_instrument_no_longer_held_is_ignored() -> None:
    identities = resolve([XTB_ATR], [Decision(XTB_ATR.key, "PLGONE000001", same=True)])

    assert identities.asset_key(XTB_ATR.key) == XTB_ATR.key
    assert identities.asset_key("PLGONE000001") == "PLGONE000001"


# --- suggest (REQ-092) -----------------------------------------------------------


def test_same_name_and_price_across_brokers_is_suggested() -> None:
    identities = resolve([XTB_ATR, BOSSA_ATR], [])

    (suggestion,) = suggest(
        [XTB_ATR, BOSSA_ATR], identities, [], {XTB_ATR.key: D("53.30"), ATR_ISIN: D("53.10")}
    )

    assert (suggestion.key_a, suggestion.key_b) == (ATR_ISIN, XTB_ATR.key)
    assert suggestion.reasons == ["ta sama nazwa", "podobna cena za sztukę"]


def test_symbol_matching_the_other_brokers_ticker_is_suggested() -> None:
    bossa = _bossa(ATR_ISIN, "ATREM SPÓŁKA AKCYJNA", ticker="ATR", exchange_code="PW")

    (suggestion,) = suggest([XTB_ATR, bossa], resolve([XTB_ATR, bossa], []), [], {})

    assert suggestion.reasons[0] == "ten sam ticker ATR"


def test_similar_names_at_different_prices_are_not_suggested() -> None:
    world = _xtb("SWDA.UK", "iShares Core MSCI World")
    emerging = _bossa("IE00BKM4GZ66", "iShares Core MSCI EM")
    instruments = [world, emerging]
    identities = resolve(instruments, [])

    at_same_price = suggest(instruments, identities, [], {world.key: D(100), emerging.key: D(98)})
    at_other_price = suggest(instruments, identities, [], {world.key: D(450), emerging.key: D(150)})

    assert [s.reasons for s in at_same_price] == [["podobna nazwa", "podobna cena za sztukę"]]
    assert at_other_price == []


def test_shared_ticker_at_a_far_price_is_two_companies() -> None:
    pl = _bossa("PLBSK0000017", "ING BSK", ticker="ING", exchange_code="PW")
    nl = _xtb("ING.NL", "ING Groep")

    assert suggest([pl, nl], resolve([pl, nl], []), [], {pl.key: D(290), nl.key: D(85)}) == []


def test_answered_joined_same_broker_and_manual_pairs_are_not_suggested() -> None:
    manual = BrokerInstrument(key="manual:1", broker="manual", name="Atrem")
    xtb_twin = _xtb("ATR.US", "Atrem")
    instruments = [XTB_ATR, BOSSA_ATR, manual, xtb_twin]
    answered = [Decision(ATR_ISIN, XTB_ATR.key, same=False)]

    suggestions = suggest(instruments, resolve(instruments, answered), answered, {})

    # Only Bossa <-> the other XTB listing is left: the answered pair is
    # settled, XTB's two listings are one broker's own call, manual never.
    assert [(s.key_a, s.key_b) for s in suggestions] == [(ATR_ISIN, "xtb:ATR.US")]
    joined = [Decision(ATR_ISIN, "xtb:ATR.US", same=True)]
    assert suggest(instruments, resolve(instruments, joined), joined, {}) != []  # XTB_ATR left
    all_joined = joined + [Decision(ATR_ISIN, XTB_ATR.key, same=True)]
    assert suggest(instruments, resolve(instruments, all_joined), all_joined, {}) == []


# --- assignments and names -------------------------------------------------------


def test_assignment_under_the_asset_key_wins_over_a_members_own() -> None:
    identities = resolve([XTB_ATR, BOSSA_ATR], [Decision(ATR_ISIN, XTB_ATR.key, same=True)])
    stocks, other = uuid4(), uuid4()

    from_member = asset_assignments({XTB_ATR.key: stocks}, identities)
    both = asset_assignments({XTB_ATR.key: stocks, ATR_ISIN: other}, identities)

    assert from_member == {ATR_ISIN: stocks}
    assert both == {ATR_ISIN: other}


def test_display_name_prefers_mixed_case() -> None:
    assert display_name(["ATREM", "Atrem"]) == "Atrem"
    assert display_name(["ATREM"]) == "ATREM"


def test_names_compare_without_legal_form_diacritics_or_spacing() -> None:
    assert compact_name("Śnieżka SA") == compact_name("SNIEZKA")
    assert compact_name("CD Projekt S.A.") == compact_name("CDPROJEKT")
    assert compact_name("Łódź Holding") == "LODZ"
