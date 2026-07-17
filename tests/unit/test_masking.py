"""PIIマスキングの unit テスト（sudachi はローカルCPUのみ・外部I/Oなし）。"""

from __future__ import annotations

import asyncio

from app.infra.masking.pii import PIIMasker


async def test_pii_masker_masks_phone_and_email() -> None:
    masker = PIIMasker()

    result = await masker.mask("連絡先は test@example.com、電話 090-1234-5678 です。")

    assert "test@example.com" not in result.masked_text
    assert "090-1234-5678" not in result.masked_text
    assert "[EMAIL_1]" in result.masked_text
    assert "[PHONE_1]" in result.masked_text
    assert result.mapping["[EMAIL_1]"] == "test@example.com"


async def test_pii_masker_keeps_non_pii_text() -> None:
    masker = PIIMasker()

    result = await masker.mask("3階廊下で漏水が発生しました。")

    assert "漏水" in result.masked_text


async def test_pii_masker_is_thread_safe_under_concurrency() -> None:
    # sudachipy Tokenizer の "Already borrowed" 回帰防止（worker は to_thread で並行実行）
    masker = PIIMasker()

    results = await asyncio.gather(
        *(masker.mask(f"田中太郎さん {i} 番で漏水。電話 090-1234-5678") for i in range(50))
    )

    assert len(results) == 50
    assert all("[PHONE_1]" in r.masked_text for r in results)
