# vector_store.py
# -*- coding: utf-8 -*-
"""
벡터 스토어 및 임베딩 관리
Qdrant 벡터DB, 임베딩 모델, LLM 관리
"""

import os
import sys
import logging
from typing import List, Optional, Dict, Any
from pathlib import Path
from fastapi import HTTPException

logger = logging.getLogger(__name__)

try:
    try:
        # LangChain 0.1.2+ 에서는 QdrantVectorStore 사용
        from langchain_qdrant import QdrantVectorStore
        Qdrant = QdrantVectorStore  # 호환성을 위한 별칭
    except ImportError:
        # 구버전 호환
        from langchain_qdrant import Qdrant
    from langchain_core.documents import Document
    from qdrant_client import QdrantClient
    from qdrant_client.http.models import Distance, VectorParams
    HAS_QDRANT = True
except ImportError as e:
    HAS_QDRANT = False
    Qdrant = None
    QdrantVectorStore = None
    QdrantClient = None
    Distance = None
    VectorParams = None
    Document = None
    print(f"오류: Qdrant 라이브러리가 설치되지 않았습니다: {e}", file=sys.stderr)
    print("설치 명령: pip install langchain-qdrant qdrant-client", file=sys.stderr)
    sys.exit(1)

try:
    from langchain_ollama import ChatOllama, OllamaEmbeddings
    HAS_OLLAMA = True
    HAS_OLLAMA_EMBEDDINGS = True
except ImportError:
    try:
        from langchain_community.chat_models import ChatOllama
        from langchain_community.embeddings import OllamaEmbeddings
        HAS_OLLAMA = True
        HAS_OLLAMA_EMBEDDINGS = True
    except ImportError:
        try:
            from langchain_ollama import OllamaLLM, OllamaEmbeddings
            HAS_OLLAMA = True
            HAS_OLLAMA_EMBEDDINGS = True
            ChatOllama = None  # Fallback to OllamaLLM
        except ImportError:
            try:
                from langchain_community.llms import Ollama as OllamaLLM
                from langchain_community.embeddings import OllamaEmbeddings
                HAS_OLLAMA = True
                HAS_OLLAMA_EMBEDDINGS = True
                ChatOllama = None
            except ImportError:
                HAS_OLLAMA = False
                HAS_OLLAMA_EMBEDDINGS = False
                ChatOllama = None
                OllamaLLM = None
                OllamaEmbeddings = None

from config import EMBED_MODEL, OLLAMA_MODEL


# ==========================================================
# 전역 변수 (싱글톤 패턴)
# ==========================================================
_embeddings = None
_vectorstore = None
_llm = None
_qdrant_client = None

# Qdrant 설정 (환경 변수 필수)
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME")
if not QDRANT_COLLECTION_NAME:
    raise ValueError("QDRANT_COLLECTION_NAME 환경 변수가 설정되지 않았습니다. .env 파일을 확인하세요.")
QDRANT_VECTOR_SIZE = 1024  # bge-m3 임베딩 차원
QDRANT_DISTANCE = Distance.COSINE  # 코사인 유사도


# ==========================================================
# 임베딩 모델 관리
# ==========================================================
def get_embeddings():
    """Ollama 임베딩 모델을 한 번만 초기화해서 재사용."""
    global _embeddings
    if _embeddings is None:
        import os
        
        if not HAS_OLLAMA_EMBEDDINGS:
            raise HTTPException(500, "OllamaEmbeddings를 사용할 수 없습니다. langchain-ollama를 설치하세요.")
        
        # Ollama 임베딩 사용
        logger.info(f"Ollama 임베딩 모델 로드 중: {EMBED_MODEL}")
        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        
        try:
            _embeddings = OllamaEmbeddings(
                model=EMBED_MODEL,
                base_url=ollama_url
            )
            logger.info(f"Ollama 임베딩 모델 로드 완료: {EMBED_MODEL}")
        except Exception as e:
            logger.error(f"Ollama 임베딩 모델 로드 실패: {e}")
            raise HTTPException(500, f"Ollama 임베딩 모델 로드 실패: {e}")
    
    return _embeddings


# ==========================================================
# Qdrant 유틸리티 함수
# ==========================================================
def _ensure_collection_exists(qdrant_client):
    """Qdrant 컬렉션이 존재하는지 확인하고 없으면 생성."""
    try:
        collections = qdrant_client.get_collections().collections
        collection_names = [col.name for col in collections]

        if QDRANT_COLLECTION_NAME not in collection_names:
            logger.info(f"Qdrant 컬렉션 '{QDRANT_COLLECTION_NAME}' 생성 중")
            qdrant_client.create_collection(
                collection_name=QDRANT_COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=QDRANT_VECTOR_SIZE,
                    distance=QDRANT_DISTANCE
                )
            )
            logger.info(f"Qdrant 컬렉션 '{QDRANT_COLLECTION_NAME}' 생성 완료 (벡터 차원: {QDRANT_VECTOR_SIZE})")
        else:
            if os.getenv("DEBUG_QDRANT", "false").lower() == "true":
                collection_info = qdrant_client.get_collection(QDRANT_COLLECTION_NAME)
                logger.debug(f"Qdrant 컬렉션 '{QDRANT_COLLECTION_NAME}' 이미 존재 (포인트 수: {collection_info.points_count})")
    except Exception as e:
        error_msg = str(e)
        # 디렉토리 관련 오류인 경우 더 명확한 메시지 제공
        if "No such file or directory" in error_msg or "Can't create directory" in error_msg:
            logger.error("Qdrant 컬렉션 생성 실패: 스토리지 디렉토리 접근 불가")
            logger.error("원인: Qdrant 서버의 스토리지 디렉토리 권한 문제 또는 볼륨 마운트 문제")
            logger.error("해결 방법:")
            logger.error("1. Docker 볼륨 마운트 확인")
            logger.error("2. 디렉토리 생성 및 권한 설정: mkdir -p qdrant_storage && chmod 777 qdrant_storage")
            logger.error("3. 또는 인메모리 모드 사용: QDRANT_URL 환경 변수 제거")
            raise HTTPException(
                500,
                "Qdrant 컬렉션 생성 실패: 스토리지 디렉토리 접근 불가. "
                "Docker 볼륨 마운트를 확인하거나 인메모리 모드를 사용하세요."
            )
        else:
            logger.error(f"Qdrant 컬렉션 생성/확인 실패: {e}")
            raise HTTPException(500, f"Qdrant 컬렉션 생성 실패: {e}")


# ==========================================================
# Qdrant 클라이언트 관리
# ==========================================================
def get_qdrant_client():
    """
    Qdrant 클라이언트 생성 (로컬 파일 시스템, 인메모리 또는 서버 모드)

    환경 변수:
    - QDRANT_URL: Qdrant 서버 URL (우선순위 1)
      예: "http://localhost:6333" (Docker 서버)
    - QDRANT_PATH: 로컬 파일 시스템 경로 (우선순위 2)
      예: "/home/your_user/qdrant_storage" (로컬 파일 시스템 저장)
    - 기본값: 로컬 파일 시스템 저장 (BASE_DIR/qdrant_storage)
      예: ":memory:" (인메모리 모드, QDRANT_URL=":memory:"로 명시적 설정 시)
    """
    global _qdrant_client
    is_first_connection = _qdrant_client is None
    if _qdrant_client is None:
        if not HAS_QDRANT:
            raise HTTPException(500, "Qdrant가 설치되지 않았습니다. pip install langchain-qdrant qdrant-client")

        # Qdrant 설정 확인 (환경 변수 우선순위: QDRANT_URL > QDRANT_PATH > 기본값)
        qdrant_url = os.getenv("QDRANT_URL")
        qdrant_path = os.getenv("QDRANT_PATH")

        if qdrant_url:
            # QDRANT_URL이 설정된 경우
            if qdrant_url == ":memory:":
                # 인메모리 Qdrant 클라이언트 생성 (테스트/개발용)
                _qdrant_client = QdrantClient(":memory:")
                if is_first_connection:
                    logger.info("Qdrant 인메모리 클라이언트 생성 완료 (데이터는 프로세스 종료 시 사라집니다)")
            else:
                _qdrant_client = QdrantClient(url=qdrant_url)
                if is_first_connection:
                    logger.info(f"Qdrant 원격 서버 연결: {qdrant_url}")
        elif qdrant_path:
            # QDRANT_PATH가 설정된 경우 (로컬 파일 시스템 저장)
            storage_path = Path(qdrant_path)
            storage_path.mkdir(parents=True, exist_ok=True)
            _qdrant_client = QdrantClient(path=str(storage_path))
            if is_first_connection:
                logger.info(f"Qdrant 로컬 파일 시스템 저장소: {storage_path}")
        else:
            # 기본값: 로컬 파일 시스템 저장 (BASE_DIR/qdrant_storage)
            from config import BASE_DIR
            default_storage_path = BASE_DIR / "qdrant_storage"
            default_storage_path.mkdir(parents=True, exist_ok=True)
            os.chmod(default_storage_path, 0o777)
            _qdrant_client = QdrantClient(path=str(default_storage_path))
            if is_first_connection:
                logger.info(f"Qdrant 로컬 파일 시스템 저장소: {default_storage_path}")

        # 컬렉션 생성 (없는 경우) - 명시적으로 생성
        _ensure_collection_exists(_qdrant_client)

    return _qdrant_client


# ==========================================================
# 벡터 스토어 관리
# ==========================================================
def get_vectorstore():
    """Qdrant 벡터DB를 로드하거나 새로 생성."""
    global _vectorstore

    if not HAS_QDRANT:
        raise HTTPException(500, "Qdrant가 설치되지 않았습니다. pip install langchain-qdrant qdrant-client")

    embeddings = get_embeddings()
    qdrant_client = get_qdrant_client()

    # 컬렉션이 존재하는지 확인하고 없으면 생성 (항상 확인)
    _ensure_collection_exists(qdrant_client)

    # 기존 벡터스토어가 있고 컬렉션이 존재하면 재사용
    is_first_load = _vectorstore is None
    if _vectorstore is not None:
        try:
            # 컬렉션이 여전히 존재하는지 확인
            qdrant_client.get_collection(QDRANT_COLLECTION_NAME)
            return _vectorstore
        except Exception:
            # 컬렉션이 없으면 새로 생성
            _vectorstore = None
            is_first_load = True

    # Qdrant 벡터 저장소 객체 생성 (QdrantVectorStore 사용)
    try:
        # 최신 버전: QdrantVectorStore 사용
        _vectorstore = QdrantVectorStore(
            client=qdrant_client,
            collection_name=QDRANT_COLLECTION_NAME,
            embedding=embeddings  # 최신 버전에서는 'embedding' 파라미터 사용
        )
    except (TypeError, NameError) as e:
        # 구버전 호환: Qdrant 사용 (embedding 대신 embeddings)
        try:
            _vectorstore = Qdrant(
                client=qdrant_client,
                collection_name=QDRANT_COLLECTION_NAME,
                embeddings=embeddings
            )
        except Exception as e2:
            logger.error(f"Qdrant 벡터스토어 생성 실패: {e2}")
            # 컬렉션을 다시 확인하고 생성 시도
            _ensure_collection_exists(qdrant_client)
            _vectorstore = Qdrant(
                client=qdrant_client,
                collection_name=QDRANT_COLLECTION_NAME,
                embeddings=embeddings
            )

    if is_first_load:
        try:
            collection_info = qdrant_client.get_collection(QDRANT_COLLECTION_NAME)
            points_count = collection_info.points_count
            logger.info(f"Qdrant 벡터DB 로드 완료: 컬렉션 '{QDRANT_COLLECTION_NAME}' (문서 {points_count}개)")
        except Exception as e:
            logger.warning(f"Qdrant 벡터DB 정보 확인 실패: {e}")
            logger.info("Qdrant 새 벡터DB 생성 완료")

    return _vectorstore


def save_vectorstore():
    """Qdrant는 인메모리이므로 저장 불필요 (호환성을 위해 유지)."""
    # Qdrant 인메모리는 자동으로 저장되므로 별도 저장 불필요
    pass


def reset_vectorstore():
    """벡터스토어를 초기화합니다. (전역 변수를 None으로 설정)"""
    global _vectorstore, _qdrant_client
    _vectorstore = None
    _qdrant_client = None


def delete_qdrant_collection():
    """Qdrant 컬렉션을 삭제하여 벡터 스토어를 완전히 초기화합니다."""
    global _vectorstore, _qdrant_client
    _vectorstore = None

    try:
        qdrant_client = get_qdrant_client()
        qdrant_client.delete_collection(QDRANT_COLLECTION_NAME)
        logger.info(f"Qdrant 컬렉션 '{QDRANT_COLLECTION_NAME}' 삭제 완료")
        logger.info("파일을 다시 업로드하여 벡터 스토어를 재구성하세요")
        return {"deleted": [QDRANT_COLLECTION_NAME]}
    except Exception as e:
        logger.warning(f"Qdrant 컬렉션 삭제 실패: {e}")
        return {"deleted": []}


# ==========================================================
# LLM 관리
# ==========================================================
def get_llm():
    """Ollama LLM을 한 번만 생성해서 재사용."""
    global _llm
    if _llm is None:
        if not HAS_OLLAMA:
            raise HTTPException(500, "Ollama가 설치되지 않았습니다. pip install langchain-ollama")
        # ChatOllama를 우선 사용 (Modelfile TEMPLATE와 호환)
        if ChatOllama is not None:
            _llm = ChatOllama(
                model=OLLAMA_MODEL,
                temperature=0.1,  # 낮게 설정하여 정확도 향상
                num_ctx=4096  # 컨텍스트 길이 설정
            )
        elif OllamaLLM is not None:
            _llm = OllamaLLM(model=OLLAMA_MODEL, temperature=0.1)
        else:
            raise HTTPException(500, "Ollama LLM을 초기화할 수 없습니다.")
    return _llm


# ==========================================================
# 벡터 스토어 유틸리티
# ==========================================================
def add_documents_to_vectorstore(docs: List[Document]):
    """벡터스토어에 문서를 추가합니다."""
    vectorstore = get_vectorstore()
    if docs:
        vectorstore.add_documents(docs)
        logger.info(f"Qdrant {len(docs)}개 문서 추가 완료")


def delete_documents_by_file(filename: str):
    """특정 파일명의 모든 문서를 벡터스토어에서 삭제합니다."""
    vectorstore = get_vectorstore()
    qdrant_client = get_qdrant_client()

    try:
        # Qdrant에서 메타데이터 필터를 사용하여 문서 삭제
        # 필터: metadata.file == filename
        from qdrant_client.http.models import Filter, FieldCondition, MatchValue

        filter_condition = Filter(
            must=[
                FieldCondition(
                    key="metadata.file",  # LangChain Qdrant는 metadata. 접두사 사용
                    match=MatchValue(value=filename)
                )
            ]
        )

        # 필터에 맞는 포인트 삭제
        result = qdrant_client.delete(
            collection_name=QDRANT_COLLECTION_NAME,
            points_selector=filter_condition
        )

        logger.info(f"Qdrant 파일 '{filename}' 관련 문서 삭제 완료")
    except Exception as e:
        logger.error(f"Qdrant 문서 삭제 실패: {e}")
        # 폴백: 컬렉션 전체 삭제 후 재구성
        try:
            # 모든 문서를 가져와서 필터링
            all_points = qdrant_client.scroll(
                collection_name=QDRANT_COLLECTION_NAME,
                limit=10000,
                with_payload=True
            )[0]

            # 삭제할 포인트 ID 수집
            ids_to_delete = []
            for point in all_points:
                if point.payload and point.payload.get("file") == filename:
                    ids_to_delete.append(point.id)

            if ids_to_delete:
                qdrant_client.delete(
                    collection_name=QDRANT_COLLECTION_NAME,
                    points_selector=ids_to_delete
                )
                logger.info(f"Qdrant {len(ids_to_delete)}개 문서 삭제 완료: {filename}")
            else:
                logger.info(f"삭제할 문서가 없습니다: {filename}")
        except Exception as e2:
            logger.error(f"폴백 삭제 방법도 실패: {e2}")


def get_all_filenames() -> List[str]:
    """벡터스토어에 저장된 모든 파일명 목록을 반환합니다."""
    qdrant_client = get_qdrant_client()

    try:
        # 모든 포인트를 스크롤하여 파일명 수집
        all_points = qdrant_client.scroll(
            collection_name=QDRANT_COLLECTION_NAME,
            limit=10000,
            with_payload=True
        )[0]

        filenames = set()
        for point in all_points:
            if point.payload:
                # LangChain Qdrant는 payload에 metadata를 저장
                metadata = point.payload.get("metadata", {})
                filename = metadata.get("file")
                if filename:
                    filenames.add(filename)

        return sorted(list(filenames))
    except Exception as e:
        logger.error(f"파일명 목록 조회 실패: {e}")
        return []


def get_document_count() -> int:
    """벡터스토어에 저장된 총 문서(청크) 수를 반환합니다."""
    qdrant_client = get_qdrant_client()

    try:
        collection_info = qdrant_client.get_collection(QDRANT_COLLECTION_NAME)
        return collection_info.points_count
    except Exception as e:
        logger.error(f"문서 수 조회 실패: {e}")
        return 0

