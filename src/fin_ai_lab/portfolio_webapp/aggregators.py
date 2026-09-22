from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from fin_ai_lab.portfolio_xray.canonical import Position


class Aggregator(BaseModel):
    id: UUID
    portfolio_id: UUID
    name: str
    member_instrument_keys: list[str]
    member_aggregator_ids: list[UUID]


class CycleError(Exception):
    pass


def instrument_key(position: Position) -> str:
    # REQ-065: stable across re-imports, unlike a position row's per-snapshot
    # id. ISIN when the instrument has one; otherwise broker:symbol, the
    # pair the spec names. A manual position can lack both, so this falls
    # back once more to broker:instrument_name -- not in the spec's own
    # two-level rule, but instrument_name is the only field canonical.Position
    # always has.
    if position.isin is not None:
        return position.isin
    if position.symbol is not None:
        return f"{position.broker}:{position.symbol}"
    return f"{position.broker}:{position.instrument_name}"


def validate_no_cycle(
    target_id: UUID,
    proposed_member_aggregator_ids: list[UUID],
    all_by_id: dict[UUID, Aggregator],
) -> None:
    # REQ-062: reject a proposed member that already contains the target,
    # directly or through its own nested aggregators -- adding it would let
    # the target reach itself by walking down through that member.
    for member_id in proposed_member_aggregator_ids:
        if _reaches(member_id, target_id, all_by_id, seen=set()):
            raise CycleError(
                f"Aggregator {member_id} already contains this aggregator "
                "(directly or through nesting) -- would create a cycle"
            )


def _reaches(
    from_id: UUID, target_id: UUID, all_by_id: dict[UUID, Aggregator], *, seen: set[UUID]
) -> bool:
    if from_id == target_id:
        return True
    if from_id in seen:
        return False  # a cycle already present in stored data -- don't loop forever
    seen.add(from_id)
    aggregator = all_by_id.get(from_id)
    if aggregator is None:
        return False
    return any(
        _reaches(child_id, target_id, all_by_id, seen=seen)
        for child_id in aggregator.member_aggregator_ids
    )


def resolve_value(
    aggregator: Aggregator,
    all_by_id: dict[UUID, Aggregator],
    values_by_instrument_key: dict[str, Decimal],
) -> Decimal:
    # REQ-061: an instrument reachable through more than one path (direct
    # member of this aggregator AND of a nested one) is counted once -- the
    # set dedups by construction.
    keys = _collect_instrument_keys(aggregator.id, all_by_id, seen=set())
    return sum((values_by_instrument_key.get(key, Decimal(0)) for key in keys), Decimal(0))


def _collect_instrument_keys(
    aggregator_id: UUID, all_by_id: dict[UUID, Aggregator], *, seen: set[UUID]
) -> set[str]:
    if aggregator_id in seen:
        return set()
    seen.add(aggregator_id)
    aggregator = all_by_id.get(aggregator_id)
    if aggregator is None:
        return set()
    keys = set(aggregator.member_instrument_keys)
    for child_id in aggregator.member_aggregator_ids:
        keys |= _collect_instrument_keys(child_id, all_by_id, seen=seen)
    return keys


def top_level_ids(all_aggregators: list[Aggregator]) -> set[UUID]:
    # Roots of the forest: an aggregator that is itself a member of another
    # one (REQ-063 allows that) still renders nested under that parent, so
    # it does not also get its own top-level card.
    referenced = {member_id for agg in all_aggregators for member_id in agg.member_aggregator_ids}
    return {agg.id for agg in all_aggregators if agg.id not in referenced}
