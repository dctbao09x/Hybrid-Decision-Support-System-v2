# backend/api/routers/chat_router.py
"""
Chat Router (Consolidated)
==========================

All chat endpoints consolidated under /api/v1/chat/*

Endpoints:
  - POST /api/v1/chat    — Send chat message
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger("api.routers.chat")

router = APIRouter(tags=["Chat"])


# ==============================================================================
# Request/Response Models
# ==============================================================================

class ChatMessage(BaseModel):
    """Chat message."""
    role: str = Field(..., description="Message role (user/assistant)")
    text: str = Field(..., description="Message text")


class ChatRequest(BaseModel):
    """Chat request."""
    message: str = Field(..., description="User message")
    chatHistory: Optional[List[ChatMessage]] = Field(None, description="Previous chat history")


class ChatResponse(BaseModel):
    """Chat response."""
    reply: str = Field(..., description="Assistant reply")


# ==============================================================================
# Routes
# ==============================================================================

@router.post(
    "",
    response_model=ChatResponse,
    summary="Send chat message",
    description="Send a message and get AI assistant reply",
)
def chat(request: ChatRequest):
    """Process chat message and return AI response."""
    history = request.chatHistory or []
    last_topic = None
    
    for msg in reversed(history):
        if msg.role == "user" and msg.text:
            last_topic = msg.text.strip().lower()
            break

    text = request.message.strip().lower()
    if not text and last_topic:
        text = last_topic

    if not text:
        return ChatResponse(reply="Bạn có thể chia sẻ thêm không?")

    combined_text = f"{text} {last_topic or ''}".strip()

    if "AI" in combined_text or "trí tuệ nhân tạo" in combined_text or "machine learning" in combined_text:
        reply = "AI/ML là mảng rất tiềm năng. Bạn đã có nền tảng lập trình nào chưa?"
    elif "thiết kế" in combined_text or "design" in combined_text or "ui" in combined_text:
        reply = "Thiết kế là mảng sáng tạo. Bạn quan tâm UI/UX hay graphic?"
    elif "data" in combined_text or "dữ liệu" in combined_text:
        reply = "Data là mảng có nhiều cơ hội. Bạn thích phân tích hay xây hệ thống dữ liệu?"
    elif "backend" in combined_text or "server" in combined_text:
        reply = "Backend cần nền tảng về API và database. Bạn đã dùng ngôn ngữ nào?"
    else:
        reply = "Cảm ơn bạn đã chia sẻ. Bạn có thể nói rõ hơn về mục tiêu nghề nghiệp không?"

    return ChatResponse(reply=reply)
