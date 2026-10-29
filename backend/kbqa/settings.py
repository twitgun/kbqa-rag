"""进程级配置：只放密钥与路径，业务参数一律走 app_configs 表（见 ADR-019）。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]  # D:\bishe


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # 数据库：MySQL 8（见 ADR-004）
    database_url: str = "mysql+pymysql://root:@127.0.0.1:3306/kbqa?charset=utf8mb4"

    # 生成模型
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"

    # 路径
    data_dir: Path = ROOT / "data"
    model_dir: Path = ROOT / "runtime" / "models"

    # 向量模型：目录名，位于 model_dir 下。默认 BGE-M3；带宽不足可先用小模型。
    embedding_model: str = "bge-m3"
    embedding_device: str = "cpu"
    embedding_batch_size: int = 8

    # 重排模型：目录名；缺失时自动跳过重排（降级为双塔分数）
    reranker_model: str = "bge-reranker-v2-m3"
    rerank_enabled: bool = True
    rerank_batch_size: int = 8

    # 生成前的可答性判定（多一次调用，约 1s）
    answerability_check: bool = False
    # 只在检索最高分 ≥ 此值时调用可答性判定（低于它已被 τ 拦住）
    answerability_min_score: float = 0.70

    # 服务
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    app_version: str = "0.1.0"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def bm25_file(self) -> Path:
        return self.data_dir / "bm25" / "bm25.pkl"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
