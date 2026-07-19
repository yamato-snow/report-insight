"""アプリ設定（pydantic-settings）。env は開発環境 08 §4 が正。"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(StrEnum):
    FAKE = "fake"
    ANTHROPIC = "anthropic"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- LLM ---
    llm_provider: LLMProvider = LLMProvider.FAKE
    anthropic_api_key: str = ""
    model_classify: str = "claude-haiku-4-5-20251001"
    model_generate: str = "claude-sonnet-5"
    llm_max_concurrency: int = 4
    confidence_threshold: float = 0.85

    # --- 埋め込み ---
    embedding_model: str = "intfloat/multilingual-e5-large"
    embedding_dim: int = 1024

    # --- AWS（ローカルは LocalStack） ---
    aws_endpoint_url: str | None = None
    aws_region: str = "ap-northeast-1"
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"  # noqa: S105 — LocalStackダミー。本番はSecrets Manager
    s3_inbox_bucket: str = "report-inbox"
    sqs_queue_url: str = "http://localstack:4566/000000000000/report-queue"

    # --- DB / 通知 ---
    database_url: str = "postgresql+asyncpg://app:app@db:5432/report_insight"
    slack_webhook_url: str = "http://webhook-mock:9000/webhook"

    # --- 実行 ---
    log_level: str = Field(default="INFO")

    # --- 観測（EMF メトリクス） ---
    # env は CloudWatch ディメンション（dev/prod）。ECS からは RI_ENV で注入する。
    env: str = Field(default="local", validation_alias="RI_ENV")
    metrics_namespace: str = "ReportInsight"


@lru_cache
def get_settings() -> Settings:
    """プロセス内シングルトン設定。"""
    return Settings()
