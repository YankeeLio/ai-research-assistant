"""SciLoom API 入口。"""

from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import get_settings
from .routers import arxiv, documents, graph, qa, translation, writing

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


READINESS: dict[str, object] = {"embedder": False, "indexed": 0, "documents": 0, "warming": False}


def _warm_embedder() -> None:
    """启动即预热向量模型。

    BGE-M3 首次加载约 15-20 s，若留到第一个提问时才加载，用户会对着空面板等半分钟。
    放在后台线程里预热，服务启动期间不影响健康检查。
    """
    try:
        from .services.retrieval import get_embedder

        embedder = get_embedder()
        READINESS["embedder"] = True
        logger.info("向量模型就绪: %s (dim=%s)", embedder.name, getattr(embedder, "dim", "?"))
    except Exception as exc:  # noqa: BLE001 - 预热失败不应阻止服务启动
        logger.warning("向量模型预热失败: %s", exc)


def _warm_indexes() -> None:
    """后台补齐所有文档的向量索引。

    评审打开演示地址后的第一个问题如果还要现建索引，2C4G 的服务器上可能要等 1-2 分钟，
    第一印象直接崩掉。这里在启动后按顺序补建，并把进度暴露给 /api/health。
    """
    try:
        from .core import db
        from .services import qa

        rows = [r for r in db.list_documents() if r["status"] == "ready"]
        READINESS["documents"] = len(rows)
        READINESS["warming"] = True
        for row in rows:
            if row["page_count"] > 200:
                # 超长文档建索引要几十分钟，跳过（解析结果仍可用于阅读）
                continue
            try:
                index = qa.ensure_index(row["doc_id"])
                if index is not None:
                    READINESS["indexed"] = int(READINESS["indexed"]) + 1
                    logger.info("索引预热 %d/%d: %s", READINESS["indexed"], len(rows), row["title"][:30])
            except Exception as exc:  # noqa: BLE001 - 单篇失败不影响其他
                logger.warning("索引预热失败 %s: %s", row["doc_id"], exc)
    finally:
        READINESS["warming"] = False


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    threading.Thread(target=_warm_embedder, name="warm-embedder", daemon=True).start()
    threading.Thread(target=_warm_indexes, name="warm-indexes", daemon=True).start()
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
app.include_router(writing.router, prefix="/api")


@app.get("/api/health", tags=["system"])
def health() -> dict[str, object]:
    """健康检查同时暴露预热进度：部署脚本应等到 ready=true 再对外宣布地址。"""
    ready = bool(READINESS["embedder"]) and not READINESS["warming"]
    return {
        "status": "ok",
        "ready": ready,
        "env": settings.app_env,
        "model": settings.llm_model,
        "data_dir": str(settings.data_dir),
        "warmup": {
            "embedder": READINESS["embedder"],
            "indexed": READINESS["indexed"],
            "documents": READINESS["documents"],
            "warming": READINESS["warming"],
        },
    }
