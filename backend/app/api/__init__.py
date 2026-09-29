"""Aggregates every API router under /api/v1."""

from fastapi import APIRouter

from app.api import (
    alerts,
    auth,
    cases,
    entities,
    governance,
    graph,
    intel,
    overview,
    packs,
    stream,
    workbench,
)

router = APIRouter()
for module in (auth, overview, alerts, cases, graph, entities, intel, workbench, packs, governance, stream):
    router.include_router(module.router)
