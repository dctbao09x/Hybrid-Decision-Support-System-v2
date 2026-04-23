from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class AdminLoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)


class AdminContext(BaseModel):
    adminId: str
    role: str
    permissions: List[str]


class AdminLoginResponse(BaseModel):
    accessToken: str
    refreshToken: str
    csrfToken: str
    expiresIn: int
    admin: AdminContext
