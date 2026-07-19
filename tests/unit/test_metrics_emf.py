"""EmfMetrics（CloudWatch EMF 送出）の unit テスト（AWS 不要・決定的）。

EMF の形（`_aws.CloudWatchMetrics` / Namespace / Dimensions / Metric 名）と、
トークン送出が「Env/Service 粒度」と「Env 集計」の2ストリームを持つことを検証する。
"""

from __future__ import annotations

import io
import json

from app.infra.observability.emf import EmfMetrics


def _emit_and_parse(fn) -> list[dict]:
    buf = io.StringIO()
    metrics = EmfMetrics(
        namespace="ReportInsight",
        dimensions={"Env": "dev", "Service": "worker"},
        stream=buf,
    )
    fn(metrics)
    return [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]


def test_incr_emits_valid_emf() -> None:
    (record,) = _emit_and_parse(lambda m: m.incr("structured_failure"))

    aws = record["_aws"]
    assert isinstance(aws["Timestamp"], int)
    directive = aws["CloudWatchMetrics"][0]
    assert directive["Namespace"] == "ReportInsight"
    assert directive["Dimensions"] == [["Env", "Service"]]
    assert {"Name": "structured_failure", "Unit": "Count"} in directive["Metrics"]
    # ディメンション値とメトリクス値がトップレベルにあること（EMF の必須要件）
    assert record["Env"] == "dev"
    assert record["Service"] == "worker"
    assert record["structured_failure"] == 1


def test_incr_custom_value() -> None:
    (record,) = _emit_and_parse(lambda m: m.incr("api_error", 3))
    assert record["api_error"] == 3


def test_emit_tokens_has_env_and_service_streams() -> None:
    (record,) = _emit_and_parse(lambda m: m.emit_tokens(input_tokens=120, output_tokens=42))

    directive = record["_aws"]["CloudWatchMetrics"][0]
    # 粒度（Env+Service）とコスト集計用（Env のみ）の2ディメンションセット
    assert ["Env", "Service"] in directive["Dimensions"]
    assert ["Env"] in directive["Dimensions"]
    names = {metric["Name"] for metric in directive["Metrics"]}
    assert names == {"tokens_input", "tokens_output"}
    assert record["tokens_input"] == 120
    assert record["tokens_output"] == 42
