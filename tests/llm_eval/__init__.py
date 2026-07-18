"""LLM 評価ハーネス（実API・要APIキー。LLM設計書 §4 / P1 §4.3）。

`make eval`（= python -m tests.llm_eval.run）で実行する。評価ロジック（evaluators）は
ポート注入で純粋化し、Fake でも回せる（分類評価は tests/unit/test_llm_eval.py が検証）。
"""
