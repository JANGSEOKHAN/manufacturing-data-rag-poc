# Backend 기능별 README

AI-KnowledgeOps 백엔드는 업로드된 기술 문서를 전처리하고, 벡터 검색 기반 질의응답을 제공하는 FastAPI 애플리케이션입니다. 공개 포트폴리오 제출을 위해 예제 경로와 설정은 로컬 개발 기준으로 정리되어 있습니다.

## 1. 전체 구조

| 파일 | 역할 |
| --- | --- |
| `main.py` | FastAPI 앱 진입점, 파일 업로드, 질의응답, 상태 조회, 삭제, 재색인 API 제공 |
| `config.py` | 경로, 모델, 컨테이너 실행, 문서 변환, 이미지 요약 관련 설정과 유틸리티 관리 |
| `file_handler.py` | 업로드 파일 처리, 마크다운 청크 분리, 메타데이터 추출, 벡터 저장 요청 |
| `rag_query_handler.py` | 사용자 질문 분석, Qdrant 검색, LLM 답변 생성, 관련 이미지 검증 |
| `vector_store.py` | 임베딩 모델, Qdrant 클라이언트, 컬렉션, 문서 추가/삭제 관리 |
| `admin_api.py` | 관리자 화면에서 사용하는 문서 목록, 상세 청크, 이미지 요약 조회 API |
| `chat_history.py` | 채팅 이력 저장, 조회, 삭제 |
| `text_utils.py` | API 요청/응답에 사용하는 Pydantic 모델 |
| `md_image.py` | 마크다운 이미지 경로를 인라인 HTML로 변환 |

## 2. 주요 기능 흐름

1. 사용자가 관리자 화면에서 문서를 업로드합니다.
2. `main.py`가 업로드 파일을 입력 폴더에 저장하고 백그라운드 작업을 등록합니다.
3. `file_handler.py`가 문서 변환 결과를 읽어 텍스트와 이미지 정보를 정리합니다.
4. 텍스트는 청크 단위로 나뉘고 파일명, 장비 코드, 이미지 참조 같은 메타데이터가 붙습니다.
5. `vector_store.py`가 임베딩을 생성하고 Qdrant 컬렉션에 저장합니다.
6. 사용자가 질문하면 `rag_query_handler.py`가 관련 청크를 검색하고 LLM으로 답변을 생성합니다.
7. 답변과 함께 참조 문서, 관련 이미지, 매칭 근거가 프론트엔드로 반환됩니다.

## 3. 실행 준비

Python 3.10 이상을 권장합니다.

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

`.env` 파일에는 로컬 개발 환경에 맞는 경로와 모델명을 설정합니다. 공개 저장소에는 실제 운영 값이나 개인 환경 값이 들어가지 않도록 예시 파일만 유지합니다.

## 4. 환경 변수

| 변수 | 설명 |
| --- | --- |
| `BASE_DIR` | 프로젝트 루트 경로 |
| `CONTAINER_BASE_DIR` | 컨테이너 내부 기준 경로 |
| `MINERU_CONTAINER` | 문서 변환 컨테이너 이름 |
| `EMBED_MODEL` | 임베딩 모델명 |
| `OLLAMA_MODEL` | 답변 생성 모델명 |
| `OLLAMA_BASE_URL` | Ollama 로컬 엔드포인트 |
| `QDRANT_COLLECTION_NAME` | Qdrant 컬렉션명 |
| `QDRANT_URL` | Qdrant 로컬 엔드포인트 |
| `CHUNK_SIZE` | 1차 청크 크기 |
| `POST_PROCESS_MAX_SIZE` | 후처리 청크 최대 크기 |
| `POST_PROCESS_MIN_SIZE` | 후처리 청크 최소 크기 |
| `OVERLAP_SIZE` | 청크 간 겹침 크기 |
| `CORS_ORIGINS` | 허용할 프론트엔드 출처 |
| `ENABLE_IMAGE_SUMMARY` | 이미지 요약 사용 여부 |
| `ENABLE_IMAGE_VERIFICATION` | 이미지 검증 사용 여부 |

## 5. 주요 API

| Method | Path | 설명 |
| --- | --- | --- |
| `POST` | `/upload_file` | 문서 업로드 및 백그라운드 처리 시작 |
| `GET` | `/upload_status/{filename}` | 업로드 처리 상태 조회 |
| `POST` | `/rag_query` | 질문에 대한 검색 기반 답변 생성 |
| `GET` | `/view_html/{filename}` | 변환된 문서 내용을 HTML로 조회 |
| `GET` | `/status` | 백엔드, 벡터 저장소, 모델 상태 조회 |
| `GET` | `/embedded_files` | 색인된 파일 목록 조회 |
| `DELETE` | `/delete_file/{filename}` | 파일과 관련 벡터 데이터 삭제 |
| `POST` | `/reset_vectorstore` | 벡터 컬렉션 초기화 |
| `POST` | `/rebuild_vectorstore` | 기존 변환 결과를 기준으로 재색인 |
| `DELETE` | `/delete_all_files` | 입력, 출력, 벡터 데이터를 전체 삭제 |

관리자 전용 조회 API는 `/api/admin` prefix 아래에 있습니다.

## 6. 모듈별 상세

### `main.py`

- FastAPI 앱을 생성하고 CORS를 환경 변수 기반으로 설정합니다.
- 업로드, 상태 조회, 질의응답, HTML 조회, 채팅 이력, 삭제 API를 제공합니다.
- 앱 종료 시 문서 변환 컨테이너 중지 처리를 시도합니다.

### `config.py`

- 프로젝트 경로와 모델 설정을 환경 변수에서 읽습니다.
- 문서 변환 컨테이너 실행, 변환 결과 정리, 이미지 요약 유틸리티를 담당합니다.
- 변환 결과는 마크다운과 이미지 폴더 기준으로 후속 처리됩니다.

### `file_handler.py`

- 업로드 파일을 변환 결과로 연결하고 텍스트 청크를 생성합니다.
- 이미지 참조와 이미지 요약을 별도 청크로 관리합니다.
- 파일별 처리 상태와 색인된 파일 목록을 메모리에 유지합니다.

### `rag_query_handler.py`

- 질문에서 장비 코드, 범위 조건, 키워드를 추출합니다.
- 텍스트 청크와 이미지 청크를 함께 검색해 답변 컨텍스트를 구성합니다.
- 필요한 경우 이미지 관련성을 추가 확인한 뒤 결과에 포함합니다.

### `vector_store.py`

- Ollama 임베딩과 Qdrant 클라이언트를 지연 초기화합니다.
- 컬렉션 생성, 문서 추가, 파일 단위 삭제, 전체 초기화를 제공합니다.
- 저장된 파일명과 문서 수를 조회하는 헬퍼를 제공합니다.

### `admin_api.py`

- 관리자 화면에 필요한 문서 목록과 상세 정보를 제공합니다.
- 파일별 청크, 이미지 요약, 통계 정보를 프론트엔드가 보기 쉬운 형태로 변환합니다.

### `chat_history.py`

- 채팅 이력을 JSON 파일에 저장합니다.
- 채팅 목록, 메시지 조회, 저장, 삭제 기능을 제공합니다.

## 7. 개발 점검

```bash
python -m compileall -q .
```

공개 저장소에 올리기 전에는 실제 운영 값, 내부 도메인, 개인 경로, 원본 데이터 파일이 포함되지 않았는지 다시 확인합니다.
