# SciLoom API —— 单镜像包含解析、检索、OCR、翻译、图谱全部能力
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/hf \
    HF_ENDPOINT=https://hf-mirror.com

# PyMuPDF 运行期需要 GL/字体库；unrar 之类不需要，保持精简
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 fonts-dejavu-core curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖，利用层缓存：改业务代码不会触发重装
COPY pyproject.toml ./
RUN pip install --upgrade pip \
    && pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install \
        fastapi "uvicorn[standard]" pymupdf python-multipart pydantic-settings \
        httpx numpy networkx matplotlib \
        sentence-transformers transformers sentencepiece \
        rapidocr-onnxruntime

COPY app ./app

# 模型与数据都挂在卷上，容器重建不丢
VOLUME ["/models", "/app/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
