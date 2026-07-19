"""EmfMetrics — CloudWatch EMF（Embedded Metric Format）でメトリクスを送出する。

CloudWatch Logs は、ログイベントに `_aws.CloudWatchMetrics` を含む JSON があると
それを自動でカスタムメトリクス化する（EMF）。よって boto3 も追加依存も要らず、
**stdout に構造化 JSON を1行吐く**だけで本番はメトリクスになる。ローカルでは
その JSON が標準出力に出るところまでを（ユニットで決定的に）検証できる。

EMF 仕様: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format_Specification.html
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Mapping, Sequence
from typing import TextIO

# EMF の Timestamp はミリ秒。structlog を通さず生 JSON を書くのは、CloudWatch の
# メトリクス抽出が余計なキー（level/event 等）に依存しない素の EMF を保つため。


class EmfMetrics:
    """MetricsPort の EMF 実装（stdout へ EMF JSON を書く）。

    Args:
        namespace: CloudWatch メトリクス名前空間（例: ``ReportInsight``）。
        dimensions: 全メトリクスに付与する基底ディメンション（例: Env/Service）。
        stream: 出力先（既定 stdout。テストは ``StringIO`` を差し込む）。
    """

    def __init__(
        self,
        *,
        namespace: str,
        dimensions: Mapping[str, str],
        stream: TextIO | None = None,
    ) -> None:
        self._namespace = namespace
        self._dims = dict(dimensions)
        self._stream = stream if stream is not None else sys.stdout

    def incr(self, name: str, value: int = 1, **dimensions: str) -> None:
        dims = {**self._dims, **dimensions}
        self._write([(name, value, "Count")], [list(dims)], dims)

    def emit_tokens(self, *, input_tokens: int, output_tokens: int, **dimensions: str) -> None:
        dims = {**self._dims, **dimensions}
        # 基底ディメンション（Env/Service）に加え、Env のみの集計ストリームも同時に出す。
        # これで「サービス横断の日次トークン総量」を単一メトリクスとして持て、
        # コストアラームが SEARCH() を使わずに（=単一時系列で）評価できる。
        dim_sets: list[list[str]] = [list(dims)]
        if "Env" in dims and list(dims) != ["Env"]:
            dim_sets.append(["Env"])
        self._write(
            [("tokens_input", input_tokens, "Count"), ("tokens_output", output_tokens, "Count")],
            dim_sets,
            dims,
        )

    def _write(
        self,
        metrics: Sequence[tuple[str, int, str]],
        dimension_sets: Sequence[Sequence[str]],
        dims: Mapping[str, str],
    ) -> None:
        payload: dict[str, object] = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": self._namespace,
                        "Dimensions": [list(ds) for ds in dimension_sets],
                        "Metrics": [{"Name": n, "Unit": u} for n, _, u in metrics],
                    }
                ],
            },
            **dict(dims),
            **{n: v for n, v, _ in metrics},
        }
        self._stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._stream.flush()
