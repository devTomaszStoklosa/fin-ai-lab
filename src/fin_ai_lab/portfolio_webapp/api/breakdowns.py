"""User-defined breakdowns: groups and the assignment of assets to them."""

from uuid import UUID

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from fin_ai_lab.portfolio_webapp import repository
from fin_ai_lab.portfolio_webapp.api.common import (
    get_db,
    require_breakdown,
)
from fin_ai_lab.portfolio_webapp.api.deps import AppDeps
from fin_ai_lab.portfolio_webapp.breakdowns import (
    Breakdown,
    BreakdownError,
    validate_parent,
)
from fin_ai_lab.portfolio_webapp.instruments import Identities, asset_assignments
from fin_ai_lab.portfolio_webapp.instruments_builder import load_link_state
from fin_ai_lab.portfolio_webapp.schemas import (
    AssignmentIn,
    BreakdownCreate,
    BreakdownGroupIn,
    BreakdownGroupOut,
    BreakdownOut,
    BreakdownUpdate,
)


def _require_group(breakdown: Breakdown, group_id: UUID) -> None:
    if all(group.id != group_id for group in breakdown.groups):
        raise HTTPException(status_code=404, detail="Group not found")


def _validate_parent(group_id: UUID | None, parent_id: UUID | None, breakdown: Breakdown) -> None:
    try:
        validate_parent(group_id, parent_id, breakdown.groups)
    except BreakdownError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _identities(connection: duckdb.DuckDBPyConnection) -> Identities:
    return load_link_state(connection).identities


def _to_breakdown_out(breakdown: Breakdown, identities: Identities) -> BreakdownOut:
    # Keyed by asset (S12), the same keys the shares tree uses.
    return BreakdownOut(
        id=breakdown.id,
        name=breakdown.name,
        is_default=breakdown.is_default,
        groups=[
            BreakdownGroupOut(
                id=group.id, name=group.name, parent_id=group.parent_id, position=group.position
            )
            for group in breakdown.groups
        ],
        assignments=asset_assignments(breakdown.assignments, identities),
    )


def build_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/api/breakdowns", response_model=list[BreakdownOut])
    def list_breakdowns(
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> list[BreakdownOut]:
        identities = load_link_state(connection).identities
        return [_to_breakdown_out(b, identities) for b in repository.list_breakdowns(connection)]

    @router.post("/api/breakdowns", response_model=BreakdownOut, status_code=201)
    def create_breakdown(
        payload: BreakdownCreate,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> BreakdownOut:
        return _to_breakdown_out(
            repository.create_breakdown(connection, name=payload.name), _identities(connection)
        )

    @router.put("/api/breakdowns/{breakdown_id}", response_model=BreakdownOut)
    def update_breakdown(
        breakdown_id: UUID,
        payload: BreakdownUpdate,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> BreakdownOut:
        require_breakdown(connection, breakdown_id)
        updated = repository.update_breakdown(
            connection, breakdown_id=breakdown_id, name=payload.name, is_default=payload.is_default
        )
        return _to_breakdown_out(updated, _identities(connection))

    @router.delete("/api/breakdowns/{breakdown_id}", status_code=204)
    def delete_breakdown(
        breakdown_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> None:
        require_breakdown(connection, breakdown_id)
        repository.delete_breakdown(connection, breakdown_id)

    @router.post(
        "/api/breakdowns/{breakdown_id}/duplicate", response_model=BreakdownOut, status_code=201
    )
    def duplicate_breakdown(
        breakdown_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> BreakdownOut:
        source = require_breakdown(connection, breakdown_id)
        name = f"{source.name} (kopia)"[:100]
        duplicated = repository.duplicate_breakdown(connection, source, name=name)
        return _to_breakdown_out(duplicated, _identities(connection))

    @router.post(
        "/api/breakdowns/{breakdown_id}/groups", response_model=BreakdownOut, status_code=201
    )
    def create_breakdown_group(
        breakdown_id: UUID,
        payload: BreakdownGroupIn,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> BreakdownOut:
        breakdown = require_breakdown(connection, breakdown_id)
        _validate_parent(None, payload.parent_id, breakdown)
        repository.create_breakdown_group(
            connection, breakdown_id=breakdown_id, name=payload.name, parent_id=payload.parent_id
        )
        return _to_breakdown_out(
            require_breakdown(connection, breakdown_id), _identities(connection)
        )

    @router.put("/api/breakdowns/{breakdown_id}/groups/{group_id}", response_model=BreakdownOut)
    def update_breakdown_group(
        breakdown_id: UUID,
        group_id: UUID,
        payload: BreakdownGroupIn,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> BreakdownOut:
        breakdown = require_breakdown(connection, breakdown_id)
        _require_group(breakdown, group_id)
        _validate_parent(group_id, payload.parent_id, breakdown)
        repository.update_breakdown_group(
            connection, group_id=group_id, name=payload.name, parent_id=payload.parent_id
        )
        return _to_breakdown_out(
            require_breakdown(connection, breakdown_id), _identities(connection)
        )

    @router.delete("/api/breakdowns/{breakdown_id}/groups/{group_id}", response_model=BreakdownOut)
    def delete_breakdown_group(
        breakdown_id: UUID,
        group_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> BreakdownOut:
        breakdown = require_breakdown(connection, breakdown_id)
        _require_group(breakdown, group_id)
        repository.delete_breakdown_group(connection, breakdown, group_id)
        return _to_breakdown_out(
            require_breakdown(connection, breakdown_id), _identities(connection)
        )

    @router.put("/api/breakdowns/{breakdown_id}/assignments", response_model=BreakdownOut)
    def set_breakdown_assignment(
        breakdown_id: UUID,
        payload: AssignmentIn,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> BreakdownOut:
        breakdown = require_breakdown(connection, breakdown_id)
        if payload.group_id is not None and all(g.id != payload.group_id for g in breakdown.groups):
            raise HTTPException(status_code=422, detail="Grupa nie należy do tego podziału.")
        # Stored under the asset key (S12); the same asset's other member
        # keys lose what they held -- the owner just placed the whole asset.
        identities = _identities(connection)
        asset_key = identities.asset_key(payload.instrument_key)
        repository.set_assignment(
            connection,
            breakdown_id=breakdown_id,
            instrument_key=asset_key,
            group_id=payload.group_id,
            replaces=tuple(k for k in identities.members(asset_key) if k != asset_key),
        )
        return _to_breakdown_out(require_breakdown(connection, breakdown_id), identities)

    return router
