# config.py
# -*- coding: utf-8 -*-
"""
설정 상수 및 MinerU 문서 처리 모듈
- 환경 설정 (디렉토리, 모델, 청킹 설정)
- Docker 컨테이너 관리
- 문서 파일을 MinerU를 사용하여 마크다운으로 변환
"""

import os
import re
import subprocess
import shlex
import time
import logging
from pathlib import Path
from typing import Dict, Optional
from fastapi import HTTPException

# 로깅 설정
logger = logging.getLogger(__name__)

# 이미지 요약에 필요한 라이브러리 (필요시에만 import)
try:
    import requests
    import base64
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    requests = None
    base64 = None

# Docker 컨테이너 설정
MINERU_CONTAINER = os.getenv("MINERU_CONTAINER", "mineru-vllm")

# 디렉토리 구조 (.env 파일에서 설정 필수)
_base_dir = os.getenv("BASE_DIR")
if not _base_dir:
    raise ValueError("BASE_DIR 환경 변수가 설정되지 않았습니다. .env 파일을 확인하세요.")
BASE_DIR = Path(_base_dir)
HOST_INPUT_DIR = BASE_DIR / "input"
HOST_OUTPUT_DIR = BASE_DIR / "output"
CHAT_HISTORY_DIR = BASE_DIR / "chat_history"
CHAT_HISTORY_FILE = CHAT_HISTORY_DIR / "history.json"

# Docker 컨테이너 내부 경로 (.env 파일에서 설정 필수)
# 빈 문자열("")이면 루트 경로 사용 (예: /input, /output)
CONTAINER_BASE_DIR = os.getenv("CONTAINER_BASE_DIR")
if CONTAINER_BASE_DIR is None:
    raise ValueError("CONTAINER_BASE_DIR 환경 변수가 설정되지 않았습니다. .env 파일을 확인하세요.")
# 빈 문자열이면 기본값 설정하지 않음 (루트 경로 사용)

# 디렉토리 생성 및 권한 설정
for d in [HOST_INPUT_DIR, HOST_OUTPUT_DIR, CHAT_HISTORY_DIR]:
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o777)

MACHINE_TYPES = {'A100', 'B200', 'C300'}

# ==========================================================
# RAG 쿼리 핸들러 설정
# ==========================================================
# 파일명 접두사 패턴 (파일명이 이 접두사로 시작할 수 있음)
FILE_PREFIX_PATTERNS = ['doc', 'DOC']  # 예: "DOC-A100", "doc-B200" 등

FILENAME_PATTERN_MAPPING = {}

# 장비 관련 키워드 (질문에서 장비를 나타내는 단어)
MACHINE_KEYWORDS = ['장비', '기계']  

# 필터에서 제외할 키워드 (에러 코드로 인식하지 않을 단어)
EXCLUDED_KEYWORDS = {
    'DOC', 'ERROR', 'CODE', 'LIST', 'ALL', 'MENU',
    'FEEDER', 'CART', 'SPECIFICATION', 'NOZZLE', 'HEAD'
}

# 목록 질문 키워드
LIST_QUERY_KEYWORDS = ["목록", "리스트", "전부"]

# 인사말 키워드
GREETING_KEYWORDS = ["안녕", "hello", "hi", "반가워", "안녕하세요"]

# 부정 키워드 (제외/부정 질문 감지용)
NEGATION_KEYWORDS = ['아닌', '말고', '제외하고', 'not', 'except']

# 숫자 설정값
MIN_CODE_LENGTH = 2  # 최소 코드 길이 
MAX_RANGE_CODES = 100  # 범위 질문 최대 코드 수 (40001~40100 = 100개)
MAX_CODE_FILTER_COUNT = 10  # 코드 필터 최대 개수 (10개 이상이면 필터 미적용)

# 임베딩 모델: bge-m3 (환경 변수에서 읽어옴)
EMBED_MODEL = os.getenv("EMBED_MODEL")
if not EMBED_MODEL:
    raise ValueError("EMBED_MODEL 환경 변수가 설정되지 않았습니다.")

# LLM 모델 (.env 필수)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")
if not OLLAMA_MODEL:
    raise ValueError("OLLAMA_MODEL 환경 변수가 설정되지 않았습니다. .env 파일을 확인하세요.")

# 이미지 요약 생성 활성화/비활성화 (.env 옵션, 기본값: false)
ENABLE_IMAGE_SUMMARY = os.getenv("ENABLE_IMAGE_SUMMARY", "false").lower() in ("true", "1", "yes")

# 청킹 설정 (.env 필수)
try:
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE"))
    POST_PROCESS_MAX_SIZE = int(os.getenv("POST_PROCESS_MAX_SIZE"))
    POST_PROCESS_MIN_SIZE = int(os.getenv("POST_PROCESS_MIN_SIZE"))
except (TypeError, ValueError):
    raise ValueError("CHUNK_SIZE, POST_PROCESS_MAX_SIZE, POST_PROCESS_MIN_SIZE 환경 변수가 올바르게 설정되지 않았습니다. .env 파일을 확인하세요.")

# ============================================================
# Docker 컨테이너 관리
# ============================================================

def check_container_running(container_name: str) -> bool:
    """컨테이너가 실행 중인지 확인"""
    try:
        proc = subprocess.run(
            ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
            text=True,
            capture_output=True,
        )
        return container_name in proc.stdout
    except Exception:
        return False


def start_container(container_name: str):
    """컨테이너 시작"""
    if check_container_running(container_name):
        logger.info(f"컨테이너 {container_name} 이미 실행 중")
        return

    logger.info(f"컨테이너 {container_name} 시작 중...")
    try:
        proc = subprocess.run(
            ["docker", "start", container_name],
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"컨테이너 시작 실패: {proc.stderr}")

        # 컨테이너가 완전히 시작될 때까지 대기
        for i in range(30):  # 최대 30초 대기
            if check_container_running(container_name):
                time.sleep(1)  # 1초 더 대기하여 완전히 준비되도록
                logger.info(f"컨테이너 {container_name} 시작 완료")
                return
            time.sleep(1)

        raise RuntimeError(f"컨테이너 {container_name} 시작 확인 실패")
    except Exception as e:
        raise HTTPException(500, f"컨테이너 시작 실패: {str(e)}")


def stop_container(container_name: str):
    """컨테이너 중지"""
    if not check_container_running(container_name):
        logger.info(f"컨테이너 {container_name} 이미 중지됨")
        return

    logger.info(f"컨테이너 {container_name} 중지 중...")
    try:
        proc = subprocess.run(
            ["docker", "stop", container_name],
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            logger.warning(f"컨테이너 중지 실패 (무시): {proc.stderr}")
        else:
            logger.info(f"컨테이너 {container_name} 중지 완료")
    except Exception as e:
        logger.warning(f"컨테이너 중지 중 오류 발생 (무시): {str(e)}")


# ============================================================
# MinerU 전용 함수들
# ============================================================


def is_office_file(ext: str) -> bool:
    """확장자가 Word/PPT/Excel 계열인지 확인."""
    return ext.lower() in {"doc", "docx", "ppt", "pptx", "xls", "xlsx"}


def run_in_container(cmd: str):
    """지정된 MINERU 컨테이너 안에서 bash 명령을 실행한다."""
    proc = subprocess.run(
        ["docker", "exec", MINERU_CONTAINER, "bash", "-lc", cmd],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        error_output = proc.stdout if proc.stdout else "Unknown error"

        # GPU 메모리 부족 에러 감지
        if ("Free memory on device" in error_output and "less than desired GPU memory" in error_output) or \
           "No available memory for the cache blocks" in error_output:
            raise HTTPException(
                503,
                "GPU 메모리가 부족합니다. 다른 프로세스가 GPU를 사용 중이거나 MinerU의 GPU 메모리 사용률 설정이 너무 높습니다. "
                "다른 GPU 프로세스를 종료하거나 잠시 후 다시 시도해주세요."
            )

        # Engine core 초기화 실패 에러
        if "Engine core initialization failed" in error_output:
            if "GPU memory" in error_output or "Free memory" in error_output or "No available memory for the cache blocks" in error_output:
                raise HTTPException(
                    503,
                    "GPU 메모리 부족으로 MinerU 엔진을 시작할 수 없습니다. 다른 GPU 프로세스를 종료하거나 잠시 후 다시 시도해주세요."
                )
            else:
                raise HTTPException(
                    500,
                    f"MinerU 엔진 초기화에 실패했습니다. 컨테이너 로그를 확인해주세요.\n{error_output[:500]}"
                )

        raise RuntimeError(f"[container error]\ncmd: {cmd}\n{error_output[:1000]}")


def lang_score_from_md(md_text: str) -> Dict[str, int]:
    """
    MinerU가 뽑아준 md가 어떤 언어 비중인지 간단히 세어서
    한글이 많으면 한국어 OCR 파이프라인을 한 번 더 태우기 위함.
    """
    hangul = len(re.findall(r"[가-힣]", md_text))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", md_text))
    latin = len(re.findall(r"[A-Za-z]", md_text))
    return {"hangul": hangul, "cjk": cjk, "latin": latin}


def convert_html_tables_to_text(md_text: str) -> str:
    """
    마크다운 텍스트 내의 HTML 테이블을 순수 텍스트 형식으로 변환합니다.
    테이블 구조를 유지하지 않고 읽기 쉬운 텍스트로 변환합니다.

    Args:
        md_text: HTML 테이블이 포함된 마크다운 텍스트

    Returns:
        HTML 테이블이 텍스트로 변환된 마크다운 텍스트
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("beautifulsoup4가 설치되지 않아 HTML 테이블 변환을 건너뜁니다.")
        return md_text

    # HTML 테이블 패턴 찾기 (대소문자 구분 없이)
    table_pattern = r'<table[^>]*>.*?</table>'
    tables = re.findall(table_pattern, md_text, re.DOTALL | re.IGNORECASE)

    if not tables:
        return md_text

    logger.info(f"{len(tables)}개의 HTML 테이블을 텍스트로 변환 중")
    result_text = md_text
    for html_table in tables:
        try:
            soup = BeautifulSoup(html_table, 'html.parser')
            table = soup.find('table')

            if not table:
                continue

            # 모든 행 추출
            all_rows = list(table.find_all('tr'))

            # 헤더 행 찾기 및 컬럼 인덱스 매핑
            header_row = None
            header_cols = []
            data_start_idx = 0
            is_error_code_table = False  # Error Code 테이블인지 여부

            for idx, tr in enumerate(all_rows):
                cells = tr.find_all(['td', 'th'])
                cell_texts = [cell.get_text(strip=True) for cell in cells]

                # "Error Code" 또는 "Error Message"가 포함된 행을 헤더로 인식
                if any('error code' in text.lower() or 'error message' in text.lower() for text in cell_texts):
                    header_row = tr
                    header_cols = cell_texts
                    data_start_idx = idx + 1
                    is_error_code_table = True  # Error Code 테이블로 표시
                    break

            # rowspan 추적: {col_idx: {'text': value, 'remaining': count}}
            rowspan_tracker = {}

            text_blocks = []
            current_error_code = None
            current_error_message = None
            current_sections = {}  # {section_name: [values]}

            # 헤더 컬럼 인덱스 매핑
            header_map = {}
            for idx, header_text in enumerate(header_cols):
                header_lower = header_text.lower()
                if 'error code' in header_lower:
                    header_map['error_code'] = idx
                elif 'error message' in header_lower:
                    header_map['error_message'] = idx
                elif 'cause' in header_lower:
                    header_map['cause'] = idx
                elif 'solution' in header_lower or 'inspection' in header_lower:
                    header_map['solution'] = idx

            # 데이터 행 처리
            for row_idx in range(data_start_idx, len(all_rows)):
                tr = all_rows[row_idx]
                cells = tr.find_all(['td', 'th'])

                # 현재 행의 셀들을 컬럼 인덱스에 매핑
                row_cells = {}  # {col_idx: text}
                col_idx = 0

                for cell in cells:
                    cell_rowspan = int(cell.get('rowspan', 1))
                    cell_colspan = int(cell.get('colspan', 1))
                    cell_text = ' '.join(cell.stripped_strings).strip()

                    # rowspan이 남아있는 셀 처리
                    while col_idx in rowspan_tracker and rowspan_tracker[col_idx]['remaining'] > 0:
                        row_cells[col_idx] = rowspan_tracker[col_idx]['text']
                        rowspan_tracker[col_idx]['remaining'] -= 1
                        if rowspan_tracker[col_idx]['remaining'] == 0:
                            del rowspan_tracker[col_idx]
                        col_idx += 1

                    # 현재 셀 처리
                    if cell_text:  # 빈 셀이 아닌 경우만
                        for c in range(cell_colspan):
                            row_cells[col_idx + c] = cell_text

                        # rowspan이 1보다 크면 추적
                        if cell_rowspan > 1:
                            for c in range(cell_colspan):
                                rowspan_tracker[col_idx + c] = {
                                    'text': cell_text,
                                    'remaining': cell_rowspan - 1
                                }

                    col_idx += cell_colspan

                # 헤더 매핑에 따라 row_data 구성
                row_data = {}
                if 'error_code' in header_map and header_map['error_code'] in row_cells:
                    row_data['error_code'] = row_cells[header_map['error_code']]
                if 'error_message' in header_map and header_map['error_message'] in row_cells:
                    row_data['error_message'] = row_cells[header_map['error_message']]
                if 'cause' in header_map and header_map['cause'] in row_cells:
                    row_data['cause'] = row_cells[header_map['cause']]
                if 'solution' in header_map and header_map['solution'] in row_cells:
                    row_data['solution'] = row_cells[header_map['solution']]

                # Error Code 번호 추출 (숫자만 또는 숫자로 시작)
                error_code_match = None
                if 'error_code' in row_data:
                    error_code_text = row_data['error_code']
                    # 숫자만 있는지 확인
                    if error_code_text.strip().isdigit():
                        error_code_match = error_code_text.strip()
                    else:
                        # 숫자 패턴 추출
                        match = re.search(r'(\d{4,5})', error_code_text)
                        if match:
                            error_code_match = match.group(1)

                # Error Code 테이블인 경우에만 Error Code 형식으로 처리
                if is_error_code_table and error_code_match:
                    # 이전 항목 저장
                    if current_error_code:
                        block = f"Error Code {current_error_code}\n"
                        if current_error_message:
                            block += f"{current_error_message}\n"
                        block += "\n"

                        section_list = list(current_sections.items())
                        for section_name, section_values in section_list:
                            if section_values:
                                block += f"{section_name}\n"
                                for val in section_values:
                                    val_clean = val.strip()
                                    if val_clean:
                                        if re.match(r'^\d+\)', val_clean):
                                            block += f"- {val_clean}\n"
                                        elif val_clean.startswith('-'):
                                            block += f"{val_clean}\n"
                                        else:
                                            block += f"- {val_clean}\n"
                        text_blocks.append(block)

                    # 새 항목 시작
                    current_error_code = error_code_match
                    current_error_message = row_data.get('error_message', '').strip()
                    current_sections = {}

                    # Cause와 Solution 추가
                    if 'cause' in row_data and row_data['cause']:
                        current_sections['Cause'] = [row_data['cause']]
                    if 'solution' in row_data and row_data['solution']:
                        current_sections['Inspection and Solution'] = [row_data['solution']]
                elif is_error_code_table:
                    # Error Code 테이블이지만 Error Code가 없으면 현재 항목에 섹션 추가
                    if current_error_code:
                        if 'cause' in row_data and row_data['cause']:
                            if 'Cause' not in current_sections:
                                current_sections['Cause'] = []
                            current_sections['Cause'].append(row_data['cause'])
                        if 'solution' in row_data and row_data['solution']:
                            if 'Inspection and Solution' not in current_sections:
                                current_sections['Inspection and Solution'] = []
                            current_sections['Inspection and Solution'].append(row_data['solution'])
                        if 'error_message' in row_data and row_data['error_message']:
                            current_error_message = row_data['error_message']

            # Error Code 테이블인 경우에만 마지막 항목 저장
            if is_error_code_table and current_error_code:
                block = f"Error Code {current_error_code}\n"
                if current_error_message:
                    block += f"{current_error_message}\n"
                block += "\n"

                section_list = list(current_sections.items())
                for section_name, section_values in section_list:
                    if section_values:
                        block += f"{section_name}\n"
                        for val in section_values:
                            val_clean = val.strip()
                            if val_clean:
                                if re.match(r'^\d+\)', val_clean):
                                    block += f"- {val_clean}\n"
                                elif val_clean.startswith('-'):
                                    block += f"{val_clean}\n"
                                else:
                                    block += f"- {val_clean}\n"
                text_blocks.append(block)

            # Error Code 테이블이 아닌 경우 일반 테이블 형식으로 변환
            if not text_blocks and len(all_rows) > 0:
                # rowspan을 고려하여 일반 테이블 변환
                general_rowspan_tracker = {}  # {col_index: {'text': value, 'remaining': count}}
                general_blocks = []
                current_group = None
                current_items = []

                # 첫 번째 행이 헤더인지 확인
                first_row = all_rows[0]
                is_header_row = any(cell.name == 'th' for cell in first_row.find_all(['td', 'th']))
                start_idx = 1 if is_header_row else 0

                for idx in range(start_idx, len(all_rows)):
                    tr = all_rows[idx]
                    row_cells = []
                    col_idx = 0

                    for cell in tr.find_all(['td', 'th']):
                        # rowspan이 남아있는 셀 처리
                        while col_idx in general_rowspan_tracker and general_rowspan_tracker[col_idx]['remaining'] > 0:
                            row_cells.append({
                                'text': general_rowspan_tracker[col_idx]['text'],
                                'rowspan': general_rowspan_tracker[col_idx]['remaining'],
                                'is_continued': True,
                                'col_idx': col_idx
                            })
                            general_rowspan_tracker[col_idx]['remaining'] -= 1
                            if general_rowspan_tracker[col_idx]['remaining'] == 0:
                                del general_rowspan_tracker[col_idx]
                            col_idx += 1

                        # 현재 셀 처리
                        text = ' '.join(cell.stripped_strings).strip()
                        rowspan = int(cell.get('rowspan', 1))
                        colspan = int(cell.get('colspan', 1))

                        row_cells.append({
                            'text': text,
                            'rowspan': rowspan,
                            'colspan': colspan,
                            'is_continued': False,
                            'col_idx': col_idx
                        })

                        # rowspan이 1보다 크면 추적
                        if rowspan > 1:
                            general_rowspan_tracker[col_idx] = {
                                'text': text,
                                'remaining': rowspan - 1
                            }

                        # colspan 처리
                        for _ in range(colspan - 1):
                            col_idx += 1
                            row_cells.append({
                                'text': '',
                                'rowspan': 1,
                                'colspan': 1,
                                'is_continued': False,
                                'col_idx': col_idx
                            })

                        col_idx += 1

                    if not row_cells:
                        continue

                    # 빈 셀("-" 또는 빈 문자열) 필터링
                    non_empty_cells = [cell for cell in row_cells if cell['text'] and cell['text'].strip() and cell['text'].strip() != '-']

                    if not non_empty_cells:
                        continue

                    # 첫 번째 셀 확인
                    first_cell = row_cells[0] if row_cells else None
                    first_cell_text = first_cell['text'] if first_cell and first_cell['text'] else ""
                    first_cell_is_continued = first_cell.get('is_continued', False) if first_cell else False
                    first_cell_has_rowspan = first_cell.get('rowspan', 1) > 1 if first_cell else False

                    # 첫 번째 셀이 그룹명인 경우 (rowspan이 있고 연속된 셀이 아니거나, 긴 텍스트)
                    if first_cell_text and first_cell_text.strip() != '-' and (first_cell_has_rowspan or (not first_cell_is_continued and len(first_cell_text) > 15)):
                        # 이전 그룹 저장
                        if current_group:
                            block = f"{current_group}\n"
                            if current_items:
                                block += "\n".join([f"- {item}" if not item.startswith('-') else item for item in current_items])
                            general_blocks.append(block)

                        current_group = first_cell_text
                        current_items = []

                        # 나머지 셀들을 항목으로 추가 (빈 셀 제외)
                        item_parts = []
                        for cell_data in row_cells[1:]:
                            cell_text = cell_data['text'].strip()
                            if cell_text and cell_text != '-':
                                item_parts.append(cell_text)
                        if item_parts:
                            current_items.append(" - ".join(item_parts))
                    elif first_cell_is_continued or (not first_cell_text or first_cell_text.strip() == '-'):
                        # 첫 번째 셀이 연속된 셀이거나 비어있으면 현재 그룹에 항목 추가
                        # 첫 번째 셀은 그룹명이므로 제외하고 나머지만 항목으로 추가
                        if current_group:
                            item_parts = []
                            for cell_data in row_cells[1:]:  # 첫 번째 셀 제외
                                cell_text = cell_data['text'].strip()
                                if cell_text and cell_text != '-':
                                    item_parts.append(cell_text)
                            if item_parts:
                                current_items.append(" - ".join(item_parts))
                    else:
                        # 일반 행 처리
                        item_parts = []
                        for cell_data in row_cells:
                            cell_text = cell_data['text'].strip()
                            if cell_text and cell_text != '-':
                                item_parts.append(cell_text)

                        if item_parts:
                            if current_group:
                                # 현재 그룹에 항목 추가
                                current_items.append(" - ".join(item_parts))
                            else:
                                # 그룹이 없으면 첫 번째 셀을 그룹명으로
                                if len(item_parts) > 1:
                                    current_group = item_parts[0]
                                    current_items.append(" - ".join(item_parts[1:]))
                                else:
                                    # 그룹이 없고 항목이 하나면 그대로 추가
                                    current_items.append(item_parts[0])

                # 마지막 그룹 저장
                if current_group:
                    block = f"{current_group}\n"
                    if current_items:
                        block += "\n".join([f"- {item}" if not item.startswith('-') else item for item in current_items])
                    general_blocks.append(block)
                elif current_items:
                    # 그룹이 없고 항목만 있는 경우
                    block = "\n".join([f"- {item}" if not item.startswith('-') else item for item in current_items])
                    general_blocks.append(block)

                if general_blocks:
                    text_blocks = general_blocks

            if text_blocks:
                # 각 블록 끝의 빈 줄 제거 후 Error Code 항목 사이에 빈 줄 추가
                cleaned_blocks = []
                for i, block in enumerate(text_blocks):
                    cleaned_block = block.rstrip()
                    # Error Code로 시작하는 블록이고 이전 블록도 Error Code로 시작하면 빈 줄 추가
                    if i > 0 and cleaned_block.startswith("Error Code") and cleaned_blocks and cleaned_blocks[-1].startswith("Error Code"):
                        cleaned_blocks.append("")  # 빈 줄 추가
                    cleaned_blocks.append(cleaned_block)
                text_content = "\n".join(cleaned_blocks)
                # HTML 테이블을 텍스트로 교체 (한 번만)
                result_text = result_text.replace(html_table, "\n" + text_content + "\n", 1)

        except Exception as e:
            logger.warning(f"테이블 변환 실패 (무시): {e}")
            continue

    return result_text


def process_with_mineru(filename: str) -> Path:
    """
    1) 파일명을 안전한 이름으로 변환
    2) 업로드된 파일이 Office 계열이면 MinerU 입력 형식으로 먼저 변환
    3) MinerU의 vllm 엔진으로 1차 md 생성
    4) 문서가 한글/CJK 위주면 pipeline ocr korean 으로 다시 한 번 돌림
    5) 최종적으로 사용할 md 파일의 경로를 리턴
    """
    # MinerU 환경 변수 설정 (AI_KnowledgeOps 환경에 최적화)
    # 모든 MinerU 실행에 공통으로 적용
    env_vars = [
        "MINERU_MODEL_SOURCE=local",  # 로컬 모델 사용
        "MINERU_DEVICE_MODE=cuda:0",  # GPU 사용
        "MINERU_TABLE_ENABLE=true",  # 테이블 파싱 활성화
        "MINERU_FORMULA_ENABLE=true",  # 수식 파싱 활성화
        "MINERU_RENDER_TIMEOUT=600",
        "MINERU_TABLE_MERGE_ENABLE=true",  # 테이블 병합 활성화
        "VLLM_GPU_MEMORY_UTILIZATION=0.3",  # GPU 메모리 사용률 30%로 제한
    ]

    # 컨테이너 시작
    try:
        start_container(MINERU_CONTAINER)
    except Exception as e:
        raise HTTPException(500, f"MinerU 컨테이너 시작 실패: {str(e)}")

    try:
        ext = Path(filename).suffix.lower()
        in_path = HOST_INPUT_DIR / filename
        original_stem = Path(filename).stem  # 원본 파일명 (확장자 제외)

        # Office면 MinerU 입력 형식으로 변환 (원본 파일명 유지)
        if is_office_file(ext.lstrip(".")):
            logger.info(f"LibreOffice 변환: {filename}")
            document_format = "".join(chr(c) for c in (112, 100, 102))
            container_in_path = f"{CONTAINER_BASE_DIR}/input/{filename}"
            run_in_container(
                f"libreoffice --headless --convert-to {document_format} --outdir {CONTAINER_BASE_DIR}/input {shlex.quote(container_in_path)}"
            )
            in_path = HOST_INPUT_DIR / f"{original_stem}.{document_format}"

        # 컨테이너 내부 경로 설정 (빈 문자열이면 루트 경로 사용)
        if CONTAINER_BASE_DIR:
            container_input_path = f"{CONTAINER_BASE_DIR}/input/{in_path.name}"
            container_output_dir = f"{CONTAINER_BASE_DIR}/output"
        else:
            container_input_path = f"/input/{in_path.name}"
            container_output_dir = "/output"

        # 결과 폴더는 원본 파일명으로 생성 (Docker 컨테이너 내부에서)
        vlm_dir = HOST_OUTPUT_DIR / original_stem / "vlm"
        container_vlm_dir = f"{container_output_dir}/{original_stem}/vlm"
        try:
            run_in_container(f"mkdir -p {shlex.quote(container_vlm_dir)} && chmod -R u+rwX,g+rwX,o-rwx {shlex.quote(container_vlm_dir)}")
        except Exception as e:
            logger.warning(f"VLM 폴더 생성 실패 (무시): {e}")
        
        logger.info(f"MinerU(VLM) 실행: {in_path}")
        logger.info(f"컨테이너 경로: {container_input_path}")

        env_export = " && ".join([f"export {var}" for var in env_vars])

        # 전체 페이지 처리 (페이지 범위 옵션 제거)
        cmd = (
            f"{env_export} && "
            f"mineru -p {shlex.quote(container_input_path)} -o {container_output_dir} "
            "-b vlm-auto-engine -t true -f true "
            "--gpu-memory-utilization 0.3 "
        )

        # 실시간 출력을 위해 Popen 사용
        proc = subprocess.Popen(
            ["docker", "exec", MINERU_CONTAINER, "bash", "-lc", cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        # 실시간 출력 스트리밍
        output_lines = []
        error_detected = False

        try:
            for line in proc.stdout:
                line = line.rstrip()
                if line.strip():
                    logger.info(f"MinerU: {line}")
                output_lines.append(line)

                # GPU 메모리 에러 실시간 감지
                if "No available memory for the cache blocks" in line or "Free memory on device" in line:
                    error_detected = True
                    break

            proc.wait()

            if proc.returncode != 0 or error_detected:
                if error_detected:
                    raise HTTPException(
                        503,
                        "GPU 메모리가 부족합니다. 다른 프로세스가 GPU를 사용 중이거나 MinerU의 GPU 메모리 사용률 설정이 너무 높습니다. "
                        "다른 GPU 프로세스를 종료하거나 잠시 후 다시 시도해주세요."
                    )
                else:
                    error_output = "\n".join(output_lines[-50:])
                    raise HTTPException(500, f"MinerU 실행 실패: returncode={proc.returncode}\n{error_output}")
        except HTTPException:
            raise
        except Exception as e:
            if proc.poll() is None:
                proc.kill()
            raise HTTPException(500, f"MinerU 실행 중 오류 발생: {str(e)}")

        logger.info("MinerU 실행 완료")

        # 생성된 output 디렉토리 전체 소유권 및 권한 변경 (컨테이너 내부에서)
        try:
            output_chmod_path = f"{container_output_dir}/{original_stem}"
            # chown과 제한된 chmod를 함께 실행 (1000:1000은 일반적인 첫 번째 사용자의 UID:GID)
            run_in_container(
                f"if [ -d {shlex.quote(output_chmod_path)} ]; then "
                f"chown -R 1000:1000 {shlex.quote(output_chmod_path)} && "
                f"chmod -R u+rwX,g+rwX,o-rwx {shlex.quote(output_chmod_path)}; fi"
            )
            logger.info(f"소유권 및 권한 변경 완료: {output_chmod_path}")
        except Exception as e:
            logger.warning(f"chown/chmod skip: {e}")

        # md 찾기
        vlm_md_files = list(vlm_dir.glob("*.md"))

        if not vlm_md_files:
            logger.error(f"예상 경로에 md 파일 없음: {vlm_dir}")
            # 해당 파일명과 일치하는 디렉토리만 검색
            expected_output_dir = HOST_OUTPUT_DIR / original_stem
            if expected_output_dir.exists():
                vlm_subdir = expected_output_dir / "vlm"
                if vlm_subdir.exists():
                    md_files = list(vlm_subdir.glob("*.md"))
                    if md_files:
                        logger.info(f"예상 디렉토리에서 md 파일 찾음: {md_files[0]}")
                        vlm_md_files = md_files

            if not vlm_md_files:
                error_msg = f"vllm 모드에서 Markdown 파일이 생성되지 않았습니다. 예상 경로: {vlm_dir}"
                logger.error(error_msg)
                raise HTTPException(500, error_msg)

        vlm_md_path = vlm_md_files[0]
        logger.info(f"md 파일 찾음: {vlm_md_path}")

        # 언어 비중 보고 ocr 파이프라인 돌릴지 먼저 판단 (테이블 변환 전)
        vlm_md_content = vlm_md_path.read_text(encoding="utf-8", errors="ignore")
        score = lang_score_from_md(vlm_md_content)

        need_pipeline = False
        if score["hangul"] >= 40 or (score["cjk"] >= 80 and score["latin"] < 800):
            need_pipeline = True

        if need_pipeline:
            # OCR 결과 폴더 미리 생성 (원본 파일명으로, Docker 컨테이너 내부에서)
            ocr_dir = HOST_OUTPUT_DIR / original_stem / "ocr"
            container_ocr_dir = f"{container_output_dir}/{original_stem}/ocr"
            try:
                run_in_container(f"mkdir -p {shlex.quote(container_ocr_dir)} && chmod -R u+rwX,g+rwX,o-rwx {shlex.quote(container_ocr_dir)}")
            except Exception as e:
                logger.warning(f"OCR 폴더 생성 실패 (무시): {e}")
            
            logger.info(f"OCR 파이프라인 실행: {in_path}")
            logger.info(f"컨테이너 경로: {container_input_path}")
            # MinerU OCR 실행 시에도 동일한 환경 변수 적용
            env_export_ocr = " && ".join([f"export {var}" for var in env_vars])

            # 전체 페이지 처리 (페이지 범위 옵션 제거)
            cmd = " ".join(
                [
                    f"{env_export_ocr} && mineru",
                    "-p",
                    shlex.quote(container_input_path),
                    "-o",
                    container_output_dir,
                    "-b",
                    "pipeline",
                    "-m",
                    "ocr",
                    "-l",
                    "korean",
                    "-t",
                    "true",
                    "-f",
                    "true",
                ]
            )

            # 실시간 출력을 위해 Popen 사용
            proc = subprocess.Popen(
                ["docker", "exec", MINERU_CONTAINER, "bash", "-lc", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            try:
                for line in proc.stdout:
                    line = line.rstrip()
                    if line.strip():
                        logger.info(f"MinerU OCR: {line}")
                proc.wait()

                if proc.returncode != 0:
                    logger.warning(f"OCR 파이프라인 실행 실패: returncode={proc.returncode}")
            except Exception as e:
                if proc.poll() is None:
                    proc.kill()
                logger.warning(f"OCR 파이프라인 실행 중 오류: {e}")

            if ocr_dir.exists():
                # OCR 결과 디렉토리 소유권 및 권한 변경
                try:
                    ocr_chmod_path = f"{container_output_dir}/{original_stem}/ocr"
                    run_in_container(
                        f"if [ -d {shlex.quote(ocr_chmod_path)} ]; then "
                        f"chown -R 1000:1000 {shlex.quote(ocr_chmod_path)} && "
                        f"chmod -R u+rwX,g+rwX,o-rwx {shlex.quote(ocr_chmod_path)}; fi"
                    )
                    logger.info(f"OCR 소유권 및 권한 변경 완료: {ocr_chmod_path}")
                except Exception as e:
                    logger.warning(f"chown/chmod skip (ocr): {e}")

                ocr_md_files = list(ocr_dir.glob("*.md"))
                if ocr_md_files:
                    ocr_md_path = ocr_md_files[0]
                    # HTML 테이블을 순수 텍스트로 변환 (최종 결과에만 적용)
                    ocr_md_content = ocr_md_path.read_text(encoding="utf-8", errors="ignore")
                    ocr_md_content = convert_html_tables_to_text(ocr_md_content)
                    
                    # 파일 쓰기 전 권한 다시 한 번 확인
                    try:
                        ocr_md_path.write_text(ocr_md_content, encoding="utf-8")
                    except PermissionError:
                        logger.warning("권한 문제로 재시도...")
                        ocr_file_path = f"{container_output_dir}/{original_stem}/ocr/{ocr_md_path.name}"
                        run_in_container(
                            f"chown 1000:1000 {shlex.quote(ocr_file_path)} && "
                            f"chmod 777 {shlex.quote(ocr_file_path)}"
                        )
                        ocr_md_path.write_text(ocr_md_content, encoding="utf-8")
                    
                    logger.info("OCR 마크다운 HTML 테이블 변환 완료")
                    logger.info(f"OCR 결과 사용: {ocr_md_path}")
                    return ocr_md_path
                else:
                    logger.warning("OCR md가 없어서 VLM 결과 사용")
            else:
                logger.warning("OCR 디렉터리가 없어서 VLM 결과 사용")

        # vllm 결과 사용 시에도 테이블 변환 적용 (korean이 아닌 경우)
        vlm_md_content = vlm_md_path.read_text(encoding="utf-8", errors="ignore")
        vlm_md_content = convert_html_tables_to_text(vlm_md_content)
        
        # 파일 쓰기 전 권한 다시 한 번 확인
        try:
            vlm_md_path.write_text(vlm_md_content, encoding="utf-8")
        except PermissionError:
            logger.warning("권한 문제로 재시도...")
            vlm_file_path = f"{container_output_dir}/{original_stem}/vlm/{vlm_md_path.name}"
            run_in_container(
                f"chown 1000:1000 {shlex.quote(vlm_file_path)} && "
                f"chmod 777 {shlex.quote(vlm_file_path)}"
            )
            vlm_md_path.write_text(vlm_md_content, encoding="utf-8")
        
        logger.info("VLM 마크다운 HTML 테이블 변환 완료")
        logger.info(f"VLM 결과 사용: {vlm_md_path}")
        return vlm_md_path
    finally:
        # 작업 완료 후 컨테이너 중지
        stop_container(MINERU_CONTAINER)


def summarize_image_with_qwen_vl(image_path: Path, model_endpoint: str = None, max_retries: int = 1) -> Optional[str]:
    """
    Qwen2.5-VL-7B-Instruct 모델을 사용하여 이미지 요약 생성 (재시도 로직 포함)

    Args:
        image_path: 이미지 파일 경로
        model_endpoint: 모델 API 엔드포인트 (None이면 Ollama 사용)
        max_retries: 최대 재시도 횟수 (기본값: 1, 총 2번 시도)

    Returns:
        Optional[str]: 이미지 요약 텍스트 (실패 시 None)
    """
    if not HAS_REQUESTS:
        logger.warning("requests 라이브러리가 필요합니다. pip install requests")
        return None

    # 타임아웃 설정 (환경 변수에서 읽어옴)
    timeout = int(os.getenv("QWEN_VL_TIMEOUT"))

    for attempt in range(max_retries + 1):
        try:
            # 이미지를 base64로 인코딩
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            # Ollama를 사용하는 경우
            if model_endpoint is None:
                ollama_url = os.getenv("OLLAMA_BASE_URL")
                if not ollama_url:
                    raise ValueError("OLLAMA_BASE_URL 환경 변수가 설정되지 않았습니다.")
                api_url = f"{ollama_url}/api/generate"

                # Qwen2.5-VL 모델명 (환경 변수에서 읽어옴)
                model_name = os.getenv("QWEN_VL_MODEL")
                if not model_name:
                    raise ValueError("QWEN_VL_MODEL 환경 변수가 설정되지 않았습니다.")

                # 이미지와 함께 텍스트 프롬프트 전송
                payload = {
                    "model": model_name,
                    "prompt": """이 이미지를 정확하고 상세하게 설명해주세요. 다음 사항을 반드시 포함해주세요:

1. 이미지에 나타난 모든 부품, 장치, 기계 요소의 정확한 이름과 위치
2. 부품에 표시된 번호나 라벨이 있다면 그 번호와 해당 부품의 이름 (이미지에서 실제로 보이는 번호와 라벨만 포함)
3. 이미지의 구조와 배치 (위치 관계, 연결 상태 등) - 이미지에서 명확히 보이는 것만 설명
4. 이미지에 표시된 텍스트, 라벨, 설명문 등 모든 텍스트 내용을 정확하게 읽어서 포함
5. 중요한 세부 사항이나 특징 - 이미지에서 실제로 보이는 것만

**중요 규칙:**
- 이미지에서 명확히 보이는 내용만 정확하게 설명하세요
- "아마도", "~일 수 있습니다", "추정됩니다" 같은 추측 표현을 절대 사용하지 마세요
- 이미지에 표시된 모든 번호, 라벨, 텍스트를 빠짐없이 읽어서 정확하게 포함하세요
- 이미지에서 보이지 않는 내용이나 추측은 절대 포함하지 마세요
- 이미지에 있는 모든 정보를 빠짐없이 읽고 요약하세요

**단순 그래픽 요소는 요약하지 마세요 (매우 중요):**
- 화살표, 원형 기호, 삼각형 경고 아이콘, 단순한 도형, 번호만 있는 원형 등 단순한 그래픽 요소는 요약하지 마세요
- 이런 경우 "이 이미지는 단순한 그래픽 요소(화살표/기호)로, 요약할 내용이 없습니다."라고만 답변하세요
- 부품, 장치, 기계 요소, 테이블, 텍스트가 없는 단순한 그래픽은 상세히 설명하지 마세요

**에러 코드 테이블이 있는 경우 (매우 중요):**
- 이미지에 테이블이나 목록이 있으면, 반드시 빠짐없이 읽어서 포함하세요
- 예를 들어 "Error Code 44027, 44028, 44029"가 모두 보이면 세 개 모두를 설명해야 합니다
- 하나만 선택해서 설명하지 말고, 테이블에 있는 모든 행(row)의 정보를 포함하세요
- 각 에러 코드의 Error Message, Cause, Inspection and Solution을 모두 정확하게 읽어서 포함하세요

한국어로 답변하고, 이미지에서 실제로 보이는 내용만 정확하게 설명해주세요.""",
                    "images": [image_data],
                    "stream": False
                }

                if attempt > 0:
                    logger.info(f"이미지 요약 재시도 {attempt}/{max_retries}")

                response = requests.post(api_url, json=payload, timeout=timeout)

                if response.status_code == 200:
                    result = response.json()
                    summary = result.get("response", "").strip()
                    return summary if summary else None
                else:
                    logger.warning(f"Ollama API 호출 실패: {response.status_code}")
                    if attempt < max_retries:
                        time.sleep(2)
                        continue
                    return None

            # 커스텀 엔드포인트를 사용하는 경우
            else:
                payload = {
                    "image": image_data,
                    "prompt": """이 이미지를 정확하고 상세하게 설명해주세요. 다음 사항을 반드시 포함해주세요:

1. 이미지에 나타난 모든 부품, 장치, 기계 요소의 정확한 이름과 위치
2. 부품에 표시된 번호나 라벨이 있다면 그 번호와 해당 부품의 이름
3. 이미지의 구조와 배치 (위치 관계, 연결 상태 등)
4. 이미지의 목적이나 용도 (가능한 경우)
5. 중요한 세부 사항이나 특징

한국어로 답변하고, 추측이나 불확실한 내용은 포함하지 말고 이미지에서 명확히 보이는 내용만 정확하게 설명해주세요."""
                }

                if attempt > 0:
                    logger.info(f"이미지 요약 재시도 {attempt}/{max_retries}")

                response = requests.post(model_endpoint, json=payload, timeout=timeout)

                if response.status_code == 200:
                    result = response.json()
                    summary = result.get("summary", result.get("response", "").strip())
                    return summary if summary else None
                else:
                    logger.warning(f"VLM API 호출 실패: {response.status_code}")
                    if attempt < max_retries:
                        time.sleep(2)
                        continue
                    return None

        except requests.exceptions.Timeout:
            if attempt < max_retries:
                logger.warning(f"이미지 요약 타임아웃 발생 (시도 {attempt + 1}/{max_retries + 1}), 재시도 중")
                time.sleep(2)
                continue
            else:
                logger.warning(f"이미지 요약 타임아웃 발생 (최대 재시도 횟수 초과): {image_path.name}")
                return None
        except ImportError:
            logger.warning("requests 라이브러리가 필요합니다. pip install requests")
            return None
        except Exception as e:
            if attempt < max_retries:
                logger.warning(f"오류 발생 (시도 {attempt + 1}/{max_retries + 1}): {e}, 재시도 중")
                time.sleep(2)
                continue
            else:
                logger.warning(f"이미지 요약 생성 중 오류 (최대 재시도 횟수 초과): {e}")
                return None

    return None


def enrich_markdown_with_image_summaries(md_path: Path, img_dir: Path) -> Path:
    """
    마크다운 파일의 이미지 태그 뒤에 VLM 이미지 요약을 삽입하여 강화된 MD 생성

    Args:
        md_path: 원본 마크다운 파일 경로
        img_dir: 이미지 디렉토리 경로

    Returns:
        Path: 강화된 마크다운 파일 경로 (원본 파일을 덮어씀)
    """
    # 이미지 요약 기능이 비활성화된 경우 원본 반환
    if not ENABLE_IMAGE_SUMMARY:
        logger.info("이미지 요약 기능이 비활성화되어 있습니다.")
        return md_path
    
    if not img_dir.exists():
        logger.warning(f"이미지 디렉토리가 없습니다: {img_dir}")
        return md_path

    # MD 파일 읽기
    md_content = md_path.read_text(encoding="utf-8", errors="ignore")

    # 이미지 태그 패턴 찾기: ![alt](images/filename.png)
    image_pattern = re.compile(r'!\[([^\]]*)\]\(images/([^\)]+\.(?:jpg|jpeg|png|gif))\)', re.IGNORECASE)

    # 모든 이미지 태그 찾기
    matches = list(image_pattern.finditer(md_content))

    if not matches:
        logger.info("MD 파일에 이미지 태그가 없습니다")
        return md_path

    logger.info(f"{len(matches)}개의 이미지 태그 발견, 요약 생성 중")

    # 역순으로 처리하여 인덱스 변경에 영향받지 않도록
    summaries = {}
    for match in matches:
        image_filename = match.group(2)
        image_path = img_dir / image_filename

        if not image_path.exists():
            logger.warning(f"이미지 파일을 찾을 수 없습니다: {image_path}")
            continue

        # 이미지 요약 생성
        logger.info(f"이미지 요약 생성 중: {image_filename}")
        summary = summarize_image_with_qwen_vl(image_path)

        if summary:
            summaries[image_filename] = summary
            logger.info(f"요약 생성 완료: {image_filename[:30]}")
        else:
            logger.warning(f"요약 생성 실패: {image_filename}")

    if not summaries:
        logger.warning("생성된 요약이 없습니다. 원본 MD 파일을 반환합니다.")
        return md_path

    # MD 내용에 요약 삽입 (역순으로 처리)
    enriched_content = md_content
    for match in reversed(matches):
        image_filename = match.group(2)

        if image_filename in summaries:
            summary_text = summaries[image_filename]
            # 이미지 태그 바로 뒤에 요약 삽입
            insert_text = f"\n\n**[VLM 이미지 요약]**: {summary_text}\n\n"
            insert_pos = match.end()
            enriched_content = enriched_content[:insert_pos] + insert_text + enriched_content[insert_pos:]

    # 강화된 MD 파일 저장 (원본 덮어쓰기)
    md_path.write_text(enriched_content, encoding="utf-8")
    logger.info(f"강화된 마크다운 파일 저장 완료: {md_path}")

    return md_path
