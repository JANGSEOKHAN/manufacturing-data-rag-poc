# admin_api.py
# -*- coding: utf-8 -*-
"""
관리자 페이지용 API 엔드포인트
React 프론트엔드를 위한 REST API
"""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ==========================================================
# Pydantic 모델
# ==========================================================
class DocumentInfo(BaseModel):
    filename: str
    total_chunks: int
    total_images: int
    text_chunks_preview: List[Dict[str, Any]]
    image_summaries_preview: List[Dict[str, Any]]


class ChunkDetail(BaseModel):
    chunk_index: int
    content: str
    length: int
    metadata: Dict[str, Any]


class ImageSummary(BaseModel):
    image_name: str
    summary: str
    length: int
    metadata: Dict[str, Any]


class FileDetail(BaseModel):
    filename: str
    total_chunks: int
    total_images: int
    text_chunks: List[ChunkDetail]
    image_summaries: List[ImageSummary]
    md_path: Optional[str] = None
    html_path: Optional[str] = None


# ==========================================================
# API 엔드포인트 함수들
# ==========================================================
def get_all_documents(
    vectorstore_getter,
    output_dir: Path
):
    """모든 문서 목록 조회 (최적화: 파일별 통계만 계산)"""
    vs = vectorstore_getter()
    
    try:
        # Qdrant 방식 - QdrantVectorStore 또는 Qdrant 모두 지원
        from qdrant_client.http.models import ScrollRequest
        from langchain_core.documents import Document
        
        # QdrantVectorStore의 경우 client와 collection_name 속성 확인
        # 여러 가능한 속성 이름 시도
        qdrant_client = None
        collection_name = None
        
        # 방법 1: 공개 속성
        if hasattr(vs, 'client') and hasattr(vs, 'collection_name'):
            qdrant_client = vs.client
            collection_name = vs.collection_name
        # 방법 2: 내부 속성 (언더스코어)
        elif hasattr(vs, '_client') and hasattr(vs, '_collection_name'):
            qdrant_client = vs._client
            collection_name = vs._collection_name
        # 방법 3: 다른 가능한 속성 이름
        elif hasattr(vs, 'qdrant_client'):
            qdrant_client = vs.qdrant_client
            collection_name = getattr(vs, 'collection_name', None) or getattr(vs, '_collection_name', None)
        
        # 위 방법들이 모두 실패하면 직접 가져오기
        if qdrant_client is None:
            from vector_store import get_qdrant_client
            qdrant_client = get_qdrant_client()
            from vector_store import QDRANT_COLLECTION_NAME
            collection_name = QDRANT_COLLECTION_NAME
        
        # 성능 최적화: 전체 문서를 한 번만 scroll하여 메모리에서 그룹화
        # 파일별로 여러 번 scroll하는 대신, 한 번만 scroll하여 모든 정보 수집
        files_dict: Dict[str, Dict[str, Any]] = {}
        
        # 전체 문서를 한 번만 scroll (with_payload=True로 메타데이터 포함)
        scroll_result = qdrant_client.scroll(
            collection_name=collection_name,
            limit=10000,
            with_payload=True,
            with_vectors=False
        )
        
        # 파일별로 그룹화 및 통계 계산
        for point in scroll_result[0]:
            if not point.payload:
                continue
            
            # payload에서 메타데이터 추출
            metadata = point.payload.get("metadata", {})
            if isinstance(metadata, str):
                import json
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}
            
            if not isinstance(metadata, dict):
                continue
            
            filename = metadata.get("file", "unknown")
            doc_type = metadata.get("type", "text")
            page_content = point.payload.get("page_content", "")
            
            # 파일별 딕셔너리 초기화
            if filename not in files_dict:
                files_dict[filename] = {
                    "text_chunks": [],
                    "image_summaries": [],
                    "total_chunks": 0,
                    "total_images": 0
                }
            
            # 타입별로 분류 및 통계 계산
            if doc_type == "text":
                files_dict[filename]["total_chunks"] += 1
                # 미리보기는 최대 3개만 저장
                if len(files_dict[filename]["text_chunks"]) < 3:
                    files_dict[filename]["text_chunks"].append({
                        "content": page_content[:500] + "..." if len(page_content) > 500 else page_content,
                        "full_length": len(page_content),
                        "chunk_index": metadata.get("chunk_index", -1),
                        "metadata": metadata
                    })
            elif doc_type == "image":
                files_dict[filename]["total_images"] += 1
                # 미리보기는 최대 3개만 저장
                if len(files_dict[filename]["image_summaries"]) < 3:
                    files_dict[filename]["image_summaries"].append({
                        "summary": page_content[:300] + "..." if len(page_content) > 300 else page_content,
                        "full_length": len(page_content),
                        "image_name": metadata.get("image_name", "unknown"),
                        "metadata": metadata
                    })
        
        # 기존 로직 스킵하고 바로 응답 형식으로 변환
        result = []
        for filename, data in files_dict.items():
            result.append(DocumentInfo(
                filename=filename,
                total_chunks=data["total_chunks"],
                total_images=data["total_images"],
                text_chunks_preview=data["text_chunks"][:3],
                image_summaries_preview=data["image_summaries"][:3]
            ))
        
        return result
            
    except Exception as e:
        logger.error(f"문서 목록 가져오기 실패: {e}", exc_info=True)
        raise HTTPException(500, f"문서 목록 가져오기 실패: {e}")


def get_document_detail(
    filename: str,
    vectorstore_getter,
    output_dir: Path
):
    """특정 파일의 상세 정보"""
    from urllib.parse import unquote
    filename = unquote(filename)
    filename = Path(filename).name
    
    vs = vectorstore_getter()
    
    # 해당 파일의 모든 문서 가져오기
    file_docs = []
    try:
        # Qdrant 방식 - QdrantVectorStore 또는 Qdrant 모두 지원
        from qdrant_client.http.models import Filter, FieldCondition, MatchValue
        from langchain_core.documents import Document
        
        # QdrantVectorStore의 경우 client와 collection_name 속성 확인
        if hasattr(vs, 'client') and hasattr(vs, 'collection_name'):
            qdrant_client = vs.client
            collection_name = vs.collection_name
        elif hasattr(vs, '_client') and hasattr(vs, '_collection_name'):
            qdrant_client = vs._client
            collection_name = vs._collection_name
        else:
            from vector_store import get_qdrant_client
            qdrant_client = get_qdrant_client()
            from vector_store import QDRANT_COLLECTION_NAME
            collection_name = QDRANT_COLLECTION_NAME
        
        # 파일명으로 필터링
        filter_condition = Filter(
            must=[
                FieldCondition(
                    key="metadata.file",
                    match=MatchValue(value=filename)
                )
            ]
        )
        scroll_result = qdrant_client.scroll(
            collection_name=collection_name,
            scroll_filter=filter_condition,
            limit=10000,
            with_payload=True,
            with_vectors=False
        )
        
        for point in scroll_result[0]:
            if point.payload:
                page_content = point.payload.get("page_content", "")
                payload_metadata = point.payload.get("metadata", {})
                
                # metadata가 문자열로 저장된 경우 JSON 파싱
                if isinstance(payload_metadata, str):
                    import json
                    try:
                        payload_metadata = json.loads(payload_metadata)
                    except:
                        payload_metadata = {}
                
                file_docs.append(Document(
                    page_content=page_content,
                    metadata=payload_metadata
                ))
        
        # FAISS 호환성 (Qdrant가 아닌 경우)
        if len(file_docs) == 0 and hasattr(vs, 'docstore') and hasattr(vs.docstore, '_dict'):
            for doc in vs.docstore._dict.values():
                if doc.metadata.get("file") == filename:
                    file_docs.append(doc)
    except Exception as e:
        raise HTTPException(500, f"문서 가져오기 실패: {e}")
    
    # 텍스트 청크와 이미지 요약 분리
    text_chunks = sorted(
        [d for d in file_docs if d.metadata.get("type", "text") == "text"],
        key=lambda x: x.metadata.get("chunk_index", 999)
    )
    image_summaries = [d for d in file_docs if d.metadata.get("type") == "image"]
    
    # 원본 MD/HTML 파일 찾기
    base_dir = output_dir / Path(filename).stem
    md_path = None
    html_path = None
    
    for subdir in ["ocr", "vlm", ""]:
        if subdir:
            test_dir = base_dir / subdir
        else:
            test_dir = base_dir
        
        if test_dir.exists():
            md_files = list(test_dir.glob("*.md"))
            html_files = list(test_dir.glob("*.html"))
            if md_files:
                md_path = str(md_files[0])
            if html_files:
                html_path = str(html_files[0])
            if md_path or html_path:
                break
    
    return FileDetail(
        filename=filename,
        total_chunks=len(text_chunks),
        total_images=len(image_summaries),
        text_chunks=[
            ChunkDetail(
                chunk_index=chunk.metadata.get("chunk_index", i),
                content=chunk.page_content,
                length=len(chunk.page_content),
                metadata=chunk.metadata
            )
            for i, chunk in enumerate(text_chunks)
        ],
        image_summaries=[
            ImageSummary(
                image_name=img.metadata.get("image_name", "unknown"),
                summary=img.page_content,
                length=len(img.page_content),
                metadata=img.metadata
            )
            for img in image_summaries
        ],
        md_path=md_path,
        html_path=html_path
    )


def get_admin_api_router(vectorstore_getter, output_dir: Path):
    """관리자 API 라우터 생성"""
    admin_router = APIRouter(prefix="/api/admin", tags=["admin"])
    
    @admin_router.get("/documents", response_model=List[DocumentInfo])
    def get_all_documents_endpoint():
        return get_all_documents(vectorstore_getter, output_dir)
    
    @admin_router.get("/documents/{filename:path}", response_model=FileDetail)
    def get_document_detail_endpoint(filename: str):
        return get_document_detail(filename, vectorstore_getter, output_dir)
    
    return admin_router
