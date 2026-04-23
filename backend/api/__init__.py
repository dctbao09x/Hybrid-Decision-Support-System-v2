"""
API package for modular routers.

Imports are lazy to avoid heavy dependency loading at module init time.
Use direct imports when needed:
    from backend.api.kb_routes import router as kb_router
    from backend.api.analyze import router as analyze_router
    etc.
"""

__all__ = [
    "kb_routes",
    "analyze",
    "recommendations",
    "chat",
    "career_library",
]
