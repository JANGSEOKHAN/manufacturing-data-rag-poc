# -*- coding: utf-8 -*-
"""
- 텍스트 청킹 로직 및 파일 업로드 처리 핸들러
- 텍스트 청킹: 구조 기반 청킹, 의미 기반 청킹
- 파일 업로드: MinerU 처리, 청킹, 벡터DB 저장
"""

import os
import re
import time
import logging
import threading
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Optional
from langchain_core.documents import Document

from config import HOST_INPUT_DIR
from config import process_with_mineru, enrich_markdown_with_image_summaries
from md_image import markdown_to_html_inline_images
from vector_store import get_vectorstore, save_vectorstore, reset_vectorstore, get_llm

# 로깅 설정
logger = logging.getLogger(__name__)


# ============================================================
# 텍스트 청킹 로직 (원래 chunking.py에 있던 코드)
# ============================================================

def chunk_text(
    text: str,
    chunk_size: int,
    overlap: int,
    use_chapters: bool = True,
    use_pages: bool = False,
    post_process: bool = True,
    post_process_max_size: int = 1500,
    post_process_min_size: int = 200,
) -> List[str]:
    """
    헤더 기반 청킹 + MarkdownHeaderTextSplitter

    헤더(#)와 Error Code 번호를 기준으로 먼저 큰 단위로 분할한 후,
    각 단위에 대해 크기 기반 분할을 적용합니다.
    """
    if not text:
        return []

    try:
        from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
        use_langchain = True
    except ImportError:
        use_langchain = False

    def recursive_split(text: str, chunk_size: int, overlap: int, separators: List[str]) -> List[str]:
        """재귀적으로 텍스트를 분할하는 함수"""
        if len(text) <= chunk_size:
            return [text]

        for separator in separators:
            if separator in text:
                splits = text.split(separator)
                chunks = []
                current_chunk = ""

                for i, split in enumerate(splits):
                    if i < len(splits) - 1:
                        split += separator

                    if len(current_chunk) + len(split) <= chunk_size:
                        current_chunk += split
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                        if len(split) > chunk_size:
                            # 재귀적으로 더 작게 분할
                            sub_chunks = recursive_split(split, chunk_size, overlap, separators[1:])
                            chunks.extend(sub_chunks[:-1])
                            current_chunk = sub_chunks[-1] if sub_chunks else split
                        else:
                            current_chunk = split

                if current_chunk:
                    chunks.append(current_chunk)

                # overlap 처리
                if overlap > 0 and len(chunks) > 1:
                    overlapped_chunks = [chunks[0]]
                    for i in range(1, len(chunks)):
                        prev_end = chunks[i-1][-overlap:] if len(chunks[i-1]) > overlap else chunks[i-1]
                        overlapped_chunks.append(prev_end + chunks[i])
                    return overlapped_chunks

                return chunks if chunks else [text]

        # 분리자를 찾지 못한 경우 그대로 반환
        return [text]

    # 1. 헤더와 Error Code 번호를 기준으로 큰 단위로 분할
    # 이미지와 이미지 요약을 하나의 청크로 묶기
    sections = []
    current_section = []
    lines = text.split('\n')

    # 이미지 패턴: ![](images/...)
    image_pattern = re.compile(r'!\[.*?\]\(images/[^\)]+\)', re.IGNORECASE)
    # VLM 요약 패턴: **[VLM 이미지 요약]**:
    vlm_summary_pattern = re.compile(r'\*\*\[VLM 이미지 요약\]\*\*:', re.IGNORECASE)
    # 헤더 패턴 (#으로 시작)
    header_pattern = re.compile(r'^#+\s*')

    i = 0

    while i < len(lines):
        line = lines[i]
        line_stripped = line.strip()

        # 이미지 라인인지 확인
        is_image = bool(image_pattern.match(line_stripped))
        # VLM 요약 라인인지 확인
        is_vlm_summary = bool(vlm_summary_pattern.search(line_stripped))
        # 헤더인지 확인
        is_header = bool(header_pattern.match(line_stripped))

        # 에러 코드 패턴 (2자리 이상도 감지하도록 수정)
        error_code_pattern = r'\b([A-Z]{1,3}\d{2,5}|\d{2,5}[A-Z]{0,2}|[A-Z]{2,}\d{2,})\b'
        line_cleaned = re.sub(r'[「」-]', '', line)
        error_code_match = re.search(error_code_pattern, line_cleaned, re.IGNORECASE)

        # 이미지 블록 처리
        if is_image:
            # 이미지 바로 위 라인 확인 (헤더가 있는지)
            has_header_above = False
            header_line = None
            if current_section:
                # current_section의 마지막 줄 확인
                last_line = current_section[-1].strip() if current_section else ""
                if header_pattern.match(last_line):
                    has_header_above = True
                    header_line = current_section[-1]

            if has_header_above:
                # 헤더가 있으면: 헤더 이전까지 저장하고, 헤더부터 새 섹션 시작
                if len(current_section) > 1:
                    # 헤더를 제외한 이전 섹션 저장
                    section_text = '\n'.join(current_section[:-1]).strip()
                    if section_text:
                        sections.append(section_text)
                # 헤더부터 시작하는 새 섹션
                current_section = [header_line, line]
            else:
                # 헤더가 없으면 이전 청크에 붙이기
                current_section.append(line)

            # VLM 요약 블록 수집 (이미지 다음에 오는 요약)
            # VLM 요약은 여러 줄에 걸쳐 있을 수 있으므로, 요약이 끝날 때까지 수집
            i += 1
            vlm_summary_started = False
            vlm_summary_ended = False

            while i < len(lines):
                next_line = lines[i]
                next_line_stripped = next_line.strip()

                # VLM 요약 시작 확인
                if vlm_summary_pattern.search(next_line_stripped):
                    vlm_summary_started = True
                    current_section.append(next_line)
                    i += 1
                    continue

                # VLM 요약이 시작된 상태에서 계속 수집
                if vlm_summary_started:
                    # 다음 이미지가 나오면 종료
                    is_next_image = bool(image_pattern.match(next_line_stripped))
                    if is_next_image:
                        break

                    # 헤더가 나오면 종료 (단, VLM 요약 내부의 헤더는 아님)
                    is_next_header = bool(header_pattern.match(next_line_stripped))
                    if is_next_header:
                        # 헤더가 나왔다는 것은 VLM 요약이 끝났다는 의미
                        break

                    # 빈 줄이 2개 이상 연속으로 나오면 VLM 요약 종료로 간주
                    if not next_line_stripped:
                        # 다음 줄도 확인
                        if i + 1 < len(lines):
                            next_next_line = lines[i + 1].strip()
                            if not next_next_line:
                                # 빈 줄 2개 연속 = 요약 종료
                                break

                    # VLM 요약 내부의 부품 코드는 무시하고 계속 수집
                    # (예: "B1302:", "B1332:" 등은 요약 내용의 일부)
                    current_section.append(next_line)
                    i += 1
                    continue

                # VLM 요약이 아직 시작되지 않았으면 시작 확인
                # 다음 이미지나 헤더가 나오면 종료
                is_next_image = bool(image_pattern.match(next_line_stripped))
                is_next_header = bool(header_pattern.match(next_line_stripped))
                is_next_error_code = bool(re.search(error_code_pattern, re.sub(r'[「」-]', '', next_line), re.IGNORECASE))

                if is_next_image or (is_next_header and not vlm_summary_pattern.search(next_line_stripped)):
                    break

                # VLM 요약 시작 전의 일반 텍스트도 포함 (예: 설명문)
                current_section.append(next_line)
                i += 1

            continue

        # 에러 코드 라인 처리
        if error_code_match and current_section:
            # 이전 섹션 저장
            section_text = '\n'.join(current_section).strip()
            if section_text:
                sections.append(section_text)
            current_section = [line]
        # 헤더 처리
        elif is_header:
            # 에러 코드 관련 헤더인지 확인 (Cause, Solution, Inspection, Error Code, Error Message 등)
            header_lower = line_stripped.lower()
            is_error_related_header = any(keyword in header_lower for keyword in [
                'cause', 'solution', 'inspection', 'error code', 'error message',
                'phenomenon', '원인', '해결', '검사', '에러 코드', '에러 메시지'
            ])

            # 현재 섹션이 에러 코드로 시작하는 경우, 에러 관련 헤더는 같은 청크에 포함
            if current_section:
                current_section_text = '\n'.join(current_section)
                has_error_code_in_section = bool(re.search(error_code_pattern, current_section_text, re.IGNORECASE))

                if has_error_code_in_section and is_error_related_header:
                    # 에러 코드 블록 내의 헤더이므로 같은 청크에 추가
                    current_section.append(line)
                else:
                    # 현재 섹션이 헤더만 있는지 확인 (본문이 없는지)
                    current_lines = [l.strip() for l in current_section if l.strip()]
                    is_current_section_header_only = all(
                        header_pattern.match(l) for l in current_lines
                    )
                    
                    if is_current_section_header_only:
                        # 현재 섹션이 헤더만 있으면 연속 헤더로 간주하여 같은 청크에 추가
                        current_section.append(line)
                    else:
                        # 현재 섹션에 본문이 있으면 새 청크 시작
                        section_text = '\n'.join(current_section).strip()
                        if section_text:
                            sections.append(section_text)
                        current_section = [line]
            else:
                current_section = [line]
        else:
            current_section.append(line)

        i += 1

    # 마지막 섹션 저장
    if current_section:
        section_text = '\n'.join(current_section).strip()
        if section_text:
            sections.append(section_text)

    # 2. 각 섹션에 대해 크기 기반 분할 적용
    all_chunks = []
    separators = ["\n\n", "\n", ". ", " ", ""]

    if use_langchain:
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=overlap,
            length_function=len,
            separators=separators
        )

    for section in sections:
        # 이미지+요약 블록인지 확인 (이미지와 VLM 요약이 포함된 경우)
        has_image = bool(image_pattern.search(section))
        has_vlm_summary = bool(vlm_summary_pattern.search(section))
        is_image_summary_block = has_image and has_vlm_summary

        # 이미지+요약 블록은 크기와 관계없이 하나의 청크로 유지
        if is_image_summary_block:
            all_chunks.append(section)
            continue

        # [수정] Error Code 섹션인지 확인 (에러 코드 패턴 포함 여부)
        has_error_code = bool(re.search(error_code_pattern, section, re.IGNORECASE))

        # Error Code 섹션이고 POST_PROCESS_MAX_SIZE 이하면 분할하지 않음
        # (임시 조치: CHUNK_SIZE를 2000 이상으로 늘리는 것을 권장)
        if has_error_code and len(section) <= post_process_max_size:
            all_chunks.append(section)
        # 섹션이 chunk_size 이하면 그대로 추가
        elif len(section) <= chunk_size:
            all_chunks.append(section)
        else:
            # langchain 사용 가능하면 사용, 아니면 직접 구현 사용
            if use_langchain:
                chunks = text_splitter.split_text(section)
            else:
                chunks = recursive_split(section, chunk_size, overlap, separators)
            all_chunks.extend(chunks)

    # 3. Post-processing: 헤더만 있는 작은 청크를 다음 청크와 병합
    if post_process:
        merged_chunks = []
        i = 0
        while i < len(all_chunks):
            current_chunk = all_chunks[i]
            current_stripped = current_chunk.strip()
            
            # 헤더만 있는 작은 청크인지 확인
            # 조건: 1) 길이가 post_process_min_size 이하, 2) 헤더로 시작 (#), 3) 본문이 거의 없음
            is_header_only = (
                len(current_stripped) <= post_process_max_size and
                current_stripped.startswith("#") and
                len(current_stripped.splitlines()) <= 3  # 3줄 이하 (헤더 + 빈 줄 정도)
            )
            
            # 헤더만 있는 청크이고 다음 청크가 있으면 병합
            if is_header_only and i + 1 < len(all_chunks):
                next_chunk = all_chunks[i + 1]
                merged_chunk = current_chunk + "\n\n" + next_chunk
                
                # 병합 후 크기가 너무 크지 않으면 병합, 크면 그대로 유지
                if len(merged_chunk) <= chunk_size * 1.5:  # chunk_size의 1.5배 이하면 병합 허용
                    merged_chunks.append(merged_chunk)
                    i += 2  # 현재 청크와 다음 청크 모두 처리했으므로 2개 건너뛰기
                    continue
                else:
                    # 병합하면 너무 크면 현재 청크만 추가하고 다음 청크는 그대로
                    merged_chunks.append(current_chunk)
                    i += 1
                    continue
            
            # 병합하지 않는 경우 그대로 추가
            merged_chunks.append(current_chunk)
            i += 1
        
        return merged_chunks

    return all_chunks


def extract_equipment_metadata_from_file(filename: str, md_text: str) -> Dict[str, Optional[str]]:
    """
    파일 단위로 LLM을 사용하여 장비명과 모델 추출 (1회만 호출)
    파일명과 문서 앞부분을 함께 분석하여 메타데이터 생성
    
    Args:
        filename: 파일명 (예: "DOC-A100 Error Code.docx")
        md_text: 마크다운 텍스트 (전체 또는 앞부분)
    
    Returns:
        {"equipment_name": "DOC", "equipment_model": "A100"} 또는 None 값 포함
    """
    try:
        llm = get_llm()
        if llm is None:
            logger.warning("LLM이 초기화되지 않아 장비 정보 추출을 건너뜁니다")
            return {"equipment_name": None, "equipment_model": None}
        
        # 문서의 앞부분만 사용 (표지, 제목 등 - 최대 3000자)
        # 파일명도 힌트로 제공
        sample_text = md_text[:3000] if len(md_text) > 3000 else md_text
        
        prompt = f"""다음 문서의 파일명과 내용을 분석하여 장비명(equipment_name)과 모델명(equipment_model)을 추출해주세요.

파일명: {filename}

문서 내용 (앞부분):
{sample_text}

위 정보를 바탕으로 다음 JSON 형식으로만 답변해주세요:
{{
  "equipment_name": "장비명",
  "equipment_model": "모델명"
}}

**추출 규칙:**
1. 파일명과 문서 내용을 모두 분석하여 장비 정보를 찾으세요
2. 파일명이 "scan01", "final_scan_002"처럼 의미가 없어도, 문서 내용(제목, 표지, 첫 페이지 등)에서 장비 정보를 찾으세요
   - 예시: 문서에 "Sample Machine A100 Service Guide"가 있으면 → equipment_name: "Sample Machine", equipment_model: "A100"
   - 예시: 문서에 "Demo Loader B200 User Guide"가 있으면 → equipment_name: "Demo Loader", equipment_model: "B200"
   - 예시: 문서에 "DOC-C300 Error Code"가 있으면 → equipment_name: "DOC", equipment_model: "C300"
   - 예시: 파일명이 "DOC-A100 Manual.docx"이고 문서에도 "DOC-A100"가 있으면 → equipment_name: "DOC", equipment_model: "A100"
3. 장비명은 찾았지만 모델명이 없는 경우도 있습니다. 이 경우 equipment_name만 추출하고 equipment_model은 null로 설정하세요
   - 예시: 문서에 "Sample Machine Service Manual"만 있고 모델명이 없으면 → equipment_name: "Sample Machine", equipment_model: null
   - 예시: 문서에 "Demo Equipment Guide"만 있으면 → equipment_name: "Demo Equipment", equipment_model: null
4. 장비명과 모델명 모두 찾을 수 없으면 둘 다 null로 표시하세요
5. 추측하지 말고 문서에서 명확히 보이는 것만 추출하세요
6. JSON 형식만 답변하고 다른 설명은 하지 마세요

**응답 예시:**
{{
  "equipment_name": "DOC",
  "equipment_model": "A100"
}}
또는 (장비명만 있는 경우)
{{
  "equipment_name": "Sample Machine",
  "equipment_model": null
}}
또는 (둘 다 없는 경우)
{{
  "equipment_name": null,
  "equipment_model": null
}}"""

        from langchain_core.messages import HumanMessage
        if hasattr(llm, "invoke") and "Chat" in type(llm).__name__:
            response = llm.invoke([HumanMessage(content=prompt)])
            result_text = response.content if hasattr(response, "content") else str(response)
        else:
            response = llm.invoke(prompt)
            result_text = response.content if hasattr(response, "content") else str(response)
        
        # JSON 파싱
        import json
        # JSON 부분만 추출 (```json ... ``` 또는 {...} 형식)
        json_match = re.search(r'\{[^}]*"equipment_name"[^}]*"equipment_model"[^}]*\}', result_text, re.DOTALL)
        if json_match:
            try:
                result_json = json.loads(json_match.group(0))
                equipment_name = result_json.get("equipment_name")
                equipment_model = result_json.get("equipment_model")
                
                # null 문자열 처리
                if equipment_name and equipment_name.lower() not in ["null", "none", ""]:
                    equipment_name = equipment_name.upper().strip()
                else:
                    equipment_name = None
                    
                if equipment_model and equipment_model.lower() not in ["null", "none", ""]:
                    equipment_model = equipment_model.upper().strip()
                else:
                    equipment_model = None
                
                logger.info(f"장비 정보 추출: {equipment_name}/{equipment_model}")
                return {
                    "equipment_name": equipment_name,
                    "equipment_model": equipment_model
                }
            except json.JSONDecodeError as e:
                logger.debug(f"JSON 파싱 실패: {e}")
        
        return {"equipment_name": None, "equipment_model": None}
    except Exception as e:
        logger.warning(f"장비 정보 추출 실패: {e}")
        return {"equipment_name": None, "equipment_model": None}


# ============================================================
# 파일 업로드 처리 핸들러 (원래 file_handler.py에 있던 코드)
# ============================================================

# 업로드 작업 상태 추적 (파일명 -> 상태)
_UPLOAD_STATUS: Dict[str, Dict[str, Any]] = {}
_UPLOAD_STATUS_LOCK = threading.Lock()

# 업로드/임베딩된 파일 목록을 메모리에 들고 있는 간단한 캐시
_EMBEDDED_FILES: List[Dict[str, Any]] = []


def get_upload_status(filename: str) -> Dict[str, Any]:
    """업로드 처리 상태 조회"""
    with _UPLOAD_STATUS_LOCK:
        status = _UPLOAD_STATUS.get(filename, {
            "status": "not_found",
            "message": "업로드 정보를 찾을 수 없습니다.",
            "progress": 0
        })
    return status


def get_embedded_files() -> List[Dict[str, Any]]:
    """임베딩된 파일 목록 조회"""
    return _EMBEDDED_FILES.copy()


def process_upload_file(filename: str):
    """파일 업로드 후 처리 (MinerU, 청킹, 벡터DB 저장)"""
    try:
        with _UPLOAD_STATUS_LOCK:
            _UPLOAD_STATUS[filename] = {
                "status": "processing",
                "message": "파일 처리 중...",
                "progress": 0
            }

        logger.info(f"업로드 처리 시작: {filename}")

        # MinerU 실행해서 md 얻기
        from config import process_with_mineru

        with _UPLOAD_STATUS_LOCK:
            _UPLOAD_STATUS[filename]["message"] = "MinerU로 문서 변환 중..."
            _UPLOAD_STATUS[filename]["progress"] = 10

        # [1단계] MinerU로 문서 파싱 (GPU 사용)
        md_path = process_with_mineru(filename)
        parent_dir = md_path.parent
        img_dir = parent_dir / "images"

        # [2단계] 이미지 요약 및 MD 강화 (GPU가 비어있을 때 수행)
        use_image_enrichment = os.getenv("USE_IMAGE_ENRICHMENT", "true").lower() == "true"

        if use_image_enrichment and img_dir.exists():
            with _UPLOAD_STATUS_LOCK:
                _UPLOAD_STATUS[filename]["message"] = "이미지 요약 생성 중..."
                _UPLOAD_STATUS[filename]["progress"] = 25

            logger.info("이미지 요약 및 MD 강화 시작")
            try:
                md_path = enrich_markdown_with_image_summaries(md_path, img_dir)
                logger.info("MD 강화 완료")
            except Exception as e:
                logger.warning(f"이미지 요약 생성 실패 (계속 진행): {e}")
                # 실패해도 원본 MD로 계속 진행

        with _UPLOAD_STATUS_LOCK:
            _UPLOAD_STATUS[filename]["message"] = "HTML 변환 중..."
            _UPLOAD_STATUS[filename]["progress"] = 30

        # md → HTML (이미지 인라인 포함) - 강화된 MD 사용
        md_text = md_path.read_text(encoding="utf-8", errors="ignore")
        html_text = markdown_to_html_inline_images(md_text, img_dir)
        html_path = parent_dir / f"{md_path.stem}.html"
        html_path.write_text(html_text, encoding="utf-8")

        # ====== 청킹 및 벡터 저장 ======
        # 환경 변수에서 청킹 설정 읽기
        from config import CHUNK_SIZE, POST_PROCESS_MAX_SIZE
        chunk_size = CHUNK_SIZE
        post_max = POST_PROCESS_MAX_SIZE
        overlap = int(os.getenv("CHUNK_OVERLAP", "200"))

        with _UPLOAD_STATUS_LOCK:
            _UPLOAD_STATUS[filename]["message"] = "문서 청킹 중..."
            _UPLOAD_STATUS[filename]["progress"] = 50

        # 헤더 기반 청킹 실행
        chunks = chunk_text(
            md_text,
            chunk_size=chunk_size,
            overlap=overlap,
            use_chapters=True,
            use_pages=False,
            post_process=True,
            post_process_max_size=post_max,
            post_process_min_size=0,
        )
        chunking_mode = "헤더 기반 청킹"
        logger.info(f"청킹 완료: {len(chunks)}개 청크 (방식: {chunking_mode})")

        # [파일 단위] 장비 정보 추출 (LLM 사용, 1회만 호출)
        with _UPLOAD_STATUS_LOCK:
            _UPLOAD_STATUS[filename]["message"] = "장비 정보 추출 중..."
            _UPLOAD_STATUS[filename]["progress"] = 55
        
        equipment_metadata = extract_equipment_metadata_from_file(filename, md_text)
        logger.debug(f"메타데이터: {equipment_metadata.get('equipment_name')}/{equipment_metadata.get('equipment_model')}")

        def extract_chunk_metadata(chunk_text: str) -> tuple[dict, str]:
            """청크에서 에러코드와 타입 추출 (정제 기능 포함)
            
            VLM 이미지 요약을 page_content에서 제거하고 metadata에만 저장 (Multi-Vector 전략)
            
            Returns:
                (metadata, clean_text): 메타데이터와 VLM 요약이 제거된 텍스트
            """
            metadata = {}

            # 이미지 경로 제거 및 이미지 파일명 추출
            image_pattern = re.compile(r'!\[.*?\]\(images/([^\)]+\.(?:jpg|jpeg|png|gif))\)', re.IGNORECASE)
            image_matches = image_pattern.findall(chunk_text)
            metadata["chunk_images"] = [img for img in image_matches if img]

            # VLM 이미지 요약 추출 및 제거 (metadata에만 저장)
            # 패턴: **[VLM 이미지 요약]**: 로 시작하여 다음 조건 중 하나를 만날 때까지:
            # 1. 다음 VLM 요약 시작 (**[VLM)
            # 2. 헤더 시작 (\n\n#)
            # 3. 빈 줄 2개 이상 후 일반 텍스트 (본문 시작 - "Thank you", "Troubleshooting" 등)
            # 4. 문자열 끝
            # 더 정확한 패턴: VLM 요약은 보통 여러 줄이고, 본문이 시작되면 종료
            vlm_summary_pattern = re.compile(
                r'\*\*\[VLM 이미지 요약\]\*\*:\s*(.*?)(?=\n\n\*\*\[VLM|\n\n#+[^\n]|\n\n(?:Thank|Troubleshooting|Before|Please|Be sure|Operating Instructions)|$)',
                re.DOTALL | re.IGNORECASE
            )
            vlm_summaries = vlm_summary_pattern.findall(chunk_text)
            if vlm_summaries:
                # 모든 VLM 요약을 리스트로 저장
                metadata["vlm_summaries"] = [summary.strip() for summary in vlm_summaries if summary.strip()]
                # VLM 요약을 텍스트에서 제거 (검색 정확도 향상을 위해)
                # 패턴에 매칭되는 전체 블록 제거 (헤더 포함)
                clean_text = vlm_summary_pattern.sub('', chunk_text)
                # 연속된 빈 줄 정리 (3개 이상 → 2개로)
                clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()
            else:
                metadata["vlm_summaries"] = []
                clean_text = chunk_text

            # 이미지 경로 제거 (VLM 요약이 이미 제거된 clean_text 사용)
            chunk_text_no_images = re.sub(r'images/[a-f0-9]+\.(?:jpg|png|gif|jpeg)', '', clean_text, flags=re.IGNORECASE)

            clean_text_for_codes = re.sub(r'[「」]', '', chunk_text_no_images)

            clean_text_for_codes = re.sub(r'\b([A-Z]{1,3})\s*-\s*(\d{2,5})\b', r'\1\2', clean_text_for_codes, flags=re.IGNORECASE)
            code_pattern = re.compile(r"\b([A-Z]{1,3}\d{2,5}|\d{2,5}[A-Z]{0,2}|[A-Z]{2,}\d{2,})\b", re.IGNORECASE)
            codes = code_pattern.findall(clean_text_for_codes)

            # 디버그: 코드 추출 과정 확인
            debug_extraction = os.getenv("DEBUG_CODE_EXTRACTION", "false").lower() == "true"
            if debug_extraction:
                logger.debug(f"추출된 코드: {codes}")

            if codes:
                codes_filtered = {c for c in codes if c.lower() not in {'doc', 'a100', 'b200', 'c300', 'error', 'code', 'list', 'all', 'menu', 'feeder', 'cart', 'specification', 'nozzle', 'head'}}
                codes_filtered = {c for c in codes_filtered if not (c.isdigit() and len(c) < 2)}

                final_codes = sorted(list(codes_filtered))

                # 디버그: 여러 코드 추출 확인
                if debug_extraction:
                    logger.debug(f"코드 필터링: {codes} → {final_codes}")

                if final_codes:
                    metadata["codes"] = final_codes
                    metadata["primary_code"] = final_codes[0]
                    metadata["error_codes"] = final_codes
                    metadata["primary_error_code"] = final_codes[0]
                else:
                    metadata["codes"] = []
                    metadata["primary_code"] = None
                    metadata["error_codes"] = []
                    metadata["primary_error_code"] = None
            else:
                metadata["codes"] = []
                metadata["primary_code"] = None
                metadata["error_codes"] = []
                metadata["primary_error_code"] = None

            # 청크 타입 추출 (clean_text 사용 - VLM 요약 제거된 텍스트)
            chunk_type = "content"
            clean_text_lower = clean_text.lower()

            if clean_text.strip().startswith("#") and len(clean_text) <= 200:
                lines = clean_text.splitlines()
                has_substantial = any(
                    len(line.strip()) >= 20 and not line.strip().startswith("#")
                    for line in lines
                )
                if not has_substantial:
                    chunk_type = "header"

            if "<table>" in clean_text or "|" in clean_text:
                chunk_type = "table"

            error_keywords = ["error", "troubleshooting", "에러", "트러블슈팅", "오류", "해결", "solution", "cause", "phenomenon"]
            if any(kw in clean_text_lower for kw in error_keywords):
                chunk_type = "error_section"

            if re.search(r'#\s*(Cause|Solution|Inspection|Phenomenon)', clean_text, re.IGNORECASE):
                chunk_type = "error_detail"

            # 코드가 있는데 타입이 'content'면 'error_section'으로 강제
            if metadata.get("codes") and chunk_type == "content":
                chunk_type = "error_section"

            metadata["chunk_type"] = chunk_type
            return metadata, clean_text

        docs = []
        previous_codes = []
        previous_error_codes = []
        previous_primary_code = None

        for i, c in enumerate(chunks):
            chunk_metadata, clean_content = extract_chunk_metadata(c)

            current_codes = chunk_metadata.get("codes")
            current_chunk_type = chunk_metadata.get("chunk_type")

            # 1. 이 청크가 자신의 코드를 가진 경우 (부모 청크)
            if current_codes:
                # '방금 본 코드'를 이 청크의 코드로 업데이트
                previous_codes = chunk_metadata["codes"].copy()
                previous_error_codes = chunk_metadata["error_codes"].copy()
                previous_primary_code = chunk_metadata["primary_code"]

            elif not current_codes and previous_primary_code and current_chunk_type in ["error_section", "error_detail", "table"]:
                # '고아 청크'로 판단, 부모의 메타데이터 상속
                chunk_metadata["codes"] = previous_codes.copy()
                chunk_metadata["error_codes"] = previous_error_codes.copy()
                chunk_metadata["primary_code"] = previous_primary_code
                chunk_metadata["primary_error_code"] = previous_primary_code
                if os.getenv("DEBUG_METADATA_FILTERING", "false").lower() == "true":
                    logger.debug(f"청크 #{i}: 고아 청크, codes 상속: {previous_codes}")

            elif current_chunk_type in ["content", "header"]:
                previous_codes = []
                previous_error_codes = []
                previous_primary_code = None

            if not isinstance(chunk_metadata.get("codes"), list):
                chunk_metadata["codes"] = []
            if not isinstance(chunk_metadata.get("error_codes"), list):
                chunk_metadata["error_codes"] = []

            base_metadata = {
                "file": filename,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "equipment_name": equipment_metadata.get("equipment_name"),
                "equipment_model": equipment_metadata.get("equipment_model"),
            }
            
            if clean_content.strip():
                text_metadata = {
                    **base_metadata,
                    "type": "text",
                    **{k: v for k, v in chunk_metadata.items() if k != "vlm_summaries"}
                }
                docs.append(Document(page_content=clean_content, metadata=text_metadata))
            
            vlm_summaries = chunk_metadata.get("vlm_summaries", [])
            chunk_images = chunk_metadata.get("chunk_images", [])
            
            if vlm_summaries and chunk_images:
                vlm_full_text = "\n\n".join(vlm_summaries)
                
                image_metadata = {
                    **base_metadata,
                    "type": "image",
                    "image_paths": chunk_images,
                    "codes": chunk_metadata.get("codes", []),
                    "chunk_images": chunk_images,
                }
                docs.append(Document(page_content=vlm_full_text, metadata=image_metadata))

        vs = get_vectorstore()

        with _UPLOAD_STATUS_LOCK:
            _UPLOAD_STATUS[filename]["message"] = "벡터DB에 저장 중..."
            _UPLOAD_STATUS[filename]["progress"] = 70

        # Qdrant에 문서 추가
        try:
            vs.add_documents(docs)
        except Exception as e:
            logger.error(f"문서 추가 실패: {e}")
            # 개별 문서로 재시도
            for doc in docs:
                try:
                    vs.add_documents([doc])
                    time.sleep(0.1)
                except Exception as e2:
                    logger.error(f"문서 추가 실패: {doc.metadata.get('file', 'unknown')}")

        # Qdrant는 인메모리이므로 별도 저장 불필요
        save_vectorstore()

        # 전체 문서 수 확인
        try:
            from vector_store import get_document_count
            total_docs = get_document_count()
        except Exception:
            total_docs = len(chunks)

        # 메모리에 간단히 목록 보관
        _EMBEDDED_FILES.append(
            {
                "filename": filename,
                "md_path": str(md_path),
                "html_path": str(html_path),
                "chunks": len(chunks),
                "timestamp": time.time(),
            }
        )

        logger.info(f"임베딩 완료: {filename} ({len(chunks)} chunks)")

        with _UPLOAD_STATUS_LOCK:
            _UPLOAD_STATUS[filename] = {
                "status": "completed",
                "message": f"{filename} 업로드 및 임베딩 완료",
                "progress": 100,
                "filename": filename,
                "chunks": len(chunks),
                "md_path": str(md_path),
                "html_path": str(html_path),
                "total_documents": total_docs,
            }

        logger.info(f"업로드 처리 완료: {filename}")
    except Exception as e:
        import traceback
        error_msg = str(e)
        traceback.print_exc()
        logger.error(f"업로드 처리 실패: {filename} - {error_msg}")
        with _UPLOAD_STATUS_LOCK:
            _UPLOAD_STATUS[filename] = {
                "status": "error",
                "message": f"처리 실패: {error_msg}",
                "progress": 0,
                "error": error_msg
            }


def rebuild_vectorstore_from_existing_files():
    """기존 output 디렉터리의 마크다운 파일들을 읽어서 벡터 스토어를 재구성합니다."""
    from config import HOST_OUTPUT_DIR, HOST_INPUT_DIR
    from vector_store import reset_vectorstore, get_vectorstore, save_vectorstore
    from langchain_core.documents import Document
    from md_image import markdown_to_html_inline_images

    logger.info("벡터 스토어 재구성 시작")

    # 벡터 스토어 초기화
    reset_vectorstore()
    vs = get_vectorstore()

    total_chunks = 0
    processed_files = []

    # output 디렉터리의 모든 하위 디렉터리 확인
    for output_dir in HOST_OUTPUT_DIR.iterdir():
        if not output_dir.is_dir():
            continue

        # 마크다운 파일 찾기 (ocr 또는 vlm 디렉터리 내)
        md_path = None
        for subdir_name in ["ocr", "vlm"]:
            subdir = output_dir / subdir_name
            if subdir.exists():
                md_files = list(subdir.glob("*.md"))
                if md_files:
                    md_path = md_files[0]
                    break

        if not md_path or not md_path.exists():
            continue

        # 원본 파일명 찾기 (input 디렉터리에서)
        filename = output_dir.name
        converted_ext = "." + "".join(chr(c) for c in (112, 100, 102))
        input_file = HOST_INPUT_DIR / f"{filename}{converted_ext}"
        if not input_file.exists():
            # 다른 확장자 시도
            for ext in [".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls"]:
                input_file = HOST_INPUT_DIR / f"{filename}{ext}"
                if input_file.exists():
                    filename = f"{filename}{ext}"
                    break
            else:
                # input에 없으면 output 디렉터리명을 파일명으로 사용
                filename = f"{filename}{converted_ext}"

        logger.info(f"재구성: {filename}")

        try:
            # 마크다운 파일 읽기
            md_text = md_path.read_text(encoding="utf-8", errors="ignore")

            # HTML 변환 (이미지 인라인 포함)
            img_dir = md_path.parent / "images"
            html_text = markdown_to_html_inline_images(md_text, img_dir)

            # 청킹 설정
            from config import CHUNK_SIZE, POST_PROCESS_MAX_SIZE
            chunk_size = CHUNK_SIZE
            post_max = POST_PROCESS_MAX_SIZE
            overlap = int(os.getenv("CHUNK_OVERLAP", "200"))

            # 헤더 기반 청킹 실행
            chunks = chunk_text(
                md_text,
                chunk_size=chunk_size,
                overlap=overlap,
                use_chapters=True,
                use_pages=False,
                post_process=True,
                post_process_max_size=post_max,
                post_process_min_size=0,
            )

            # [파일 단위] 장비 정보 추출 (LLM 사용, 1회만 호출)
            equipment_metadata = extract_equipment_metadata_from_file(filename, md_text)
            logger.debug(f"메타데이터: {equipment_metadata.get('equipment_name')}/{equipment_metadata.get('equipment_model')}")

            def extract_chunk_metadata(chunk_text: str) -> tuple[dict, str]:
                """청크에서 에러코드와 타입 추출 (정제 기능 포함)
                
                VLM 이미지 요약을 page_content에서 제거하고 metadata에만 저장 (Multi-Vector 전략)
                
                Returns:
                    (metadata, clean_text): 메타데이터와 VLM 요약이 제거된 텍스트
                """
                metadata = {}

                image_pattern = re.compile(r'!\[.*?\]\(images/([^\)]+\.(?:jpg|jpeg|png|gif))\)', re.IGNORECASE)
                image_matches = image_pattern.findall(chunk_text)
                metadata["chunk_images"] = [img for img in image_matches if img]

                # VLM 이미지 요약 추출 및 제거 (metadata에만 저장)
                vlm_summary_pattern = re.compile(
                    r'\*\*\[VLM 이미지 요약\]\*\*:\s*(.*?)(?=\n\n\*\*\[VLM|\n\n#+[^\n]|\n\n(?:Thank|Troubleshooting|Before|Please|Be sure|Operating Instructions)|$)',
                    re.DOTALL | re.IGNORECASE
                )
                vlm_summaries = vlm_summary_pattern.findall(chunk_text)
                if vlm_summaries:
                    # 모든 VLM 요약을 리스트로 저장
                    metadata["vlm_summaries"] = [summary.strip() for summary in vlm_summaries if summary.strip()]
                    # VLM 요약을 텍스트에서 제거 (검색 정확도 향상을 위해)
                    clean_text = vlm_summary_pattern.sub('', chunk_text)
                    # 연속된 빈 줄 정리 (3개 이상 → 2개로)
                    clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()
                else:
                    metadata["vlm_summaries"] = []
                    clean_text = chunk_text

                # 이미지 경로 제거 (VLM 요약이 이미 제거된 clean_text 사용)
                chunk_text_no_images = re.sub(r'images/[a-f0-9]+\.(?:jpg|png|gif|jpeg)', '', clean_text, flags=re.IGNORECASE)

                clean_text_for_codes = re.sub(r'[「」]', '', chunk_text_no_images)
                clean_text_for_codes = re.sub(r'\b([A-Z]{1,3})\s*-\s*(\d{2,5})\b', r'\1\2', clean_text_for_codes, flags=re.IGNORECASE)
                code_pattern = re.compile(r"\b([A-Z]{1,3}\d{2,5}|\d{2,5}[A-Z]{0,2}|[A-Z]{2,}\d{2,})\b", re.IGNORECASE)
                codes = code_pattern.findall(clean_text_for_codes)

                if codes:
                    codes_filtered = {c for c in codes if c.lower() not in {'doc', 'a100', 'b200', 'c300', 'error', 'code', 'list', 'all', 'menu', 'feeder', 'cart', 'specification', 'nozzle', 'head'}}
                    # 숫자만 있는 경우는 2자리 이상만 코드로 인식
                    codes_filtered = {c for c in codes_filtered if not (c.isdigit() and len(c) < 2)}

                    final_codes = sorted(list(codes_filtered))

                    if final_codes:
                        metadata["codes"] = final_codes
                        metadata["primary_code"] = final_codes[0]
                        metadata["error_codes"] = final_codes
                        metadata["primary_error_code"] = final_codes[0]
                    else:
                        metadata["codes"] = []
                        metadata["primary_code"] = None
                        metadata["error_codes"] = []
                        metadata["primary_error_code"] = None
                else:
                    metadata["codes"] = []
                    metadata["primary_code"] = None
                    metadata["error_codes"] = []
                    metadata["primary_error_code"] = None

                chunk_type = "content"
                clean_text_lower = clean_text.lower()

                if clean_text.strip().startswith("#") and len(clean_text) <= 200:
                    lines = clean_text.splitlines()
                    has_substantial = any(
                        len(line.strip()) >= 20 and not line.strip().startswith("#")
                        for line in lines
                    )
                    if not has_substantial:
                        chunk_type = "header"

                if "<table>" in clean_text or "|" in clean_text:
                    chunk_type = "table"

                error_keywords = ["error", "troubleshooting", "에러", "트러블슈팅", "오류", "해결", "solution", "cause", "phenomenon"]
                if any(kw in clean_text_lower for kw in error_keywords):
                    chunk_type = "error_section"

                if re.search(r'#\s*(Cause|Solution|Inspection|Phenomenon)', clean_text, re.IGNORECASE):
                    chunk_type = "error_detail"

                if metadata.get("codes") and chunk_type == "content":
                    chunk_type = "error_section"

                metadata["chunk_type"] = chunk_type
                return metadata, clean_text, clean_text

            docs = []
            previous_codes = []
            previous_error_codes = []
            previous_primary_code = None

            for i, c in enumerate(chunks):
                chunk_metadata, clean_content = extract_chunk_metadata(c)

                current_codes = chunk_metadata.get("codes")
                current_chunk_type = chunk_metadata.get("chunk_type")

                if current_codes:
                    previous_codes = chunk_metadata["codes"].copy()
                    previous_error_codes = chunk_metadata["error_codes"].copy()
                    previous_primary_code = chunk_metadata["primary_code"]

                elif not current_codes and previous_primary_code and current_chunk_type in ["error_section", "error_detail", "table"]:
                    chunk_metadata["codes"] = previous_codes.copy()
                    chunk_metadata["error_codes"] = previous_error_codes.copy()
                    chunk_metadata["primary_code"] = previous_primary_code
                    chunk_metadata["primary_error_code"] = previous_primary_code
                    if os.getenv("DEBUG_METADATA_FILTERING", "false").lower() == "true":
                        logger.debug(f"청크 #{i}: 고아 청크, codes 상속: {previous_codes}")

                else:
                    previous_codes = []
                    previous_error_codes = []
                    previous_primary_code = None

                if not isinstance(chunk_metadata.get("codes"), list):
                    chunk_metadata["codes"] = []
                if not isinstance(chunk_metadata.get("error_codes"), list):
                    chunk_metadata["error_codes"] = []

                base_metadata = {
                    "file": filename,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "equipment_name": equipment_metadata.get("equipment_name"),
                    "equipment_model": equipment_metadata.get("equipment_model"),
                }
                
                if clean_content.strip():
                    text_metadata = {
                        **base_metadata,
                        "type": "text",
                        **{k: v for k, v in chunk_metadata.items() if k != "vlm_summaries"}
                    }
                    docs.append(Document(page_content=clean_content, metadata=text_metadata))
                
                vlm_summaries = chunk_metadata.get("vlm_summaries", [])
                chunk_images = chunk_metadata.get("chunk_images", [])
                
                if vlm_summaries and chunk_images:
                    vlm_full_text = "\n\n".join(vlm_summaries)
                    
                    image_metadata = {
                        **base_metadata,
                        "type": "image",
                        "image_paths": chunk_images,
                        "codes": chunk_metadata.get("codes", []),
                        "chunk_images": chunk_images,
                    }
                    docs.append(Document(page_content=vlm_full_text, metadata=image_metadata))

            # 벡터 스토어에 추가
            for doc in docs:
                try:
                    vs.add_documents([doc])
                except Exception as e:
                    logger.error(f"문서 추가 실패: {doc.metadata.get('file')}")

            total_chunks += len(docs)
            processed_files.append(filename)
            logger.info(f"재구성 완료: {filename} ({len(docs)} chunks)")

        except Exception as e:
            logger.error(f"처리 실패: {filename} - {e}")

    # 벡터 스토어 저장
    save_vectorstore()

    logger.info(f"벡터 스토어 재구성 완료: {len(processed_files)}개 파일, {total_chunks}개 청크")
    return {
        "processed_files": processed_files,
        "total_chunks": total_chunks,
        "message": f"{len(processed_files)}개 파일에서 {total_chunks}개 청크를 재구성했습니다."
    }
