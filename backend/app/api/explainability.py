"""Stateless explainability API contract for serialized Product Twins.

The frozen analysis API can mount ``router`` when its release train permits.
Keeping the router independent preserves the established endpoint behaviour.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.twin import ProductDigitalTwin, TwinValidationError
from app.services.reasoning_engine import ReasoningEngine


router = APIRouter(prefix="/api", tags=["explainability"])


class ExplainabilityRequest(BaseModel):
    twin: dict[str, Any]


@router.post("/explain")
def explain_twin(request: ExplainabilityRequest) -> dict[str, Any]:
    """Return evidence, assumptions/gaps, rules, and propagated confidence."""
    try:
        twin = ProductDigitalTwin.from_dict(request.twin)
        reasoning = ReasoningEngine().enrich(twin)
    except (TwinValidationError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"twin": twin.to_dict(), "explainability": reasoning}


__all__ = ["ExplainabilityRequest", "explain_twin", "router"]
