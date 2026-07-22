"""シナリオ実行 CLI。`make scenario` / `make scenario NAME=xxx` から呼ばれる。

全シナリオ（または名前指定の1本）を流し、OK/NG を表示して終了コードで合否を返す。
実 API を呼ばず決定的なので CI にそのまま組み込める（課金ゼロ）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from tests.scenarios.runner import ScenarioResult, list_scenarios, run_scenario

_GREEN = "\033[32m"
_RED = "\033[31m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _fmt(result: ScenarioResult) -> str:
    mark = f"{_GREEN}OK{_RESET}" if result.ok else f"{_RED}NG{_RESET}"
    lines = [f"[{mark}] {result.name}  {_DIM}({', '.join(result.requirements)}){_RESET}"]
    if not result.ok:
        for c in result.failed_checks:
            lines.append(f"    {_RED}✗{_RESET} {c.field}: 期待={c.expected!r} 実際={c.actual!r}")
    return "\n".join(lines)


async def _main() -> int:
    parser = argparse.ArgumentParser(description="受入シナリオを実行する")
    parser.add_argument("--name", default="", help="ファイル名の一部（部分一致で1本に絞る）")
    args = parser.parse_args()

    paths = list_scenarios()
    if args.name:
        paths = [p for p in paths if args.name in p.name]
    if not paths:
        print(f"{_RED}該当するシナリオがありません{_RESET}")
        return 2

    results = [await run_scenario(p) for p in paths]
    for r in results:
        print(_fmt(r))

    passed = sum(1 for r in results if r.ok)
    total = len(results)
    color = _GREEN if passed == total else _RED
    print(f"\n{color}{passed}/{total} シナリオ OK{_RESET}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
