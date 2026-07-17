"""緊急度「高」通知の受け口モック（開発環境 08 §3 / compose の webhook-mock）。

受信したペイロードをメモリに保持し、integration テストが GET /received で検証する。
アーキテクチャの app/ には属さない開発補助ツールのため tools/ に置く。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request

app = FastAPI(title="webhook-mock")

_received: list[dict[str, Any]] = []


@app.post("/webhook")
async def webhook(request: Request) -> dict[str, str]:
    payload = await request.json()
    _received.append(payload)
    return {"status": "ok"}


@app.get("/received")
async def received() -> dict[str, Any]:
    return {"count": len(_received), "items": _received}


@app.delete("/received")
async def clear() -> dict[str, str]:
    _received.clear()
    return {"status": "cleared"}
