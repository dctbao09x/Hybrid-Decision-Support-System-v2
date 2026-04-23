# backend/api/routers/__init__.py
"""
API Routers
===========

FastAPI routers for the unified API Gateway.

All routers are mounted under /api/v1/* prefix:
  - /api/v1/health/*      — Health checks
  - /api/v1/ops/*         — Operations
  - /api/v1/governance/*  — Governance (SLA, Risk, Reports)
  - /api/v1/ml/*          — ML operations  
  - /api/v1/infer/*       — Inference
  - /api/v1/explain/*     — Explanations
  - /api/v1/pipeline/*    — Data pipeline
  - /api/v1/crawlers/*    — Crawlers
  - /api/v1/kb/*          — Knowledge base
  - /api/v1/chat/*        — Chat
"""

from backend.api.routers.explain_router import (
    router as explain_router,
    router_v2 as explain_router_v2,
    ExplainRequest,
    ExplainResponse,
)
from backend.api.routers.health_router import router as health_router
from backend.api.routers.ops_router import router as ops_router
from backend.api.routers.governance_router import router as governance_router
from backend.api.routers.ml_router import router as ml_router
from backend.api.routers.mlops_router import router as mlops_router
from backend.api.routers.infer_router import router as infer_router
from backend.api.routers.pipeline_router import router as pipeline_router
from backend.api.routers.crawler_router import router as crawler_router
from backend.api.routers.chat_router import router as chat_router

__all__ = [
    # Routers
    "explain_router",
    "explain_router_v2",
    "health_router",
    "ops_router",
    "governance_router",
    "ml_router",
    "mlops_router",
    "infer_router",
    "pipeline_router",
    "crawler_router",
    "chat_router",
    # Models
    "ExplainRequest",
    "ExplainResponse",
]
