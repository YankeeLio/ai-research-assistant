"""SciLoom API 入口。"""

from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import get_settings
from .routers import arxiv, documents, graph, qa, translation

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _warm_embedder() -> None:
    """启动即预热向量模型。

    BGE-M3 首次加载约 15-20 s，若留到第一个提问时才加载，用户会对着空面板等半分钟。
    放在后台线程里预热，服务启动期间不影响健康检查。
    """
    try:
        from .services.retrieval import get_embedder

        embedder = get_embedder()
        logger.info("向量模型就绪: %s (dim=%s)", embedder.name, getattr(embedder, "dim", "?"))
    except Exception as exc:  # noqa: BLE001 - 预热失败不应阻止服务启动
        logger.warning("向量模型预热失败: %s", exc)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    threading.Thread(target=_warm_embedder, name="warm-embedder", daemon=True).start()
    yield


app = FastAPI(
    title="SciLoom API",
    description="基于大模型与 Agent 架构的全流程科研助手",
    version="0.1.0",
    lifespan=lifespan,
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
app.include_router(translation.router, prefix="/api")
app.include_router(graph.router, prefix="/api")
app.include_router(arxiv.router, prefix="/api")


@app.get("/api/health", tags=["system"])
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "env": settings.app_env,
        "model": settings.llm_model,
        "data_dir": str(settings.data_dir),
    }
