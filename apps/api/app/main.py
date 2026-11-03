"""SciLoom API 入口。"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import get_settings
from .routers import documents, qa

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="SciLoom API",
    description="基于大模型与 Agent 架构的全流程科研助手",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router, prefix="/api")
app.include_router(qa.router, prefix="/api")


@app.get("/api/health", tags=["system"])
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "env": settings.app_env,
        "model": settings.llm_model,
        "data_dir": str(settings.data_dir),
    }
