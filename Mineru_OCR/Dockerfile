# =====================================================================
# 🧠 MinerU + vLLM (GB10 / CUDA 13 / SM12.1)
# 범용 사용자 대응 이미지
# =====================================================================
FROM avarok/vllm-dgx-spark:v11

USER root

# ---------------------------------------------------------------------
# 📦 OS 패키지
# ---------------------------------------------------------------------
RUN apt-get update && \
    apt-get install -y \
        fonts-noto-core \
        fonts-noto-cjk \
        fontconfig \
        locales \
        libreoffice \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender-dev \
        curl \
        wget \
        unzip \
        vim && \
    locale-gen en_US.UTF-8 ko_KR.UTF-8 && \
    update-locale LANG=ko_KR.UTF-8 LC_ALL=ko_KR.UTF-8 && \
    fc-cache -fv && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------
# 🐍 Python 패키지
# ---------------------------------------------------------------------
RUN python3 -m pip install -U pip setuptools wheel --break-system-packages && \
    python3 -m pip install -U \
        "mineru[core]>=2.7.0" \
        beautifulsoup4 \
        --break-system-packages && \
    python3 -m pip cache purge

# ---------------------------------------------------------------------
# 🤖 MinerU 모델 (한 번만)
# ---------------------------------------------------------------------
RUN mineru-models-download -s huggingface -m all

# ---------------------------------------------------------------------
# 🌏 환경 변수
# ---------------------------------------------------------------------
ENV LANG=ko_KR.UTF-8
ENV LC_ALL=ko_KR.UTF-8
ENV MINERU_MODEL_SOURCE=local

# vLLM 안정성 (GB10 필수)
ENV VLLM_DISABLE_LOG_STATS=1
ENV VLLM_WORKER_MULTIPROC_METHOD=spawn

# ---------------------------------------------------------------------
# 📂 작업 디렉토리
# ---------------------------------------------------------------------
WORKDIR /workspace

# ⚠ USER 고정하지 않음 (런타임에서 지정)
ENTRYPOINT ["/bin/bash"]
