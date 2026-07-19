"""P1 劣化検知→改善フロー閉ループの unit テスト（実API/DB非依存・決定的）。

- ノイズ生成（表記ゆれ/欠損）で正解ラベルが不変であること
- 表記ゆれで Fake 分類器の精度が実際に下がること（劣化）
- 正規化辞書でその劣化が回復すること（改善フロー）
- ベースライン差分回帰が劣化を検知し、回復で解消すること
- 対応表の還流マージ（export_corrections）が重複排除して蓄積すること
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.export_corrections import merge
from scripts.synth import NOTATION_DRIFT, NoiseConfig, generate

from app.infra.text.normalize import Correction, TextNormalizer
from tests.llm_eval.loop_demo import _cases, _classify, _metrics
from tests.llm_eval.regression import compare


def test_noise_preserves_labels_and_tags() -> None:
    clean = generate(30, noise=NoiseConfig.clean())
    noisy = generate(30, noise=NoiseConfig(notation=1.0, missing=0.0))
    # 正解ラベルは不変（ノイズは本文だけを汚す）。
    for (_, c_sample), (_, n_sample) in zip(clean, noisy, strict=True):
        assert c_sample.label == n_sample.label
    # 少なくとも一部は表記ゆれが適用され drift タグが付く。
    assert any("drift" in s.tags for _, s in noisy)
    # 本文自体は変化している（キーワードがかなへ）。
    assert any(
        cp["raw_text"] != np["raw_text"] for (cp, _), (np, _) in zip(clean, noisy, strict=True)
    )


def test_notation_drift_defeats_keyword_classifier() -> None:
    # ドリフト後の本文に、正規形キーワードが残っていないことを確認（照合が外れる）。
    drifted_payload, _ = generate(1, noise=NoiseConfig(notation=1.0))[0]
    text = str(drifted_payload["raw_text"])
    # 最初のテンプレは「水漏れ」を含む → ドリフトで「みずもれ」になり漢字は消える。
    assert "水漏れ" not in text
    assert "みずもれ" in text


async def test_degradation_and_recovery() -> None:
    count = 120
    noise = NoiseConfig(notation=0.6, missing=0.2)
    normalizer = TextNormalizer([Correction(v, c) for c, v in NOTATION_DRIFT.items()])

    clean = await _classify(_cases(count, NoiseConfig.clean(), None))
    noisy = await _classify(_cases(count, noise, None))
    fixed = await _classify(_cases(count, noise, normalizer))

    # 劣化: 表記ゆれで精度が有意に下がる。
    assert noisy.accuracy < clean.accuracy - 0.05
    # 回復: 正規化でベースライン同等へ戻る（決定的なので一致するはず）。
    assert fixed.accuracy == clean.accuracy


async def test_regression_detects_then_clears() -> None:
    count = 120
    noise = NoiseConfig(notation=0.6, missing=0.2)
    normalizer = TextNormalizer([Correction(v, c) for c, v in NOTATION_DRIFT.items()])

    base = _metrics(await _classify(_cases(count, NoiseConfig.clean(), None)))
    noisy = _metrics(await _classify(_cases(count, noise, None)))
    fixed = _metrics(await _classify(_cases(count, noise, normalizer)))

    assert compare(base, noisy).regressed is True  # 劣化を検知
    assert compare(base, fixed).regressed is False  # 改善で解消


def test_regression_within_tolerance_not_flagged() -> None:
    base = {"classification": {"accuracy": 0.94}}
    # 許容幅 0.03 内の低下は回帰扱いしない。
    near = {"classification": {"accuracy": 0.92}}
    far = {"classification": {"accuracy": 0.88}}
    assert compare(base, near).regressed is False
    assert compare(base, far).regressed is True


def test_normalizer_empty_is_noop() -> None:
    norm = TextNormalizer.empty()
    assert norm.normalize("ろうすいが発生") == "ろうすいが発生"
    assert len(norm) == 0


def test_normalizer_from_file_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "g.json"
    p.write_text(
        json.dumps({"corrections": [{"variant": "ろうすい", "canonical": "漏水"}]}),
        encoding="utf-8",
    )
    norm = TextNormalizer.from_file(p)
    assert norm.normalize("3階でろうすい") == "3階で漏水"


def test_export_corrections_merge_dedups(tmp_path: Path) -> None:
    golden = tmp_path / "golden.json"
    golden.write_text(
        json.dumps({"corrections": [{"variant": "ろうすい", "canonical": "漏水"}]}),
        encoding="utf-8",
    )
    added, total = merge(
        golden,
        [
            {"variant": "ろうすい", "canonical": "漏水", "source": "human_verified"},  # 既存
            {"variant": "こしょう", "canonical": "故障", "source": "human_verified"},  # 新規
        ],
    )
    assert added == 1
    assert total == 2
    data = json.loads(golden.read_text(encoding="utf-8"))
    variants = {c["variant"] for c in data["corrections"]}
    assert variants == {"ろうすい", "こしょう"}
