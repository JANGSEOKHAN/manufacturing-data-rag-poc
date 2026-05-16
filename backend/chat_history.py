# chat_history.py
# -*- coding: utf-8 -*-
"""
채팅 히스토리 관리
채팅 기록 저장, 조회, 삭제 기능
"""

import json
import time
import logging
from typing import Dict, Any, List
from fastapi import HTTPException

from config import CHAT_HISTORY_FILE

logger = logging.getLogger(__name__)


def load_chat_history() -> Dict[str, Any]:
    """채팅 히스토리 파일에서 로드"""
    if CHAT_HISTORY_FILE.exists():
        try:
            with open(CHAT_HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"채팅 히스토리 로드 실패: {e}")
            return {"history": [], "chats": {}}
    return {"history": [], "chats": {}}


def save_chat_history(data: Dict[str, Any]):
    """채팅 히스토리 파일에 저장"""
    try:
        with open(CHAT_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"채팅 히스토리 저장 실패: {e}")
        raise HTTPException(500, f"채팅 히스토리 저장 실패: {str(e)}")


def get_chat_history_list() -> List[Dict[str, Any]]:
    """채팅 히스토리 목록 조회"""
    data = load_chat_history()
    return data.get("history", [])


def get_chat_messages(chat_id: int) -> List[Dict[str, Any]]:
    """특정 채팅의 메시지 조회"""
    data = load_chat_history()
    if str(chat_id) in data.get("chats", {}):
        return data["chats"][str(chat_id)]
    return []


def save_chat(chat_id: int, title: str, messages: List[Dict[str, Any]], timestamp: str = None):
    """채팅 히스토리 저장"""
    data = load_chat_history()
    
    # 히스토리 목록 업데이트
    history = data.get("history", [])
    # 기존 항목 제거 (같은 ID가 있으면)
    history = [h for h in history if h.get("id") != chat_id]
    # 새 항목을 맨 앞에 추가
    history.insert(0, {
        "id": chat_id,
        "title": title,
        "timestamp": timestamp or time.strftime("%Y-%m-%dT%H:%M:%S")
    })
    # 최대 10개만 유지
    data["history"] = history[:10]
    
    # 채팅 메시지 저장
    if "chats" not in data:
        data["chats"] = {}
    data["chats"][str(chat_id)] = messages
    
    save_chat_history(data)
    return {"success": True, "chat_id": chat_id}


def delete_chat(chat_id: int):
    """채팅 히스토리 삭제"""
    data = load_chat_history()
    
    # 히스토리 목록에서 제거
    data["history"] = [h for h in data.get("history", []) if h.get("id") != chat_id]
    # 채팅 메시지에서 제거
    if str(chat_id) in data.get("chats", {}):
        del data["chats"][str(chat_id)]
    save_chat_history(data)
    return {"success": True}


def clear_all_chat_history():
    """모든 채팅 히스토리 삭제"""
    data = {"history": [], "chats": {}}
    save_chat_history(data)
    return {"success": True}

