"""PIIマスキング実装。LLM API送信前に個人名・電話番号・メールを伏せる（LLM設計書 §3）。

- 正規表現: 電話番号・メールアドレス
- 形態素解析(sudachipy): 固有名詞の人名 → [PERSON_n]
辞書ベースの人名検出は完全でないため多層防御の一層と位置づける（§3 の限界認識）。
"""

from __future__ import annotations

import asyncio
import re
import threading

from sudachipy import Tokenizer, dictionary, tokenizer

from app.domain.entities import MaskingResult

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"0\d{1,4}-?\d{1,4}-?\d{3,4}")


class PIIMasker:
    """PIIMaskerPort の実装。

    sudachipy の Tokenizer はスレッド安全でない（並行呼び出しで "Already borrowed"）。
    asyncio.to_thread は複数スレッドで実行されるため、Tokenizer はスレッドローカルに保持する。
    Dictionary は共有可能なので1つだけ生成し、各スレッドが create() で Tokenizer を得る。
    """

    def __init__(self) -> None:
        self._dictionary = dictionary.Dictionary()
        self._mode = tokenizer.Tokenizer.SplitMode.C
        self._local = threading.local()

    def _tokenizer(self) -> Tokenizer:
        tok = getattr(self._local, "tokenizer", None)
        if tok is None:
            tok = self._dictionary.create()
            self._local.tokenizer = tok
        return tok

    async def mask(self, text: str) -> MaskingResult:
        # 形態素解析は CPU バウンドのため別スレッドへ（規約 §3）
        return await asyncio.to_thread(self._mask_sync, text)

    def _mask_sync(self, text: str) -> MaskingResult:
        mapping: dict[str, str] = {}
        counters = {"EMAIL": 0, "PHONE": 0, "PERSON": 0}

        def _placeholder(kind: str, original: str) -> str:
            counters[kind] += 1
            token = f"[{kind}_{counters[kind]}]"
            mapping[token] = original
            return token

        # 先に人名を伏せる。後段の正規表現がプレースホルダを再分割しないようこの順にする
        pieces: list[str] = []
        for token in self._tokenizer().tokenize(text, self._mode):
            pos = token.part_of_speech()
            surface = token.surface()
            if len(pos) >= 3 and pos[1] == "固有名詞" and pos[2] == "人名":
                pieces.append(_placeholder("PERSON", surface))
            else:
                pieces.append(surface)
        masked = "".join(pieces)

        # 正規表現（メール→電話の順。電話が誤爆しないようメールを先に伏せる）
        masked = _EMAIL_RE.sub(lambda m: _placeholder("EMAIL", m.group(0)), masked)
        masked = _PHONE_RE.sub(lambda m: _placeholder("PHONE", m.group(0)), masked)

        return MaskingResult(masked_text=masked, mapping=mapping)
