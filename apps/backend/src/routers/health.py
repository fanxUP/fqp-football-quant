"""Health check and root endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok", "service": "fqp-from-scratch"}


@router.get("/")
def root():
    return {"name": "FQP From Scratch", "boundary": "analysis_simulation_review_only"}
