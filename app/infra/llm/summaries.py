"""デモ用の要約辞書（FakeLLMClient 専用）。

FakeLLMClient は実APIを呼ばない決定的スタブであり、本来「要約」を生成できない。
素朴に本文を先頭切り詰めすると、画面上で「AIの要約」と「原文」がほぼ同一になり、
要約という製品価値がデモで伝わらない。そこで合成報告書に限り、
テンプレートが持つ正解要約を本文から引く。

キーは「PIIマスキング後・正規化後」のテキスト。ingest は
  mask(raw_text) → normalize(...) → classify_report(text)
の順で呼ぶため、辞書側も同じ前処理を通した本文をキーにする必要がある。

意図的にフォールバックを残す:
- 表記ゆれ（drift）や情報欠損（missing）を注入した本文はキーに一致しない。
  これは正しい挙動で、「汚れた入力では要約品質も落ちる」ことを再現する
  （P1 劣化検知の前提を壊さない）。
- デモ以外の任意入力（受入テスト・手動投入）も一致しないため、
  呼び出し側は必ずフォールバックを用意すること。
"""

from __future__ import annotations

from functools import lru_cache


def _build() -> dict[str, str]:
    # scripts（開発用）を本番 import 経路に持ち込まないため遅延 import する。
    from scripts.templates import TEMPLATES  # noqa: PLC0415

    table: dict[str, str] = {}
    for sample in TEMPLATES:
        if sample.summary:
            table[_key(sample.raw_text)] = sample.summary
    return table


def _key(text: str) -> str:
    """本文を突き合わせ用キーへ正規化する（空白差異を吸収）。"""
    return "".join(text.split())


@lru_cache(maxsize=1)
def _table() -> dict[str, str]:
    try:
        return _build()
    except ImportError:  # scripts 非同梱の配布形態を許容する
        return {}


def lookup(masked_text: str) -> str | None:
    """マスキング済み本文に対応する正解要約を返す。無ければ None。

    マスキングで置換されたトークン（[PERSON_1] 等）を含む本文にも一致させるため、
    完全一致で引けない場合は、マスク前後で不変な部分を持つ候補を線形探索する。
    """
    key = _key(masked_text)
    table = _table()
    hit = table.get(key)
    if hit is not None:
        return hit
    # PII マスキングでキーがずれた場合の救済。マスクは本文の一部だけを
    # 置換するため、マスク済み本文の十分長い断片が元本文に含まれるはず。
    for original_key, summary in table.items():
        if _matches_masked(key, original_key):
            return summary
    return None


def _matches_masked(masked_key: str, original_key: str) -> bool:
    """マスク済みキーが元キーのマスク後の姿とみなせるか判定する。

    マスクトークンは '[' で始まり ']' で終わるため、'[' で分割した各断片が
    元テキストに順序どおり現れるかを見る（断片が短すぎる場合は誤検出を避ける）。
    """
    if "[" not in masked_key:
        return False
    pos = 0
    matched_chars = 0
    for chunk in masked_key.split("["):
        # ']' 以降がマスクトークンの後続テキスト。
        tail = chunk.split("]", 1)[-1] if "]" in chunk else chunk
        if not tail:
            continue
        found = original_key.find(tail, pos)
        if found < 0:
            return False
        pos = found + len(tail)
        matched_chars += len(tail)
    # 断片の合計が元テキストの過半を占める場合のみ同一とみなす。
    return matched_chars >= len(original_key) // 2
