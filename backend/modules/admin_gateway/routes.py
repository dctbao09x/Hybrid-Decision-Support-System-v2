from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.modules.admin_auth.middleware import auth_admin
from backend.modules.feedback.routes import admin_feedback_router
from backend.modules.admin_gateway.system_routes import admin_system_router


admin_gateway_router = APIRouter(prefix="/api/admin", tags=["Admin Gateway"], dependencies=[Depends(auth_admin)])

admin_gateway_router.include_router(admin_feedback_router)
admin_gateway_router.include_router(admin_system_router)
