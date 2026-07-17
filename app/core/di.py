"""Composition root（アーキテクチャ規約 §2: ポート実装の選択はここに集約）。

実LLM/Fake・S3/LocalStack の差し替えはすべてこの1箇所で決める。
domain/services はここを知らない（依存方向: core → infra は許容、逆は禁止）。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import LLMProvider, Settings
from app.core.db import create_engine, create_session_factory
from app.infra.aws.client import AwsConfig, make_session
from app.infra.aws.s3 import S3ObjectStorage
from app.infra.aws.sqs import SqsConsumer
from app.infra.db.repositories import (
    SqlReportRepository,
    SqlSearchRepository,
    SqlUserRepository,
)
from app.infra.embedding.fake_client import FakeEmbeddingClient
from app.infra.embedding.fastembed_client import FastEmbedClient
from app.infra.llm.anthropic_client import AnthropicLLMClient
from app.infra.llm.fake_client import FakeLLMClient
from app.infra.masking.pii import PIIMasker
from app.infra.notify.slack import SlackNotifier
from app.services.ingest import IngestService
from app.services.ports import (
    EmbeddingClient,
    LLMClient,
    NotificationPort,
    ObjectStoragePort,
    PIIMaskerPort,
)
from app.services.search import SearchService


@dataclass
class Container:
    """プロセス寿命の依存を束ねる。"""

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    llm: LLMClient
    embedder: EmbeddingClient
    masker: PIIMaskerPort
    storage: ObjectStoragePort
    notifier: NotificationPort
    sqs: SqsConsumer

    def ingest_service(self, session: AsyncSession) -> IngestService:
        return IngestService(
            storage=self.storage,
            masker=self.masker,
            llm=self.llm,
            embedder=self.embedder,
            repository=SqlReportRepository(session),
            notifier=self.notifier,
            confidence_threshold=self.settings.confidence_threshold,
        )

    def search_service(self, session: AsyncSession) -> SearchService:
        return SearchService(
            llm=self.llm,
            embedder=self.embedder,
            repository=SqlSearchRepository(session),
        )

    def user_repository(self, session: AsyncSession) -> SqlUserRepository:
        return SqlUserRepository(session)

    async def aclose(self) -> None:
        await self.engine.dispose()


def _build_llm(settings: Settings) -> LLMClient:
    if settings.llm_provider is LLMProvider.ANTHROPIC:
        return AnthropicLLMClient(
            api_key=settings.anthropic_api_key,
            model_classify=settings.model_classify,
            model_generate=settings.model_generate,
        )
    return FakeLLMClient()


def _build_embedder(settings: Settings) -> EmbeddingClient:
    # 仮定: provider=fake の時は決定的Fake埋め込みでオフライン・高速。
    # provider=anthropic の時のみ fastembed(e5-large) を使う。
    if settings.llm_provider is LLMProvider.ANTHROPIC:
        return FastEmbedClient(settings.embedding_model)
    return FakeEmbeddingClient(dim=settings.embedding_dim)


def build_container(settings: Settings) -> Container:
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    aws_config = AwsConfig(
        region=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
        access_key_id=settings.aws_access_key_id,
        secret_access_key=settings.aws_secret_access_key,
    )
    aws_session = make_session()
    return Container(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        llm=_build_llm(settings),
        embedder=_build_embedder(settings),
        masker=PIIMasker(),
        storage=S3ObjectStorage(aws_session, aws_config, settings.s3_inbox_bucket),
        notifier=SlackNotifier(settings.slack_webhook_url),
        sqs=SqsConsumer(aws_session, aws_config, settings.sqs_queue_url),
    )
