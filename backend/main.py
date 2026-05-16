# main.py
# -*- coding: utf-8 -*-
"""
RAG API 메인 애플리케이션
FastAPI 앱 및 엔드포인트 정의
"""

import os
import re
import time
import json
import shutil
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Optional
from urllib.parse import unquote

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, File, UploadFile, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import logging

# ==========================================================
# 로깅 설정 (MinerU 및 이미지 요약 로그만 표시)
# ==========================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:     %(message)s',
    handlers=[logging.StreamHandler()]
)

# 불필요한 로거 숨김
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("vector_store").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

# MinerU 및 파일 처리 로거만 INFO 레벨 유지
logging.getLogger("config").setLevel(logging.INFO)
logging.getLogger("file_handler").setLevel(logging.INFO)

# Logger 초기화
logger = logging.getLogger(__name__)

# 모듈 임포트
from config import (
    HOST_INPUT_DIR, HOST_OUTPUT_DIR, CHAT_HISTORY_FILE
)
from text_utils import Question, ChatSaveRequest, ChatHistoryItem
from vector_store import (
    get_vectorstore, save_vectorstore, reset_vectorstore, delete_qdrant_collection,
    get_llm, get_embeddings, delete_documents_by_file
)
from file_handler import (
    process_upload_file, get_upload_status, get_embedded_files, 
    _EMBEDDED_FILES, _UPLOAD_STATUS, rebuild_vectorstore_from_existing_files
)
from chat_history import (
    load_chat_history as _load_chat_history,
    save_chat_history as _save_chat_history,
    get_chat_history_list,
    get_chat_messages as _get_chat_messages,
    save_chat as _save_chat,
    delete_chat as _delete_chat
)
from rag_query_handler import rag_query as rag_query_handler

try:
    from langchain_core.documents import Document
except ImportError:
    Document = None


# ==========================================================
# 로깅 필터 설정 (정적 파일 요청 로그 제거)
# ==========================================================
class StaticFileLogFilter(logging.Filter):
    """정적 파일 요청 로그를 필터링"""
    def filter(self, record):
        # 로그 메시지에서 정적 파일 경로 확인
        message = record.getMessage()
        # /static/ 또는 /input/ 경로는 로깅하지 않음
        if "/static/" in message or "/input/" in message:
            return False
        return True

# uvicorn access logger에 필터 추가
uvicorn_access_logger = logging.getLogger("uvicorn.access")
uvicorn_access_logger.addFilter(StaticFileLogFilter())


# ==========================================================
# FastAPI 앱 생성
# ==========================================================
app = FastAPI(title="RAG API (md → inline html → vector)")

cors_origins_str = os.getenv("CORS_ORIGINS")
if not cors_origins_str:
    raise ValueError("CORS_ORIGINS 환경 변수가 설정되지 않았습니다. .env 파일을 확인하세요.")
cors_origins = cors_origins_str.split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 서버 종료 시 MinerU 컨테이너 자동 중지
@app.on_event("shutdown")
async def shutdown_event():
    """서버 종료 시 MinerU 컨테이너 중지"""
    try:
        from config import stop_container, MINERU_CONTAINER
        logger.info(f"서버 종료 중... {MINERU_CONTAINER} 컨테이너 중지 시도")
        stop_container(MINERU_CONTAINER)
        logger.info(f"{MINERU_CONTAINER} 컨테이너 중지 완료")
    except Exception as e:
        logger.warning(f"컨테이너 중지 실패 (무시됨): {e}")

app.mount("/static", StaticFiles(directory=str(HOST_OUTPUT_DIR)), name="static")
app.mount("/input", StaticFiles(directory=str(HOST_INPUT_DIR)), name="input")
try:
    import sys
    from pathlib import Path
    # 현재 파일의 디렉토리를 Python 경로에 추가
    current_dir = Path(__file__).parent
    if str(current_dir) not in sys.path:
        sys.path.insert(0, str(current_dir))
    
    from admin_api import get_admin_api_router
    admin_api_router = get_admin_api_router(get_vectorstore, HOST_OUTPUT_DIR)
    app.include_router(admin_api_router)
except Exception:
    pass


# ==========================================================
# 업로드 엔드포인트
# ==========================================================
@app.post("/upload_file")
async def upload_file(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    filename = file.filename
    host_input_path = HOST_INPUT_DIR / filename
    host_input_path.write_bytes(await file.read())
    logger.info(f"업로드 완료: {filename}")
    
    # 백그라운드에서 처리 시작
    background_tasks.add_task(process_upload_file, filename)
    
    return {
        "status": "accepted",
        "message": f"{filename} 업로드 완료. 처리 중...",
        "filename": filename,
        "upload_status_url": f"/upload_status/{filename}"
    }


@app.get("/upload_status/{filename}")
def upload_status(filename: str):
    """업로드 처리 상태 조회"""
    return get_upload_status(filename)


# ==========================================================
# RAG 질의 엔드포인트
# ==========================================================
@app.post("/rag_query")
def rag_query(req: Question):
    try:
        return rag_query_handler(req)
    except HTTPException:
        # HTTPException은 그대로 전달
        raise
    except Exception as e:
        # 예상치 못한 오류 처리
        logger.error(f"RAG 쿼리 처리 중 예상치 못한 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"질의 처리 중 오류가 발생했습니다: {str(e)}"
        )


# ==========================================================
# HTML 뷰 엔드포인트
# ==========================================================
@app.get("/view_html/{filename:path}", response_class=HTMLResponse)
def view_html(filename: str):
    decoded_filename = unquote(filename)
    original_stem = Path(decoded_filename).stem
    base = HOST_OUTPUT_DIR / original_stem

    # OCR 폴더에서 HTML 파일 찾기
    ocr_dir = base / "ocr"
    if ocr_dir.exists():
        ocr_html_files = list(ocr_dir.glob("*.html"))
        if ocr_html_files:
            return HTMLResponse(
                content=ocr_html_files[0].read_text(encoding="utf-8", errors="ignore")
            )

    # VLM 폴더에서 HTML 파일 찾기
    vlm_dir = base / "vlm"
    if vlm_dir.exists():
        vlm_html_files = list(vlm_dir.glob("*.html"))
        if vlm_html_files:
            return HTMLResponse(
                content=vlm_html_files[0].read_text(encoding="utf-8", errors="ignore")
            )

    raise HTTPException(404, f"HTML 파일을 찾을 수 없습니다. (검색 경로: {base})")


# ==========================================================
# 상태 조회 엔드포인트
# ==========================================================
@app.get("/status")
def status():
    from vector_store import get_document_count, get_all_filenames
    
    vs = get_vectorstore()
    try:
        # Qdrant는 docstore가 없으므로 다른 방식으로 조회
        if hasattr(vs, 'client') and hasattr(vs, 'collection_name'):
            # Qdrant 방식
            total_docs = get_document_count()
            all_filenames = get_all_filenames()
            
            # 파일별 청크 수 계산
            files: Dict[str, int] = {}
            try:
                from qdrant_client.http.models import Filter, FieldCondition, MatchValue
                
                for filename in all_filenames:
                    filter_condition = Filter(
                        must=[
                            FieldCondition(
                                key="file",  # LangChain Qdrant는 payload에 직접 저장
                                match=MatchValue(value=filename)
                            )
                        ]
                    )
                    scroll_result = vs.client.scroll(
                        collection_name=vs.collection_name,
                        scroll_filter=filter_condition,
                        limit=10000,
                        with_payload=True,
                        with_vectors=False
                    )
                    # 모든 청크 카운트 (type 필터링 제거, 모든 청크 포함)
                    chunk_count = len(scroll_result[0])
                    files[filename] = chunk_count
            except Exception as e:
                logger.warning(f"Qdrant 파일별 청크 수 계산 실패: {e}")
                # 폴백: 파일명만 반환
                for filename in all_filenames:
                    files[filename] = 0
        else:
            # FAISS 호환 방식 (기존 코드)
            total_docs = len(vs.docstore._dict) if hasattr(vs, 'docstore') and hasattr(vs.docstore, '_dict') else 0
            
            # 파일별 청크 수 계산
            files: Dict[str, int] = {}
            try:
                if hasattr(vs, 'docstore') and hasattr(vs.docstore, '_dict'):
                    file_chunk_count: Dict[str, int] = {}
                    for doc in vs.docstore._dict.values():
                        filename = doc.metadata.get("file", "unknown")
                        if filename not in file_chunk_count:
                            file_chunk_count[filename] = 0
                        if doc.metadata.get("type", "text") == "text":
                            file_chunk_count[filename] += 1

                    for f in HOST_INPUT_DIR.iterdir():
                        if f.is_file():
                            files[f.name] = file_chunk_count.get(f.name, 0)
            except Exception as e:
                logger.warning(f"파일별 청크 수 계산 실패: {e}")
                for f in HOST_INPUT_DIR.iterdir():
                    if f.is_file():
                        files[f.name] = 0
    except Exception as e:
        logger.warning(f"벡터DB 상태 조회 실패: {e}")
        total_docs = 0
        files = {}
        # input 디렉터리의 파일 목록이라도 반환
        for f in HOST_INPUT_DIR.iterdir():
            if f.is_file():
                files[f.name] = 0

    return {"total_documents": total_docs, "files": files}


@app.get("/embedded_files")
def embedded_files():
    return {"count": len(get_embedded_files()), "items": get_embedded_files()}


# ==========================================================
# 채팅 히스토리 엔드포인트
# ==========================================================
@app.get("/chat_history")
def get_chat_history():
    data = _load_chat_history()
    return {"history": data.get("history", [])}


@app.get("/chat_history/{chat_id}")
def get_chat_messages(chat_id: str):
    data = _load_chat_history()
    chat_id_int = int(chat_id) if chat_id.isdigit() else None
    if chat_id_int and str(chat_id_int) in data.get("chats", {}):
        return {"messages": data["chats"][str(chat_id_int)]}
    return {"messages": []}


@app.post("/chat_history")
def save_chat(request: ChatSaveRequest):
    result = _save_chat(request.chat_id, request.title, request.messages, request.timestamp)
    return result


@app.delete("/chat_history/{chat_id}")
def delete_chat(chat_id: str):
    chat_id_int = int(chat_id) if chat_id.isdigit() else None
    if not chat_id_int:
        raise HTTPException(400, "Invalid chat_id")
    return _delete_chat(chat_id_int)


# ==========================================================
# 파일 삭제 엔드포인트
# ==========================================================
@app.delete("/delete_file/{filename}")
def delete_file(filename: str):
    from file_handler import _EMBEDDED_FILES
    
    filename = Path(filename).name
    input_path = HOST_INPUT_DIR / filename
    out_dir = HOST_OUTPUT_DIR / Path(filename).stem
    removed = False

    if input_path.exists():
        input_path.unlink()
        removed = True
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
        removed = True

    # 벡터DB에서 삭제 (인덱스 재구성 포함)
    try:
        delete_documents_by_file(filename)
    except Exception as e:
        logger.warning(f"Qdrant에서 문서 삭제 실패: {e}")
        # 삭제 실패 시에도 파일은 삭제되었으므로 계속 진행

    # 메모리 캐시에서 제거
    import file_handler
    file_handler._EMBEDDED_FILES = [it for it in file_handler._EMBEDDED_FILES if it["filename"] != filename]

    if not removed:
        raise HTTPException(404, f"{filename} 파일을 찾을 수 없습니다.")
    return {"message": f"{filename} 삭제 완료"}


@app.post("/reset_vectorstore")
def reset_vectorstore_endpoint():
    result = delete_qdrant_collection()
    return {
        "message": "벡터 스토어가 초기화되었습니다. 파일을 다시 업로드하여 벡터 스토어를 재구성하세요.",
        "deleted_files": result["deleted"]
    }


@app.post("/rebuild_vectorstore")
def rebuild_vectorstore_endpoint():
    try:
        result = rebuild_vectorstore_from_existing_files()
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"벡터 스토어 재구성 실패: {str(e)}")


@app.delete("/delete_all_files")
def delete_all_files():
    # input 파일 삭제
    for p in HOST_INPUT_DIR.iterdir():
        if p.is_file():
            p.unlink()

    # output 디렉터리 삭제
    for p in HOST_OUTPUT_DIR.iterdir():
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)

    # Qdrant는 인메모리이므로 디렉터리 불필요

    # 메모리 상태 초기화
    reset_vectorstore()
    import file_handler
    file_handler._EMBEDDED_FILES = []

    return {"message": "모든 문서 및 벡터 삭제 완료", "total_documents": 0}
