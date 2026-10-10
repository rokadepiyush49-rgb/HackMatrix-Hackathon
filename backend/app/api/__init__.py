"""Aggregates every API router under /api/v1."""

from fastapi import APIRouter

from app.api import (
    alerts,
    auth,
    bank,
    cases,
    entities,
    governance,
    graph,
    intel,
    live,
    overview,
    packs,
    stream,
    workbench,
)

router = APIRouter()
for module in (auth, overview, alerts, cases, graph, entities, intel, workbench, packs, governance, stream, live, bank):
    router.include_router(module.router)
