"""
Chat router (simple AI consult).
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List


router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    text: str


class ChatRequest(BaseModel):
    message: str
    chatHistory: Optional[List[ChatMessage]] = None


class ChatResponse(BaseModel):
    reply: str


@router.post("/", response_model=ChatResponse)
def chat(request: ChatRequest):
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
