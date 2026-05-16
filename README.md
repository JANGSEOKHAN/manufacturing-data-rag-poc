# AI KnowledgeOps RAG 서버

> 공개 포트폴리오 제출용 저장소입니다. 실제 운영 환경에서 사용한 `.env`, 로컬 벡터 DB, 업로드 문서, 내부 매뉴얼, 백업 파일, 브랜드 로고 등 공개에 부적합한 자료는 제거했습니다. README와 설정 예시는 테스트/샘플 환경 기준으로 일반화했습니다.

제조/설비 매뉴얼 문서를 **OCR → Markdown/HTML → 이미지 요약(Enrichment) → 청킹 → 벡터DB(Qdrant)** 로 넣고  
Ollama LLM으로 질의응답하는 **리눅스 기반 RAG 환경**입니다.  
FastAPI 백엔드 + (React/Streamlit) 프론트 + MinerU OCR + Qwen2.5-VL 이미지 요약 + Qwen3-VL 이미지 검증 + Qdrant + Ollama 조합을 기준으로 합니다.

---

## 주요 기능

- **2단계 문서 처리**: MinerU OCR → Qwen2.5-VL 이미지 요약 → Qdrant 벡터DB 저장
- **Qwen-VL 이미지 검증**: Qwen3-VL로 관련 이미지 필터링
- **코드 기반 필터링**: 에러코드/부품번호 기반 정확한 검색
- **React 프론트엔드**: 실시간 질의응답 인터페이스

---

## 시스템 요구사항

### 운영체제
- **RedHat 8** 버전 이상
- **Debian** 계열 (Ubuntu 22.04 이상 권장)

### GPU
- NVIDIA GPU (CUDA 지원)
- **VRAM: 16GB 이상 권장** (MinerU vLLM 엔진 실행 필수)

### 초기 설치 전 준비 사항
- 인터넷 연결 (초기 설치 시 모델 다운로드)
- Docker 이미지 다운로드 (MinerU 컨테이너)

---

## 1. 기능 개요

- **문서 처리**: 매뉴얼 문서 → MinerU OCR → Qwen2.5-VL 이미지 요약 → 구조 기반 청킹 → Qdrant 저장
- **질의응답**: 코드 기반 필터링 + 유사도 검색 → Qwen-VL 이미지 검증 → LLM 답변 생성
- **벡터DB**: Qdrant (BAAI/bge-m3 임베딩, 메타데이터 필터링)
- **관리**: 문서 업로드/삭제, 벡터 스토어 재구성, 채팅 히스토리

---

## 2. 설치/환경 구성

### 2.0 초기 환경 설정

#### 필요 디렉토리 생성
```bash
mkdir -p input output qdrant_storage chat_history
```

#### 디렉토리 소유권 및 권한 설정
```bash
# 사용자 이름에 맞게 수정
sudo chown -R "$USER:$USER" qdrant_storage/ output/ input/ chat_history/
sudo chmod -R u+rwX,g+rwX,o-rwx qdrant_storage/ output/ input/ chat_history/
```

### 2.1 Docker 설치
```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

### 2.2 NVIDIA / CUDA 설치
```bash
# NVIDIA Container Toolkit
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker

# CUDA
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt-get update
sudo apt-get -y install cuda-toolkit-12-8

# Docker GPU 설정
echo '{"default-runtime": "nvidia", "runtimes": {"nvidia": {"path": "nvidia-container-runtime", "runtimeArgs": []}}}' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
```

### 2.3 Python 가상환경
```bash
# Python 가상환경 생성 및 활성화
cd backend
python3 -m venv .venv
source .venv/bin/activate

# Python 패키지 설치
pip install -r requirements.txt

# 환경 변수 파일 설정
vi .env
```

`.env` 파일 내용 예시:
```
BASE_DIR=/opt/ai-knowledgeops
CONTAINER_BASE_DIR=/
```

### 2.4 Qdrant 설치
```bash
cd qdrant/
docker load -i qdrant_latest.tar  # 또는 docker pull qdrant/qdrant
docker run -d --name qdrant -p 6333:6333 -v qdrant_data:/qdrant/storage qdrant/qdrant
# Web UI: http://localhost:6333/dashboard
```

### 2.5 Ollama 설치 & 모델
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5vl:7b              # 이미지 요약
ollama pull qwen3-vl:8b-instruct     # 이미지 검증
ollama pull qwen2.5:14b-instruct-q4_K_M  # LLM
```

### 2.6 MinerU 설치
```bash
docker pull avarok/vllm-dgx-spark:v11
docker build -t mineru:latest -f Dockerfile .
docker run -it --gpus all --shm-size 32g --ipc=host \
  -p 30000:30000 -p 7860:7860 -p 8010:8000 \
  -v /opt/ai-knowledgeops/input:/input \
  -v /opt/ai-knowledgeops/output:/output \
  --name mineru-vllm mineru:latest

# 컨테이너 내부에서
python3 -m pip install -U 'mineru[core]>=2.7.0' --break-system-packages
```

### 2.7 Node.js 및 npm 설치 (프론트엔드용)
```bash
# NVM(Node Version Manager) 설치
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash

# NVM 활성화 (쉘 재시작 대신)
. "$HOME/.nvm/nvm.sh"

# Node.js v24 설치
nvm install 24
```

### 2.8 시스템 서비스 등록 (선택사항)
```bash
# 백엔드: /etc/systemd/system/rag-backend.service
# 프론트엔드: /etc/systemd/system/rag-frontend.service
# 관리자 페이지: /etc/systemd/system/rag-admin-frontend.service

sudo systemctl daemon-reload
sudo systemctl enable --now rag-backend rag-frontend rag-admin-frontend
```

---

## 3. Backend 파일별 용도

- **main.py**: FastAPI 앱 진입점, 엔드포인트 정의 (`/upload_file`, `/rag_query`, `/admin` 등)
- **config.py**: 환경 설정, MinerU 컨테이너 실행, Qwen2.5-VL 이미지 요약, 청킹 파라미터
- **rag_query_handler.py**: 질문 타입 분류, 필터/유사도 검색, Qwen-VL 이미지 검증, LLM 프롬프트 구성
- **vector_store.py**: Qdrant 벡터스토어 초기화/관리, 임베딩 모델/LLM 관리
- **file_handler.py**: 파일 업로드 처리, 구조 기반 청킹, 벡터스토어 저장
- **chat_history.py**: 채팅 히스토리 저장/조회
- **md_image.py**: 마크다운 이미지 → Data URI 변환

---

## 4. 데이터 흐름

### 파일 업로드
```
사용자 업로드 → MinerU OCR → Qwen2.5-VL 이미지 요약 → 구조 기반 청킹 → Qdrant 저장
```

### 질의응답
```
질문 → 질문 타입 분류 → 필터/유사도 검색 → 이미지 추출 → Qwen-VL 검증 → LLM 답변 생성
```

---
## 5. 주요 엔드포인트

### 업로드/문서
- `POST /upload_file`: 파일 업로드 및 임베딩
- `GET /upload_status/{filename}`: 업로드 처리 상태
- `GET /embedded_files`: 임베딩된 파일 목록

### 질의응답
- `POST /rag_query`: 질의응답
  ```json
  {
    "question": "샘플 장비 44014 에러 해결 방법 알려줘",
    "k": 5
  }
  ```

### 관리
- `GET /admin`: 관리자 페이지
- `GET /status`: 벡터DB 상태
- `POST /rebuild_vectorstore`: 벡터스토어 재구성
- `DELETE /delete_file/{filename}`: 문서 삭제

### 채팅 히스토리
- `GET /chat_history`: 채팅 목록
- `POST /chat_history`: 채팅 저장
- `DELETE /chat_history/{chat_id}`: 채팅 삭제

---

## 6. 디렉터리 구조

```
AI-KnowledgeOps/
├── backend/              # 백엔드 (FastAPI)
│   ├── main.py
│   ├── config.py
│   ├── rag_query_handler.py
│   ├── vector_store.py
│   ├── file_handler.py
│   └── requirements.txt
├── frontend/             # 클라이언트 UI
├── admin-frontend/       # 관리자 UI
├── input/                # 업로드된 원본 파일
├── output/               # MinerU 변환 결과
├── qdrant_storage/       # Qdrant 벡터DB
└── chat_history/         # 채팅 기록
```

---
## 7. 실행 방법

### 7.1 백엔드 실행
```bash
docker start qdrant mineru-vllm  # 컨테이너 시작
cd backend
source .venv/bin/activate
uvicorn main:app --host localhost --port 8601
```

### 7.2 프론트엔드 실행
```bash
cd frontend && npm install && npm run dev -- --host localhost --port 8901
cd admin-frontend && npm install && npm run dev -- --host localhost --port 8902
```

**접속 URL**:
- 클라이언트 UI: http://localhost:8901
- 관리자 UI: http://localhost:8902
- API 문서: http://localhost:8601/docs

---

## 8. 포트 정보

- Qdrant: 6333
- 클라이언트 UI: 8901
- 관리자 UI: 8902
- FastAPI Backend: 8601
- MinerU: 30000, 7860, 8010

## 9. 참고문헌

- [MinerU GitHub](https://github.com/opendatalab/MinerU)
- [Qdrant Documentation](https://qdrant.tech/documentation/quickstart/)
- [Qwen2.5-VL Model](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct)
- [Qwen3-VL Model](https://ollama.com/library/qwen3-vl)


