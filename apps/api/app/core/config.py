"""全局配置：从环境变量 / .env 读取，禁止在代码中硬编码密钥。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/app/core/config.py -> 仓库根目录
ROOT_DIR = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    log_level: str = "INFO"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    data_dir: Path = ROOT_DIR / "data"
    max_upload_mb: int = 200

    # 解析
    chunk_size: int = 800
    chunk_overlap: int = 120
    max_pages_inline: int = 200
    ocr_engine: str = "paddle"

    # 模型
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_reasoning_model: str = ""
    embedding_backend: str = "local"
    embedding_model: str = "BAAI/bge-m3"
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_dim: int = 1024
    rerank_enabled: bool = True

    # 学术数据源
    arxiv_max_results: int = 50
    arxiv_request_delay: int = 3

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def docs_dir(self) -> Path:
        return self.data_dir / "docs"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.docs_dir.mkdir(parents=True, exist_ok=True)
    return settings
