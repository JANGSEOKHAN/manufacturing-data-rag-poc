# -*- coding: utf-8 -*-

import re
import time
import os
import json as json_module
from typing import List, Tuple
from pathlib import Path
from fastapi import HTTPException
from langchain_core.documents import Document
import base64
import requests

# config 모듈 import
from config import *
from config import (
    MACHINE_TYPES,
    FILE_PREFIX_PATTERNS,
    MACHINE_KEYWORDS,
    EXCLUDED_KEYWORDS,
    LIST_QUERY_KEYWORDS,
    GREETING_KEYWORDS,
    NEGATION_KEYWORDS,
    MIN_CODE_LENGTH,
    MAX_RANGE_CODES,
    MAX_CODE_FILTER_COUNT,
    FILENAME_PATTERN_MAPPING,
    HOST_OUTPUT_DIR,
)

from vector_store import (
    get_vectorstore,
    get_llm,
    reset_vectorstore,
    get_document_count,
    get_qdrant_client,
    get_all_filenames,
)
from text_utils import Question
from md_image import convert_image_to_data_uri


def rag_query(req: Question):
    """
    Qdrant 네이티브 필터 + Python 중복 제거/재정렬을 사용하는 RAG 핸들러
    """

    t0 = time.time()
    question_lower = req.question.lower()

    greetings = GREETING_KEYWORDS
    is_greeting = False
    if question_lower in greetings:
        is_greeting = True
    elif len(req.question) < 10 and any(g in question_lower for g in greetings):
        is_greeting = True

    if is_greeting:
        return {
            "answer": "안녕하세요. 어떻게 도와드릴까요?",
            "sources": [],
            "images": [],
            "elapsed_time": f"{time.time() - t0:.2f}s",
            "chunks_used": 0,
        }

    vs = get_vectorstore()
    doc_count = get_document_count()
    if doc_count == 0:
        raise HTTPException(
            404,
            "벡터 스토어가 비어있습니다. 파일을 업로드하여 벡터 스토어를 구성해주세요.",
        )

    # 1. 범위 질문 감지
    range_pattern = re.compile(r"(\d{4,5})\s*[~-]\s*(\d{4,5})")
    range_match = range_pattern.search(question_lower)

    # 2. 특정 '코드' 감지 (필터링용)
    code_pattern = re.compile(r"\b([A-Z]{1,3}\d{3,5}|\d{4,5}[A-Z]{0,2}|[A-Z]{2,}\d{3,})", re.IGNORECASE)
    question_codes = set(code_pattern.findall(req.question))
    question_codes = {c.upper() for c in question_codes if '-' not in c}

    # 2-1. 장비 코드 감지
    detected_machines_for_filter = set()
    question_lower_no_space = question_lower.replace(' ', '').replace('-', '')

    for machine in MACHINE_TYPES:
        machine_lower = machine.lower()
        patterns_original = [rf'\b{machine_lower}\b']
        for keyword in MACHINE_KEYWORDS:
            patterns_original.append(rf'{machine_lower}\s+{keyword}')
        patterns_original.append(rf'npm[-_\s]?{machine_lower}')

        patterns_no_space = []
        for keyword in MACHINE_KEYWORDS:
            patterns_no_space.append(rf'{machine_lower}{keyword}')
        patterns_no_space.append(rf'npm{machine_lower}')

        for pattern in patterns_original:
            if re.search(pattern, question_lower, re.IGNORECASE):
                detected_machines_for_filter.add(machine)
                break

        if machine not in detected_machines_for_filter:
            for pattern in patterns_no_space:
                if re.search(pattern, question_lower_no_space, re.IGNORECASE):
                    detected_machines_for_filter.add(machine)
                    break

    # question_codes에서도 장비 코드 확인
    for code in question_codes:
        if code in MACHINE_TYPES:
            detected_machines_for_filter.add(code)

    question_codes_for_filter = question_codes - MACHINE_TYPES - EXCLUDED_KEYWORDS
    question_codes_for_filter = {c for c in question_codes_for_filter if not (c.isdigit() and len(c) < MIN_CODE_LENGTH)}

    # 3. 목록 질문 감지
    is_list_query = any(kw in question_lower for kw in LIST_QUERY_KEYWORDS)

    query_for_retrieval = req.question
    search_k = max(20, req.k * 4)  # 균형 설정 (15 → 20)
    context_k = max(req.k * 2, 10)  # 균형 설정 (8 → 10)
    query_type = "4. 일반 질문"
    qdrant_filter = None

    try:
        from qdrant_client.http.models import Filter, FieldCondition, MatchAny
    except ImportError:
        logger.warning("qdrant_client가 설치되지 않았습니다. 필터링이 작동하지 않을 수 있습니다.")
        Filter = None
        FieldCondition = None
        MatchAny = None

    if range_match and Filter:
        # 1. 범위 질문
        query_type = "1. 범위 질문"
        range_codes = []
        try:
            start_code = int(range_match.group(1))
            end_code = int(range_match.group(2))
            if (end_code - start_code + 1) < MAX_RANGE_CODES:  # 범위 질문 최대 코드 수 제한
                for code in range(start_code, end_code + 1):
                    range_codes.append(str(code))

                question_codes_for_filter.update(range_codes)

                filter_conditions_range = [
                    FieldCondition(key="metadata.codes", match=MatchAny(any=range_codes)),
                    FieldCondition(key="metadata.error_codes", match=MatchAny(any=range_codes))
                ]

                if detected_machines_for_filter:
                    try:
                        all_filenames = get_all_filenames()
                        matching_filenames = []

                        for machine in detected_machines_for_filter:
                            for filename in all_filenames:
                                filename_upper = filename.upper()
                                machine_upper = machine.upper()

                                # 1. 특수 파일명 패턴 매핑 확인 (FILENAME_PATTERN_MAPPING)
                                matched_by_pattern = False
                                if FILENAME_PATTERN_MAPPING:
                                    for pattern_key, mapped_machine in FILENAME_PATTERN_MAPPING.items():
                                        if pattern_key.upper() in filename_upper and mapped_machine.upper() == machine_upper:
                                            matched_by_pattern = True
                                            if filename not in matching_filenames:
                                                matching_filenames.append(filename)
                                            break

                                # 2. 일반 장비 코드 매칭 (특수 패턴에 매칭되지 않은 경우만)
                                if not matched_by_pattern:
                                    # 파일명에 장비 코드가 포함되어 있는지 확인 (접두사 무관)
                                    pattern = rf'[-_\s]?{re.escape(machine_upper)}[-_\s\.]'
                                    if (machine_upper in filename_upper and
                                        (re.search(pattern, filename_upper) or
                                         filename_upper.startswith(machine_upper) or
                                         filename_upper.endswith(machine_upper))):
                                        if filename not in matching_filenames:
                                            matching_filenames.append(filename)

                        if matching_filenames:
                            file_filter_condition = FieldCondition(
                                key="metadata.file",
                                match=MatchAny(any=matching_filenames)
                            )
                            qdrant_filter = Filter(
                                must=[
                                    Filter(should=filter_conditions_range),
                                    file_filter_condition
                                ]
                            )
                            if os.getenv("DEBUG_SEARCH", "false").lower() == "true":
                                logger.debug(f"범위 질문: 장비 코드 감지 {detected_machines_for_filter}, 파일명 필터 추가됨 (실제 파일명: {matching_filenames})")
                        else:
                            if os.getenv("DEBUG_SEARCH", "false").lower() == "true":
                                logger.warning(f"범위 질문: 장비 코드 {detected_machines_for_filter}에 해당하는 파일명을 찾을 수 없습니다.")
                            qdrant_filter = Filter(should=filter_conditions_range)
                    except Exception as e:
                        logger.warning(f"범위 질문 파일명 필터 생성 실패: {e}")
                        qdrant_filter = Filter(should=filter_conditions_range)
                else:
                    qdrant_filter = Filter(should=filter_conditions_range)

                search_k = max(80, len(range_codes) * 25)  # 균형 설정
                context_k = max(40, len(range_codes) * 6)  # 균형 설정
        except Exception:
            pass

    elif question_codes_for_filter and len(question_codes_for_filter) <= MAX_CODE_FILTER_COUNT and Filter:
        query_type = "2. 특정 코드 질문"
        code_list = list(question_codes_for_filter)

        try:
            filter_conditions = []

            filter_conditions.append(
                FieldCondition(
                    key="metadata.codes",
                    match=MatchAny(any=code_list)
                )
            )
            filter_conditions.append(
                FieldCondition(
                    key="metadata.error_codes",
                    match=MatchAny(any=code_list)
                )
            )

            if detected_machines_for_filter:
                try:
                    all_filenames = get_all_filenames()
                    matching_filenames = []

                    for machine in detected_machines_for_filter:
                        for filename in all_filenames:
                            filename_upper = filename.upper()
                            machine_upper = machine.upper()

                            matched_by_pattern = False
                            if FILENAME_PATTERN_MAPPING:
                                for pattern_key, mapped_machine in FILENAME_PATTERN_MAPPING.items():
                                    if pattern_key.upper() in filename_upper and mapped_machine.upper() == machine_upper:
                                        matched_by_pattern = True
                                        if filename not in matching_filenames:
                                            matching_filenames.append(filename)
                                        break

                            if not matched_by_pattern:
                                pattern = rf'[-_\s]?{re.escape(machine_upper)}[-_\s\.]'
                                if (machine_upper in filename_upper and
                                    (re.search(pattern, filename_upper) or
                                     filename_upper.startswith(machine_upper) or
                                     filename_upper.endswith(machine_upper))):
                                    if filename not in matching_filenames:
                                        matching_filenames.append(filename)

                    if matching_filenames:
                        file_filter_condition = FieldCondition(
                            key="metadata.file",
                            match=MatchAny(any=matching_filenames)
                        )

                        qdrant_filter = Filter(
                            must=[
                                Filter(should=filter_conditions),
                                file_filter_condition
                            ]
                        )
                        if os.getenv("DEBUG_SEARCH", "false").lower() == "true":
                            logger.debug(f"장비 코드 감지: {detected_machines_for_filter}, 파일명 필터 추가됨 (실제 파일명: {matching_filenames})")
                    else:
                        if os.getenv("DEBUG_SEARCH", "false").lower() == "true":
                            logger.warning(f"장비 코드 {detected_machines_for_filter}에 해당하는 파일명을 찾을 수 없습니다. 에러 코드 필터만 사용합니다.")
                        qdrant_filter = Filter(should=filter_conditions)
                except Exception as file_filter_error:
                    logger.warning(f"파일명 조회 실패: {file_filter_error}. 에러 코드 필터만 사용합니다.")
                    qdrant_filter = Filter(should=filter_conditions)
            else:
                qdrant_filter = Filter(should=filter_conditions)

            if len(detected_machines_for_filter) >= 2:
                search_k = max(80, len(question_codes_for_filter) * 25, len(detected_machines_for_filter) * 25)  # 균형 설정
                context_k = max(15, len(question_codes_for_filter) * 7, len(detected_machines_for_filter) * 4)  # 균형 설정
            else:
                search_k = max(60, len(question_codes_for_filter) * 20)  # 균형 설정
                context_k = max(12, len(question_codes_for_filter) * 6)  # 균형 설정
            if os.getenv("DEBUG_SEARCH", "false").lower() == "true":
                logger.debug(f"Qdrant 사전 필터링 활성화: 에러코드={code_list}, 장비={detected_machines_for_filter if detected_machines_for_filter else '없음'}")
        except Exception as e:
            logger.warning(f"필터 생성 실패: {e}. 필터링 없이 검색합니다.")
            import traceback
            traceback.print_exc()
            qdrant_filter = None
            search_k = max(50, len(question_codes_for_filter) * 20)
            context_k = max(10, len(question_codes_for_filter) * 5)

        query_for_retrieval = req.question

    elif is_list_query:
        query_type = "3. 목록 질문"
        search_k = 80  # 균형 설정 (품질 유지)
        context_k = 40  # 균형 설정 (품질 유지)
        if "에러" in question_lower or "error" in question_lower:
            query_for_retrieval = f"{req.question} error"

    if qdrant_filter is None and detected_machines_for_filter and Filter:
        try:
            all_filenames = get_all_filenames()
            matching_filenames = []

            for machine in detected_machines_for_filter:
                for filename in all_filenames:
                    filename_upper = filename.upper()
                    machine_upper = machine.upper()

                    matched_by_pattern = False
                    if FILENAME_PATTERN_MAPPING:
                        for pattern_key, mapped_machine in FILENAME_PATTERN_MAPPING.items():
                            if pattern_key.upper() in filename_upper and mapped_machine.upper() == machine_upper:
                                matched_by_pattern = True
                                if filename not in matching_filenames:
                                    matching_filenames.append(filename)
                                break

                    if not matched_by_pattern:
                        pattern = rf'[-_\s]?{re.escape(machine_upper)}[-_\s\.]'
                        if (machine_upper in filename_upper and
                            (re.search(pattern, filename_upper) or
                             filename_upper.startswith(machine_upper) or
                             filename_upper.endswith(machine_upper))):
                            if filename not in matching_filenames:
                                matching_filenames.append(filename)

            if matching_filenames:
                file_filter_condition = FieldCondition(
                    key="metadata.file",
                    match=MatchAny(any=matching_filenames)
                )
                qdrant_filter = Filter(must=[file_filter_condition])
                query_type = "4. 일반 질문 (장비 필터 적용)"
                if os.getenv("DEBUG_SEARCH", "false").lower() == "true":
                    logger.debug(f"일반 질문: 장비 코드 감지 {detected_machines_for_filter}, 파일명 필터 추가됨 (실제 파일명: {matching_filenames})")
        except Exception as e:
            logger.warning(f"일반 질문 파일명 필터 생성 실패: {e}")

    logger.info(f"{query_type} 감지 (검색: {search_k}개)")

    text_filter_conditions = []
    if qdrant_filter:
        if hasattr(qdrant_filter, 'must') and qdrant_filter.must is not None:
            if isinstance(qdrant_filter.must, list):
                text_filter_conditions.extend(qdrant_filter.must)
            else:
                text_filter_conditions.append(qdrant_filter.must)
        if hasattr(qdrant_filter, 'should') and qdrant_filter.should is not None:
            if isinstance(qdrant_filter.should, list):
                text_filter_conditions.extend(qdrant_filter.should)
            else:
                text_filter_conditions.append(qdrant_filter.should)

    if Filter:
        text_filter_conditions.append(
            FieldCondition(key="metadata.type", match=MatchAny(any=["text"]))
        )
        text_filter = Filter(must=text_filter_conditions) if text_filter_conditions else None
    else:
        text_filter = None

    image_filter_conditions = []
    if qdrant_filter:
        if hasattr(qdrant_filter, 'must') and qdrant_filter.must is not None:
            if isinstance(qdrant_filter.must, list):
                image_filter_conditions.extend(qdrant_filter.must)
            else:
                image_filter_conditions.append(qdrant_filter.must)
        if hasattr(qdrant_filter, 'should') and qdrant_filter.should is not None:
            if isinstance(qdrant_filter.should, list):
                image_filter_conditions.extend(qdrant_filter.should)
            else:
                image_filter_conditions.append(qdrant_filter.should)

    if Filter:
        image_filter_conditions.append(
            FieldCondition(key="metadata.type", match=MatchAny(any=["image"]))
        )
        image_filter = Filter(must=image_filter_conditions) if image_filter_conditions else None
    else:
        image_filter = None

    try:
        logger.info(f"텍스트 검색 실행 (k={search_k})")
        raw_results_with_scores = vs.similarity_search_with_score(
            query=query_for_retrieval,
            k=search_k,
            filter=text_filter
        )

        # 필터 적용 후 결과가 0개이면 필터 없이 재검색 (텍스트만)
        if len(raw_results_with_scores) == 0 and text_filter is not None:
            logger.info("텍스트 필터 적용 후 결과 0개. type 필터만 적용하여 재검색합니다.")
            if Filter:
                text_filter_retry = Filter(
                    must=[FieldCondition(key="metadata.type", match=MatchAny(any=["text"]))]
                )
                raw_results_with_scores = vs.similarity_search_with_score(
                    query=query_for_retrieval,
                    k=search_k,
                    filter=text_filter_retry
                )
            else:
                raw_results_with_scores = vs.similarity_search_with_score(
                    query=query_for_retrieval,
                    k=search_k,
                    filter=None
                )

        image_results_with_scores = []
        if len(raw_results_with_scores) == 0 and qdrant_filter is not None:
            if (query_type == "4. 일반 질문 (장비 필터 적용)" or
                (query_type == "1. 범위 질문" and detected_machines_for_filter) or
                (query_type == "2. 특정 코드 질문" and detected_machines_for_filter)):
                if os.getenv("DEBUG_SEARCH", "false").lower() == "true":
                    print(f"[DEBUG] 필터 적용 후 검색 결과 0개. 장비 필터를 제거하고 재검색합니다.")

                if query_type == "2. 특정 코드 질문" and question_codes_for_filter:
                    code_list = list(question_codes_for_filter)
                    filter_conditions_only = [
                        FieldCondition(key="metadata.codes", match=MatchAny(any=code_list)),
                        FieldCondition(key="metadata.error_codes", match=MatchAny(any=code_list))
                    ]
                    qdrant_filter_retry = Filter(should=filter_conditions_only)
                    raw_results_with_scores = vs.similarity_search_with_score(
                        query=query_for_retrieval,
                        k=search_k,
                        filter=qdrant_filter_retry
                    )
                    if os.getenv("DEBUG_SEARCH", "false").lower() == "true":
                        print(f"[DEBUG] 에러 코드 필터만 적용하여 재검색 완료")
                elif query_type == "1. 범위 질문" and question_codes_for_filter:
                    range_codes = [str(c) for c in question_codes_for_filter if c.isdigit()]
                    if range_codes:
                        filter_conditions_range_only = [
                            FieldCondition(key="metadata.codes", match=MatchAny(any=range_codes)),
                            FieldCondition(key="metadata.error_codes", match=MatchAny(any=range_codes))
                        ]
                        qdrant_filter_retry = Filter(should=filter_conditions_range_only)
                        raw_results_with_scores = vs.similarity_search_with_score(
                            query=query_for_retrieval,
                            k=search_k,
                            filter=qdrant_filter_retry
                        )
                        if os.getenv("DEBUG_SEARCH", "false").lower() == "true":
                            print(f"[DEBUG] 범위 코드 필터만 적용하여 재검색 완료")
                    else:
                        raw_results_with_scores = vs.similarity_search_with_score(
                            query=query_for_retrieval,
                            k=search_k,
                            filter=None
                        )
                        if os.getenv("DEBUG_SEARCH", "false").lower() == "true":
                            print(f"[DEBUG] 필터 없이 재검색 완료")
                else:
                    raw_results_with_scores = vs.similarity_search_with_score(
                        query=query_for_retrieval,
                        k=search_k,
                        filter=None
                    )
                    if os.getenv("DEBUG_SEARCH", "false").lower() == "true":
                        print(f"[DEBUG] 필터 없이 재검색 완료")

                query_type = f"{query_type} (장비 필터 제거 후 재검색)"

    except (ValueError, TypeError) as e:
        error_msg = str(e)
        if "Could not find document for id" in error_msg:
            logger.error(f"벡터 스토어 동기화 오류: {error_msg}")
            reset_vectorstore()
            vs = get_vectorstore()
            try:
                raw_results_with_scores = vs.similarity_search_with_score(
                    query_for_retrieval,
                    k=search_k,
                    filter=qdrant_filter  # 재시도 시에도 필터 포함
                )
            except Exception as retry_error:
                raise HTTPException(500, f"벡터 스토어 오류: {retry_error}")
        elif "filter" in error_msg.lower() or "key" in error_msg.lower():
            logger.warning(f"필터 키 오류 감지: {error_msg}. 필터링 없이 재시도합니다.")
            try:
                raw_results_with_scores = vs.similarity_search_with_score(
                    query=query_for_retrieval, k=search_k
                )
            except Exception as retry_error:
                logger.warning(f"필터링 재시도 실패: {retry_error}")
                raise HTTPException(500, f"벡터 스토어 검색 오류: {retry_error}")
        else:
            raise HTTPException(500, f"벡터 스토어 검색 오류: {error_msg}")

    unique_results_with_scores = []

    detected_machines = detected_machines_for_filter if detected_machines_for_filter else {code for code in question_codes if code in MACHINE_TYPES}
    negation_keywords = NEGATION_KEYWORDS
    has_negation = any(kw in question_lower for kw in negation_keywords)

    seen_primary_codes = set()

    if detected_machines and question_codes_for_filter:
        if os.getenv("DEBUG_SEARCH", "false").lower() == "true":
            print(f"[DEBUG] 기계({detected_machines}) 감지. `file` 및 `primary_code` 기준으로 중복 제거/우선순위 정렬.")

        if len(detected_machines) >= 2:
            machine_results = {machine: [] for machine in detected_machines}
            other_results = []

            for doc, score in raw_results_with_scores:
                file_name = doc.metadata.get("file", "")
                matched_machine = None
                for machine in detected_machines:
                    if machine.upper() in file_name.upper():
                        matched_machine = machine
                        break

                if matched_machine:
                    machine_results[matched_machine].append((doc, score))
                else:
                    other_results.append((doc, score))

            unique_results_with_scores = []
            machine_seen_codes = {machine: set() for machine in detected_machines}

            for machine in detected_machines:
                for doc, score in machine_results[machine]:
                    primary_code = doc.metadata.get("primary_code")
                    if primary_code and primary_code in machine_seen_codes[machine]:
                        continue
                    if primary_code:
                        machine_seen_codes[machine].add(primary_code)
                    unique_results_with_scores.append((doc, score))

            for doc, score in other_results:
                unique_results_with_scores.append((doc, score))

            if os.getenv("DEBUG_SEARCH", "false").lower() == "true":
                print(f"[DEBUG] 두 장비 이상 감지: 각 장비별로 primary_code 중복 제거 수행")
        else:
            priority_results = []
            other_results = []

            for doc, score in raw_results_with_scores:
                primary_code = doc.metadata.get("primary_code")
                file_name = doc.metadata.get("file", "")

                if primary_code and primary_code in seen_primary_codes:
                    continue

                is_priority_file = False
                for machine in detected_machines:
                    if machine in file_name:
                        is_priority_file = True
                        break

                if primary_code:
                    seen_primary_codes.add(primary_code)

                if has_negation:
                    if is_priority_file:
                        other_results.append((doc, score))
                    else:
                        priority_results.append((doc, score))
                else:
                    if is_priority_file:
                        priority_results.append((doc, score))
                    else:
                        other_results.append((doc, score))

            unique_results_with_scores = priority_results + other_results

    elif question_codes:
        print("[DEBUG] 코드 질문 감지. `primary_code` 기준으로 중복 제거를 수행합니다.")
        for doc, score in raw_results_with_scores:
            primary_code = doc.metadata.get("primary_code")
            doc_codes = set(doc.metadata.get("codes", []))
            has_question_code = bool(question_codes_for_filter & doc_codes)

            if has_question_code:
                unique_results_with_scores.append((doc, score))
            elif primary_code and primary_code not in seen_primary_codes:
                unique_results_with_scores.append((doc, score))
                seen_primary_codes.add(primary_code)
            elif not primary_code:
                unique_results_with_scores.append((doc, score))
    else:
        unique_results_with_scores = raw_results_with_scores

    raw_results_with_scores = unique_results_with_scores

    if not raw_results_with_scores:
        return {
            "answer": "죄송합니다, 문서에서 관련 정보를 찾을 수 없습니다.",
            "sources": [],
            "images": [],
            "elapsed_time": f"{time.time() - t0:.2f}s",
            "chunks_used": 0,
        }

    raw_results: List[Document] = [doc for doc, score in raw_results_with_scores]
    ordered_results = raw_results

    if raw_results_with_scores:
        display_count = min(5, len(raw_results_with_scores))
        logger.info(f"검색 결과 유사도 (상위 {display_count}개)")
        for i, (doc, score) in enumerate(raw_results_with_scores[:display_count], 1):
            similarity_percent = max(0, (1 - score / 2) * 100)
            codes = doc.metadata.get("codes", [])[:3]
            file_name = doc.metadata.get("file", "알 수 없는 문서")
            file_short = Path(file_name).name[:30]
            print(f"  [{i}] {similarity_percent:.1f}% (거리: {score:.4f}) | 파일: {file_short} | codes: {codes}")

    if len(detected_machines_for_filter) >= 2 and question_codes_for_filter:
        machine_docs = {machine: [] for machine in detected_machines_for_filter}
        other_docs = []

        for doc in ordered_results:
            file_name = doc.metadata.get("file", "")
            matched_machine = None
            for machine in detected_machines_for_filter:
                if machine.upper() in file_name.upper():
                    matched_machine = machine
                    break

            if matched_machine:
                machine_docs[matched_machine].append(doc)
            else:
                other_docs.append(doc)

        context_docs = []
        used_docs = set()

        for machine in detected_machines_for_filter:
            if machine_docs[machine]:
                doc = machine_docs[machine][0]
                context_docs.append(doc)
                used_docs.add(id(doc))

        remaining_slots = context_k - len(context_docs)
        if remaining_slots > 0:
            machine_indices = {machine: 1 for machine in detected_machines_for_filter}
            added_count = 0

            while added_count < remaining_slots:
                added_in_round = False
                for machine in detected_machines_for_filter:
                    if added_count >= remaining_slots:
                        break
                    idx = machine_indices[machine]
                    if idx < len(machine_docs[machine]):
                        doc = machine_docs[machine][idx]
                        if id(doc) not in used_docs:
                            context_docs.append(doc)
                            used_docs.add(id(doc))
                            added_count += 1
                            added_in_round = True
                        machine_indices[machine] += 1

                if not added_in_round:
                    for doc in other_docs:
                        if added_count >= remaining_slots:
                            break
                        if id(doc) not in used_docs:
                            context_docs.append(doc)
                            used_docs.add(id(doc))
                            added_count += 1
                    break

        if os.getenv("DEBUG_SEARCH", "false").lower() == "true":
            print(f"[DEBUG] 두 장비 이상 감지: {detected_machines_for_filter}, 각 장비별 최소 1개씩 포함하여 {len(context_docs)}개 선택")
    else:
        if question_codes_for_filter:
            priority_docs = []
            other_docs = []

            for doc in ordered_results:
                doc_codes = set(doc.metadata.get("codes", []))
                if question_codes_for_filter & doc_codes:
                    priority_docs.append(doc)
                else:
                    other_docs.append(doc)

            context_docs = priority_docs[:context_k]
            remaining_slots = context_k - len(context_docs)
            if remaining_slots > 0:
                context_docs.extend(other_docs[:remaining_slots])
        else:
            context_docs = ordered_results[:context_k]

    if os.getenv("DEBUG_SEARCH", "false").lower() == "true" and question_codes:
        print(f"[DEBUG] 검색 결과: {len(raw_results)}개 청크 중 {len(context_docs)}개 선택 (context_k={context_k})")
        matching_chunks = []
        for doc in context_docs:
            doc_codes = set(doc.metadata.get("codes", []))
            if question_codes_for_filter & doc_codes:
                matching_chunks.append(doc)
        if matching_chunks:
            print(f"[DEBUG] ✅ context_docs에 질문 코드가 포함된 청크: {len(matching_chunks)}개")
        else:
            print(f"[DEBUG] ⚠️ context_docs에 질문 코드가 포함된 청크 없음 (전체 {len(context_docs)}개)")

    if not context_docs:
        if os.getenv("DEBUG_SEARCH", "false").lower() == "true":
            print("[DEBUG] Qdrant 필터링/검색 결과 0개.")

    display_images = []
    seen_image_paths = set()

    for doc in context_docs:
        chunk_images = doc.metadata.get("chunk_images", [])
        if chunk_images:
            converted_ext = "." + "".join(chr(c) for c in (112, 100, 102))
            md_stem = doc.metadata.get("file", "").replace(converted_ext, "").replace(converted_ext.upper(), "")
            if not md_stem:
                continue
            
            for img_filename in chunk_images:
                if not img_filename or img_filename in seen_image_paths:
                    continue
                
                img_path = None
                for subdir in ["vlm", "ocr", ""]:
                    if subdir:
                        img_dir = HOST_OUTPUT_DIR / md_stem / subdir / "images"
                    else:
                        img_dir = HOST_OUTPUT_DIR / md_stem / "images"
                    
                    if img_dir.exists():
                        test_path = img_dir / img_filename
                        if test_path.exists():
                            img_path = test_path
                            break
                
                if img_path and img_path.exists():
                    from urllib.parse import quote
                    encoded_md_stem = quote(md_stem, safe='')
                    encoded_img_filename = quote(img_filename, safe='')
                    
                    url_parts = ["/static", encoded_md_stem]
                    if "vlm" in str(img_path):
                        url_parts.append("vlm")
                    elif "ocr" in str(img_path):
                        url_parts.append("ocr")
                    url_parts.extend(["images", encoded_img_filename])
                    image_url = "/".join(url_parts)
                    
                    try:
                        data_uri = convert_image_to_data_uri(img_path)
                    except Exception as e:
                        data_uri = None
                    
                    display_images.append({
                        "filename": img_filename,
                        "url": image_url,
                        "data_uri": data_uri,
                        "source": "text_search",
                        "score": 1.0
                    })
                    seen_image_paths.add(img_filename)
    
    text_search_image_count = len(display_images)
    if text_search_image_count > 0:
        logger.info(f"이미지 추출: {text_search_image_count}개")

    snippets_for_llm: List[str] = []

    for doc in context_docs:
        file_meta = doc.metadata.get("file", "알 수 없는 문서")
        snippet = f"[문서: {file_meta}]\n{doc.page_content}"
        snippets_for_llm.append(snippet)

    full_context = "\n\n---\n\n".join(snippets_for_llm) if snippets_for_llm else ""

    if question_codes_for_filter:
        found_codes = []
        missing_codes = []
        for code in question_codes_for_filter:
            if code in full_context or code.lower() in full_context.lower():
                found_codes.append(code)
            else:
                missing_codes.append(code)

        if missing_codes:
            logger.warning(f"컨텍스트에 포함되지 않은 코드: {missing_codes}")

    # 프롬프트 구성
    system_prompt = """당신은 제조 장비 매뉴얼 전문 어시스턴트입니다. 사용자와 자연스럽게 대화하듯이 답변하세요.

**중요: 모든 답변은 반드시 한국어로 작성하세요.**

**기본 규칙:**
1. 제공된 **'컨텍스트'** 정보만을 기반으로 답변해야 합니다 (할루시네이션 금지).
2. 컨텍스트를 처음부터 끝까지 꼼꼼히 읽고 질문에 관련된 모든 정보를 찾아서 답변하세요.
3. 같은 내용을 반복하지 마세요.
4. 컨텍스트에 정보가 없으면 "컨텍스트에 해당 정보가 없습니다"라고 명확히 답변하세요.
5. **답변 스타일:** 친근하고 자연스러운 대화 톤으로 답변하세요. 딱딱한 설명서 톤보다는 사용자와 대화하듯이 자연스럽게 답변하세요.

6. **답변 형식 (매우 중요):**
   - 답변에 불필요한 빈 줄을 **절대** 넣지 마세요.
   - **에러 코드나 부품 목록을 나열할 때 1., 2., 9., 10. 같은 번호 매기기를 사용하지 마세요.**
   - 각 항목에 빈 줄을 넣지 말고 촘촘하게(compact) 작성해야 합니다.

7. **코드의 종류(에러 코드 vs 부품 코드 등)를 절대 임의로 추론하지 마세요.**
    - 컨텍스트 안에 "Error code", "에러 코드" 등으로 **명시된 경우에만** 그 코드를 에러 코드로 설명하세요.
    - 컨텍스트가 "part code", "부품 코드", "기구 코드"처럼 부품/모듈로 설명하면, **반드시 부품 코드로** 설명하세요.
    - 코드의 종류가 문서에 명시되어 있지 않으면, 단순히 "해당 코드"라고 표현하세요.
    - 가능한 한 "에러 코드"라는 표현을 사용하지 말고, "관련 코드", "해당 코드"처럼 중립적인 표현을 사용하세요.
    - 문서 제목이 "Error Code"여도, 질문이 단순 장비/모듈 이름인 경우에는 "이 장비와 관련해 문서에 정리된 코드는 다음과 같습니다."처럼 표현하고, 굳이 "에러 코드"라고 단정하지 마세요.
    - 사용자가 질문에서 "에러 코드"라고 명시한 경우에만, "에러 코드"라는 표현을 사용해도 됩니다.

**이미지 참고 자료 (VLM 요약) 처리:**
- 컨텍스트에 "[참고: 이미지 설명]" 섹션이 있으면, 이것은 이미지의 시각적 설명입니다.
- **이미지 설명은 참고용이며, 본문 텍스트를 우선적으로 사용하세요.**
- 이미지 설명에 나열된 코드 목록은 단순히 "이미지에 보이는 코드들"일 뿐이며, 실제 정의나 설명은 본문 텍스트에서 찾으세요.
- 예: 이미지 설명에 "G1001, G1002가 있습니다"라고 나와도, G1001의 실제 정의는 본문 텍스트에서 찾아야 합니다.

**이미지 관련성 검증:**
- 답변에 포함될 이미지는 반드시 질문과 직접적으로 관련이 있어야 합니다.
- 이미지가 질문에 대한 답변에 도움이 되지 않거나, 단순히 같은 문서에 있기만 한 경우에는 이미지를 참조하지 마세요.
- 이미지에 질문과 관련된 코드, 부품, 에러 정보가 명확히 보이는 경우에만 이미지를 활용하세요.

**질문 유형별 지침:**
- **코드/부품/장비 질문 (예: "M656", "G1002", "40009", "M623"):**
    - 컨텍스트에서 해당 코드나 부품 번호를 정확히 찾으세요. 에러 코드뿐만 아니라 부품 번호, 장비 코드 등 모든 형식을 찾으세요.
    - **본문 텍스트를 우선적으로 확인하고, 이미지 설명은 보조 참고 자료로만 사용하세요.**
    - 해당 코드의 **설명, 원인(Cause), 해결 방법(Solution), 위치, 기능** 등 모든 관련 정보를 자연스럽게 요약하여 제공하세요.
- **여러 장비를 동시에 질문한 경우 (예: "D1과 W 장비 40001"):**
    - 컨텍스트에서 각 장비별 정보를 **명확히 구분**하여 답변하세요.
    - 각 장비의 정보를 별도로 제시하되, 같은 내용을 반복하지 마세요.
    - 예시 형식: "D1 장비의 경우: ... / W 장비의 경우: ..." 또는 "D1 장비: ... W 장비: ..."
    - 각 장비의 문서([문서: NPM-D1 ...], [문서: NPM-W ...])를 구분하여 답변하세요.
- **일반 질문:**
    - 질문의 의도를 파악하여 컨텍스트에서 가장 관련성 높은 정보를 찾아 답변하세요.
- **목록 질문 (예: "에러 리스트"):**
    - 컨텍스트에서 관련된 모든 항목을 찾아 목록 형식으로 답변하세요.
"""

    user_prompt = f"""컨텍스트:
{full_context}

질문: {req.question}

위 컨텍스트를 처음부터 끝까지 자세히 읽고 분석하여 질문에 정확히 답변하세요.
- 코드나 부품 번호를 찾는 질문이면 컨텍스트에서 해당 정보를 정확히 찾아서 모든 관련 정보를 자연스럽게 포함하여 답변하세요.
- 리스트나 목록을 요청하는 질문이면 컨텍스트에서 관련된 모든 항목을 찾아서 각각 답변하세요.
- **먼저 이 코드가 문서에서 에러 코드인지, 부품/모듈 코드인지, 혹은 단순 축/축번호인지 등을 확인한 뒤, 문서에 적힌 분류를 그대로 사용하세요. 임의로 에러 코드라고 단정하지 마세요.**
- **(중요)** 답변은 친근하고 자연스러운 대화 톤으로 작성하되, **절대로** 각 항목 사이에 불필요한 빈 줄을 넣지 말고 촘촘하게(compact) 작성하세요.
- 반드시 한국어로 답변하세요."""

    # LLM 호출
    llm = get_llm()
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        if hasattr(llm, "invoke") and "Chat" in type(llm).__name__:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
            response = llm.invoke(messages)
            answer = response.content if hasattr(response, "content") else str(response)
        else:
            full_prompt = f"{system_prompt}\n\n{user_prompt}"
            response = llm.invoke(full_prompt)
            answer = response.content if hasattr(response, "content") else str(response)
    except Exception as e:
        logger.error(f"LLM 호출 실패: {e}")
        import traceback
        traceback.print_exc()
        answer = "답변 생성 중 오류가 발생했습니다."
        llm_failed = True  # LLM 호출 실패 플래그
    else:
        llm_failed = False

    def verify_image_relevance(image_path: Path, question: str, answer_text: str) -> Tuple[str, bool]:
        """
        Qwen-VL을 사용하여 이미지가 질문과 관련 있는지 검증
        
        Args:
            image_path: 이미지 파일 경로
            question: 사용자 질문
            answer_text: LLM이 생성한 최종 답변
        
        Returns:
            Tuple[str, bool]: (이미지 파일명, 관련성 여부)
        """
        try:
            # 이미지를 base64로 인코딩
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")
            
            ollama_url = os.getenv("OLLAMA_BASE_URL")
            if not ollama_url:
                raise ValueError("OLLAMA_BASE_URL 환경 변수가 설정되지 않았습니다.")
            api_url = f"{ollama_url}/api/generate"
            
            # 이미지 검증용 VLM 모델
            model_name = os.getenv("QWEN_VL_VERIFY_MODEL")
            if not model_name:
                raise ValueError("QWEN_VL_VERIFY_MODEL 환경 변수가 설정되지 않았습니다.")
            
            import re
            code_pattern = re.compile(r'\b([A-Z]+\d+)\b')
            mentioned_codes = set(code_pattern.findall(answer_text))
            codes_str = ", ".join(sorted(mentioned_codes)) if mentioned_codes else "없음"
            
            verification_prompt = f"""사용자 질문: {question}

위 질문에 대한 답변 내용:
{answer_text[:800]}

**답변에서 언급된 구체적인 코드/부품:** {codes_str}

이 이미지를 보고, 위 질문과 답변 내용에 **직접적으로** 관련이 있는지 판단하세요.

**판단 기준:**
✅ **관련 있음 (true) - 다음 중 하나라도 해당되면:**
1. 이미지에 답변에서 언급된 **코드나 부품명이 일부라도 보이는 경우**
   - 예: 답변이 "M407, M404, R3012"를 언급하고, 이미지에 해당 코드들이 보이면 관련 있음.
   - 예: 답변에 "B1302"가 있고 이미지에 "B1302" 라벨이 보이면 관련 있음.
2. 이미지가 답변에서 설명하는 **핵심 장비나 부품의 도면/사진**인 경우
   - 예: 질문이 "Single tray feeder drawer"이고, 이미지에 해당 장비의 도면이나 라벨(B13xx 등)이 보이면 관련 있음.
   - 답변에 구체적인 코드가 언급되지 않았더라도, 이미지의 제목이나 내용이 질문의 핵심 키워드와 일치하면 관련 있음.

❌ **관련 없음 (false) - 다음 중 하나라도 해당되면:**
- 이미지가 단순히 **매뉴얼 커버, 문서 제목, 표지**만 보이는 경우 → 무조건 false
- 이미지에 답변 내용과 전혀 상관없는 장비나 부품만 보이는 경우 → false

**중요:**
- 답변에서 추출된 코드({codes_str})가 이미지에 보이면 확실히 True입니다.
- 코드가 없더라도 질문의 핵심 대상(장비명, 부품명)이 이미지에 묘사되어 있으면 True입니다.

반드시 다음 JSON 형식으로만 답변하세요:
{{
  "relevant": true 또는 false
}}

다른 설명이나 추가 텍스트는 절대 포함하지 마세요. JSON만 출력하세요."""
            
            payload = {
                "model": model_name,
                "prompt": verification_prompt,
                "images": [image_data],
                "stream": False
            }
            
            timeout = int(os.getenv("QWEN_VL_TIMEOUT"))
            response = requests.post(api_url, json=payload, timeout=timeout)
            
            if response.status_code == 200:
                result = response.json()
                response_text = result.get("response", "").strip()
                if not response_text:
                    response_text = result.get("text", "").strip()
                
                is_relevant = False
                try:
                    json_match = re.search(r'\{[^{}]*"relevant"[^{}]*\}', response_text, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(0)
                        parsed = json_module.loads(json_str)
                        is_relevant = parsed.get("relevant", False)
                    else:
                        response_text_lower = response_text.lower()
                        positive_keywords = ["true", "예", "yes", "관련", "있", "맞"]
                        negative_keywords = ["false", "아니오", "no", "없", "아니", "무관"]
                        
                        has_negative = any(keyword in response_text_lower for keyword in negative_keywords)
                        has_positive = any(keyword in response_text_lower for keyword in positive_keywords)
                        
                        if has_negative:
                            is_relevant = False
                        elif has_positive:
                            is_relevant = True
                except (json_module.JSONDecodeError, KeyError, ValueError):
                    response_text_lower = response_text.lower()
                    positive_keywords = ["true", "예", "yes", "관련", "있", "맞"]
                    negative_keywords = ["false", "아니오", "no", "없", "아니", "무관"]
                    
                    has_negative = any(keyword in response_text_lower for keyword in negative_keywords)
                    has_positive = any(keyword in response_text_lower for keyword in positive_keywords)
                    
                    if has_negative:
                        is_relevant = False
                    elif has_positive:
                        is_relevant = True
                
                
                return (image_path.name, is_relevant)
            else:
                logger.warning(f"이미지 검증 API 호출 실패: {response.status_code}")
                return (image_path.name, False)
        except requests.exceptions.Timeout:
            logger.warning(f"이미지 검증 타임아웃: {image_path.name}")
            return (image_path.name, False)
        except Exception as e:
            error_msg = str(e)
            if "CUDA" in error_msg or "cuda" in error_msg.lower() or "VRAM" in error_msg or "out of memory" in error_msg.lower():
                logger.error(f"이미지 검증 중 CUDA/VRAM 에러 발생: {image_path.name}")
                logger.error("이미지 검증을 중단합니다. (VRAM 부족 가능성)")
                raise
            logger.warning(f"이미지 검증 예외: {image_path.name}")
            return (image_path.name, False)
    
    enable_image_verification = (
        os.getenv("ENABLE_IMAGE_VERIFICATION", "true").lower() == "true" 
        and not llm_failed
    )
    
    answer_text_for_verification = ""
    if enable_image_verification:
        if answer and len(answer) > 100:
            answer_text_for_verification = answer[:800]
        else:
            answer_text_for_verification = f"{answer[:400] if answer else ''}\n\n{full_context[:600]}".strip()
    
    verified_images = []
    if enable_image_verification and display_images:
        max_verify_limit = int(os.getenv("MAX_IMAGE_VERIFY_COUNT"))
        max_verify_count = min(max_verify_limit, len(display_images))
        logger.info(f"이미지 검증 시작: {max_verify_count}개 이미지 검증 중 (전체: {len(display_images)}개)")
        
        images_to_verify = []
        verify_count = 0
        
        from urllib.parse import unquote
        for img_info in display_images:
            if verify_count >= max_verify_count:
                break
            img_filename = img_info.get("filename", "")
            img_url = img_info.get("url", "")
            
            if not img_filename or not img_url:
                continue
            
            url_parts = img_url.split("/")
            if len(url_parts) >= 5:
                md_stem = unquote(url_parts[2])
                subdir = url_parts[3] if len(url_parts) > 5 and url_parts[3] in ["vlm", "ocr"] else ""
                img_filename_decoded = unquote(img_filename) if img_filename else ""
                
                if subdir:
                    img_path = HOST_OUTPUT_DIR / md_stem / subdir / "images" / img_filename_decoded
                else:
                    img_path = HOST_OUTPUT_DIR / md_stem / "images" / img_filename_decoded
                
                if img_path.exists():
                    images_to_verify.append((img_info, img_path))
                    verify_count += 1
                else:
                    if os.getenv("DEBUG_IMAGES", "false").lower() == "true":
                        print(f"[WARN] 이미지 파일을 찾을 수 없음: {img_path}")
                    verified_images.append(img_info)
            else:
                verified_images.append(img_info)
        
        if images_to_verify:
            verification_results = {}
            
            try:
                for img_info, img_path in images_to_verify:
                    try:
                        img_filename, is_relevant = verify_image_relevance(img_path, req.question, answer_text_for_verification)
                        verification_results[img_filename] = (img_info, is_relevant)
                    except Exception as e:
                        error_msg = str(e)
                        if "CUDA" in error_msg or "cuda" in error_msg.lower() or "VRAM" in error_msg or "out of memory" in error_msg.lower():
                            logger.error("이미지 검증 중 CUDA/VRAM 에러로 인해 검증을 중단합니다.")
                            break
                        verification_results[img_path.name] = (img_info, False)
            except Exception as e:
                error_msg = str(e)
                if "CUDA" in error_msg or "cuda" in error_msg.lower():
                    logger.error(f"이미지 검증 중 치명적 에러 발생: {error_msg[:200]}")
            
            for img_filename, (img_info, is_relevant) in verification_results.items():
                if is_relevant:
                    verified_images.append(img_info)
            
            logger.info(f"이미지 검증 완료: {len(verified_images)}개 통과 (검증: {len(images_to_verify)}개)")
        else:
            verified_images = display_images
    else:
        verified_images = display_images
    
    max_images = int(os.getenv("MAX_IMAGES"))
    selected_images = verified_images[:max_images]
    
    if len(selected_images) < len(verified_images):
        logger.info(f"최종 이미지 선택: {len(selected_images)}개 (검증 통과: {len(verified_images)}개, {len(verified_images) - len(selected_images)}개 제외)")
    else:
        logger.info(f"최종 이미지 선택: {len(selected_images)}개")

    source_files = []
    for doc in context_docs:
        file_meta = doc.metadata.get("file", "")
        if not file_meta:
            continue

        md_stem = Path(file_meta).stem
        md_path = None
        html_path = None

        for subdir in ["vlm", "ocr", ""]:
            if subdir:
                test_md = HOST_OUTPUT_DIR / md_stem / subdir / f"{md_stem}.md"
                test_html = HOST_OUTPUT_DIR / md_stem / subdir / f"{md_stem}.html"
            else:
                test_md = HOST_OUTPUT_DIR / md_stem / f"{md_stem}.md"
                test_html = HOST_OUTPUT_DIR / md_stem / f"{md_stem}.html"

            if test_md.exists():
                md_path = test_md
                html_path = test_html if test_html.exists() else None
                break

        if file_meta not in [f["filename"] for f in source_files]:
            source_files.append(
                {
                    "filename": file_meta,
                    "md_path": str(md_path) if md_path else None,
                    "html_path": str(html_path) if html_path else None,
                }
            )

    elapsed = time.time() - t0

    return {
        "answer": answer,
        "sources": source_files,
        "images": selected_images,
        "elapsed_time": f"{elapsed:.2f}s",
        "chunks_used": len(context_docs),
    }
