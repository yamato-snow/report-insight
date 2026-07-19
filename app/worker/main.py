"""SQS 構造化ワーカー。受信→S3イベント解析→ingest サービス呼び出し（基本設計 §2.1）。

- 同時実行数は Semaphore で制御（コーディング規約 §3 / LLM設計書 §6）
- RetryableError は削除せず SQS 再配信に委ね、3回失敗で DLQ 隔離（キュー設定）
"""

from __future__ import annotations

import asyncio
import signal

from app.core.config import get_settings
from app.core.db import unit_of_work
from app.core.di import Container, build_container
from app.core.logging import configure_logging, get_logger
from app.domain.errors import RetryableError
from app.infra.aws.sqs import SqsMessage
from app.services.ingest import parse_s3_event

logger = get_logger("worker")


async def process_message(container: Container, message: SqsMessage) -> None:
    """1メッセージを処理する。失敗時は例外を送出（=削除せず再配信）。

    複数キーの一部だけ成功して再配信された場合も、source_key の冪等UPSERTで
    二重登録は防がれる（基本設計 §2.1）。
    """
    keys = parse_s3_event(message.body)
    if not keys:
        logger.warning("worker.no_keys_in_message")
        return

    for key in keys:
        async with unit_of_work(container.session_factory) as session:
            service = container.ingest_service(session)
            await service.ingest_from_key(key)


async def _consume_loop(container: Container, stop: asyncio.Event) -> None:
    settings = container.settings
    semaphore = asyncio.Semaphore(settings.llm_max_concurrency)

    async def _handle(message: SqsMessage) -> None:
        async with semaphore:
            try:
                await process_message(container, message)
            except RetryableError:
                logger.warning("worker.retryable_left_for_redelivery")
                return  # 削除しない → SQS 再配信
            except Exception:
                logger.exception("worker.failed_left_for_redelivery")
                return
            await container.sqs.delete(message.receipt_handle)

    logger.info("worker.started", queue=settings.sqs_queue_url)
    while not stop.is_set():
        messages = await container.sqs.receive(max_messages=10, wait_seconds=20)
        if not messages:
            continue
        await asyncio.gather(*(_handle(m) for m in messages))


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    container = build_container(settings, service="worker")
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    try:
        await _consume_loop(container, stop)
    finally:
        await container.aclose()
        logger.info("worker.stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
