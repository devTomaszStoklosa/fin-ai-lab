"""Instrument identity across brokers (portfolio-webapp-S12): which of the
instruments held in different accounts are one and the same asset.

Each broker names an instrument its own way -- Bossa by ISIN, XTB by its own
symbol ("ATR.PL", its export has no ISIN at all) -- so the per-broker
instrument key (REQ-065) splits one company into two assets. This module
joins them back:

- automatically, when both resolved to the same FIGI at import (OpenFIGI's
  identifier of one listing: the same FIGI *is* the same instrument);
- by the owner's own decision ("to ten sam instrument" / "to różne"), for
  everything the data alone can't settle -- `suggest` lists the likely pairs
  for the owner to confirm, it never joins anything by itself.

Every asset is then known by one key (its "asset key"): breakdowns, shares
and the all-portfolios list use it instead of the per-broker key.

Pure computation -- no database, no network.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import combinations
from typing import Literal
from uuid import UUID

LinkReason = Literal["figi", "owner"]

# A name-only match must also agree on price: two ETFs tracking different
# indices share most of their name ("iShares Core MSCI World/EM").
NAME_MATCH_PRICE_TOLERANCE = Decimal("0.10")
# Beyond this the two cannot be one instrument priced in PLN on the same day
# -- a shared ticker on two exchanges is then two different companies.
MAX_PRICE_DIFFERENCE = Decimal("0.25")
MIN_NAME_LENGTH = 4
MIN_TOKEN_OVERLAP = Decimal("0.6")

# Words that name a legal form, a fund wrapper or a share-class currency,
# not the issuer -- dropped before comparing names.
# fmt: off
_NOISE_WORDS = {
    "SA", "S", "A", "SPOLKA", "AKCYJNA", "INC", "PLC", "AG", "NV", "SE", "ASA",
    "AB", "CORP", "CORPORATION", "LTD", "LIMITED", "CO", "HOLDING", "HOLDINGS",
    "GROUP", "THE", "UCITS", "ETF", "FUND", "ACC", "DIST", "USD", "EUR", "PLN",
    "GBP",
}
# fmt: on
# NFKD leaves these letters whole (they are not a base letter plus a mark).
_NON_DECOMPOSING = str.maketrans({"Ł": "L", "ł": "l", "Ø": "O", "ø": "o", "ß": "ss"})


@dataclass(frozen=True)
class BrokerInstrument:
    """One instrument as one broker records it -- the unit identity joins."""

    key: str  # per-broker instrument key (REQ-065), or manual:{position id}
    broker: str
    name: str
    isin: str | None = None
    symbol: str | None = None
    figi: str | None = None
    ticker: str | None = None
    exchange_code: str | None = None

    @property
    def is_manual(self) -> bool:
        return self.key.startswith("manual:")


@dataclass(frozen=True)
class Decision:
    """The owner's answer for one pair: the same instrument, or not."""

    key_a: str
    key_b: str
    same: bool


@dataclass(frozen=True)
class Suggestion:
    key_a: str
    key_b: str
    reasons: list[str]
    score: int


@dataclass
class Identities:
    """Every held instrument's asset key, and how it got joined."""

    asset_keys: dict[str, str] = field(default_factory=dict)
    linked_by: dict[str, LinkReason] = field(default_factory=dict)

    def asset_key(self, key: str) -> str:
        # An instrument no longer held keeps its own key -- nothing to join.
        return self.asset_keys.get(key, key)

    def members(self, asset_key: str) -> list[str]:
        members = [k for k, a in self.asset_keys.items() if a == asset_key]
        return members or [asset_key]


def pair(key_a: str, key_b: str) -> tuple[str, str]:
    return (key_a, key_b) if key_a <= key_b else (key_b, key_a)


def resolve(instruments: Iterable[BrokerInstrument], decisions: list[Decision]) -> Identities:
    """REQ-090/091: joins instruments with the same FIGI unless the owner
    said they differ, and every pair the owner said is the same; joining is
    transitive. The asset key is the ISIN when any member has one (the
    broker-independent identifier), else the member's own key."""
    by_key = {i.key: i for i in instruments}
    different = {pair(d.key_a, d.key_b) for d in decisions if not d.same}

    edges: dict[tuple[str, str], LinkReason] = {}
    by_figi: dict[str, list[str]] = {}
    for instrument in by_key.values():
        if instrument.figi and not instrument.is_manual:
            by_figi.setdefault(instrument.figi, []).append(instrument.key)
    for keys in by_figi.values():
        for key_a, key_b in combinations(sorted(keys), 2):
            if (key_a, key_b) not in different:
                edges[(key_a, key_b)] = "figi"
    for decision in decisions:
        if decision.same and decision.key_a in by_key and decision.key_b in by_key:
            edges[pair(decision.key_a, decision.key_b)] = "owner"

    parent = {key: key for key in by_key}

    def root(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for key_a, key_b in edges:
        parent[root(key_a)] = root(key_b)

    components: dict[str, list[str]] = {}
    for key in by_key:
        components.setdefault(root(key), []).append(key)

    identities = Identities()
    for members in components.values():
        asset_key = min(members, key=lambda k: _asset_key_rank(by_key[k]))
        for key in members:
            identities.asset_keys[key] = asset_key
    for (key_a, key_b), reason in edges.items():
        for key in (key_a, key_b):
            # An owner's decision is the stronger statement -- it wins the label.
            if identities.linked_by.get(key) != "owner":
                identities.linked_by[key] = reason
    return identities


def suggest(
    instruments: Iterable[BrokerInstrument],
    identities: Identities,
    decisions: list[Decision],
    unit_values: dict[str, Decimal],
) -> list[Suggestion]:
    """REQ-092: pairs from different brokers that are likely one instrument
    but not joined yet -- shared ticker or symbol, or a matching name at a
    matching price. `unit_values` is today's value of one unit in PLN per
    key, where known. Strongest evidence first."""
    candidates = [i for i in instruments if not i.is_manual]
    decided = {pair(d.key_a, d.key_b) for d in decisions}
    suggestions = []
    for a, b in combinations(sorted(candidates, key=lambda i: i.key), 2):
        if a.broker == b.broker or pair(a.key, b.key) in decided:
            continue
        if identities.asset_key(a.key) == identities.asset_key(b.key):
            continue
        suggestion = _compare(a, b, unit_values.get(a.key), unit_values.get(b.key))
        if suggestion is not None:
            suggestions.append(suggestion)
    return sorted(suggestions, key=lambda s: (-s.score, s.key_a, s.key_b))


def asset_assignments(assignments: dict[str, UUID], identities: Identities) -> dict[str, UUID]:
    """A breakdown's assignments keyed by asset. An assignment stored under
    the asset key itself wins over one stored under a member's own key (the
    owner set it after the join); otherwise the first member's, in key
    order -- deterministic whichever broker came first."""
    result: dict[str, UUID] = {}
    ordered = sorted(
        assignments.items(), key=lambda item: (identities.asset_key(item[0]) != item[0], item[0])
    )
    for key, group_id in ordered:
        result.setdefault(identities.asset_key(key), group_id)
    return result


def display_name(names: list[str]) -> str:
    """The asset's name from its members' names: a mixed-case one ("Atrem")
    reads better than a broker's all-caps short code ("ATREM")."""
    return next((n for n in names if n != n.upper()), names[0])


def compact_name(name: str) -> str:
    return "".join(_name_tokens(name))


def _compare(
    a: BrokerInstrument, b: BrokerInstrument, price_a: Decimal | None, price_b: Decimal | None
) -> Suggestion | None:
    reasons: list[str] = []
    score = 0

    shared_ticker = _shared_code(a, b)
    if shared_ticker is not None:
        reasons.append(f"ten sam ticker {shared_ticker}")
        score += 3

    name_a, name_b = compact_name(a.name), compact_name(b.name)
    name_match = False
    if len(name_a) >= MIN_NAME_LENGTH and len(name_b) >= MIN_NAME_LENGTH:
        if name_a == name_b:
            reasons.append("ta sama nazwa")
            score, name_match = score + 2, True
        elif name_a in name_b or name_b in name_a or _token_overlap(a.name, b.name):
            reasons.append("podobna nazwa")
            score, name_match = score + 1, True

    if not shared_ticker and not name_match:
        return None

    difference = _relative_difference(price_a, price_b)
    if difference is not None:
        if difference > MAX_PRICE_DIFFERENCE:
            return None
        if difference <= NAME_MATCH_PRICE_TOLERANCE:
            reasons.append("podobna cena za sztukę")
            score += 1
        elif not shared_ticker:
            return None

    key_a, key_b = pair(a.key, b.key)
    return Suggestion(key_a=key_a, key_b=key_b, reasons=reasons, score=score)


def _shared_code(a: BrokerInstrument, b: BrokerInstrument) -> str | None:
    """A ticker both brokers agree on -- OpenFIGI's ticker, or a broker's
    own symbol without its market suffix ("ATR.PL" -> "ATR")."""
    codes_a, codes_b = _codes(a), _codes(b)
    shared = sorted(codes_a & codes_b)
    return shared[0] if shared else None


def _codes(instrument: BrokerInstrument) -> set[str]:
    codes = set()
    if instrument.ticker:
        codes.add(instrument.ticker.upper())
    if instrument.symbol:
        base, dot, _suffix = instrument.symbol.upper().rpartition(".")
        codes.add(base if dot and base else instrument.symbol.upper())
    # A one- or two-letter code is too common across markets to mean much.
    return {code for code in codes if len(code) >= 3}


def _token_overlap(name_a: str, name_b: str) -> bool:
    tokens_a, tokens_b = set(_name_tokens(name_a)), set(_name_tokens(name_b))
    if len(tokens_a) < 2 or len(tokens_b) < 2:
        return False
    overlap = Decimal(len(tokens_a & tokens_b)) / Decimal(len(tokens_a | tokens_b))
    return overlap >= MIN_TOKEN_OVERLAP


def _name_tokens(name: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", name.translate(_NON_DECOMPOSING))
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch)).upper()
    return [word for word in re.findall(r"[A-Z0-9]+", plain) if word not in _NOISE_WORDS]


def _relative_difference(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    if a is None or b is None or a <= 0 or b <= 0:
        return None
    return abs(a - b) / max(a, b)


def _asset_key_rank(instrument: BrokerInstrument) -> tuple[bool, bool, str]:
    keyed_by_isin = instrument.isin is not None and instrument.key == instrument.isin
    return (not keyed_by_isin, instrument.is_manual, instrument.key)
