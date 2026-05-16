# text_utils.py
# -*- coding: utf-8 -*-
"""
Pydantic 모델 정의
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel


# ============================================================
# Pydantic 모델 정의
# ============================================================

class Question(BaseModel):
    """질문 요청 바디 (k는 가져올 문서 수)"""
    question: str
    k: Optional[int] = 5


class ChatHistoryItem(BaseModel):
    """채팅 히스토리 아이템"""
    id: int
    title: str
    timestamp: str


class ChatSaveRequest(BaseModel):
    """채팅 저장 요청"""
    chat_id: int
    title: str
    messages: List[Dict[str, Any]]
    timestamp: Optional[str] = None


class FileInfo(BaseModel):
    """파일 정보"""
    filename: str
    size: int
    upload_date: Optional[str] = None
    status: Optional[str] = None


class UploadStatusResponse(BaseModel):
    """업로드 상태 응답"""
    status: str
    message: str
    progress: int


class AskResponse(BaseModel):
    """질문 응답"""
    answer: str
    sources: Optional[List[Dict[str, Any]]] = None
    images: Optional[List[str]] = None

