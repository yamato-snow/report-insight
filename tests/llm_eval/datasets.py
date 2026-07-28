"""評価データセット3種（分類100 / 検索30 / 忠実性20）。LLM設計書 §4。

- 分類: scripts.synth の正解ラベル付きサンプルを再利用（境界例・悪文・PII・injection を含む）。
- 検索: 一意な内容の文書30件とその想定質問（正解 report は文書と1:1）。recall@k を測る。
- 忠実性: 検索文書に基づく質問20件。回答が根拠に忠実か（LLM-as-judge）を測る。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from scripts.synth import Sample, generate

_HUMAN_CASES_PATH = Path(__file__).resolve().parent / "human_cases.json"


@dataclass(frozen=True)
class ClassificationCase:
    raw_text: str
    reporter_role: str
    expected_category: str
    expected_urgency: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class SearchCase:
    """一意な文書とその想定質問。ingest 後、質問で当該文書が top-k に入るかを見る。

    distractor_doc_id が付くケースはハードネガティブ評価: 語彙は近いが内容の異なる
    「紛らわしい不正解文書」を指し、正解がそれより上位に来るかを別途測る。
    """

    doc_id: str  # source_key に使う一意キー
    raw_text: str
    question: str
    distractor_doc_id: str | None = None


@dataclass(frozen=True)
class FaithfulnessCase:
    """忠実性評価: 質問と、根拠に含まれるべき事実（judge の参照）。"""

    question: str
    grounded_fact: str


def classification_cases(count: int = 100) -> list[ClassificationCase]:
    """synth の合成報告書を分類評価ケースへ変換する（正解ラベル付き）。"""
    cases: list[ClassificationCase] = []
    for payload, sample in generate(count):
        _ = payload
        s: Sample = sample
        cases.append(
            ClassificationCase(
                raw_text=s.raw_text,
                reporter_role=s.reporter_role,
                expected_category=s.label.category.value,
                expected_urgency=s.label.urgency.value,
                tags=tuple(s.tags),
            )
        )
    return cases


def human_classification_cases(
    path: Path = _HUMAN_CASES_PATH,
) -> list[ClassificationCase]:
    """人間確認済みの還流ケースを読む（scripts/export_eval_cases.py が生成）。

    合成テンプレと違い「本番で実際に人が確定した正解ラベル」なので代表性が高い。
    ファイルが無い・空の場合は空リスト（還流前の状態を許容する）。
    """
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    cases: list[ClassificationCase] = []
    for item in data.get("cases", []):
        cases.append(
            ClassificationCase(
                raw_text=str(item["raw_text"]),
                reporter_role=str(item["reporter_role"]),
                expected_category=str(item["expected_category"]),
                expected_urgency=str(item["expected_urgency"]),
                tags=tuple(item.get("tags", ["human_verified"])),
            )
        )
    return cases


# --- 検索30問（文書と質問を1:1で対応。内容は一意） ------------------------
_SEARCH_DOCS: list[tuple[str, str]] = [
    ("3階居室の窓ガラスにひび割れを確認。飛散防止フィルムを応急施工。", "窓ガラスのひび割れの事例"),
    ("地下駐車場の照明が数本消灯。電球切れと思われる。", "駐車場の照明が消えている件"),
    ("エレベーターが2階で停止し扉が開かない。保守会社へ連絡済み。", "エレベーター停止のトラブル"),
    ("屋上防水シートの一部に浮きを発見。降雨時の漏水懸念。", "屋上防水の浮きについて"),
    ("1階集合ポスト付近に落書き。清掃業者へ除去依頼。", "落書きの被害報告"),
    ("受水槽まわりで漏水跡。バルブ増し締めで一旦停止。", "受水槽の漏水対応"),
    ("共用階段の手すりがぐらつく。ボルト緩みを確認。", "手すりのぐらつきの件"),
    ("宅配ボックスの電子錠が反応しない。電池切れの可能性。", "宅配ボックスの不具合"),
    ("植栽帯に害虫の巣を発見。専門業者に駆除を依頼予定。", "害虫・害獣の発生報告"),
    ("非常階段の防火扉が閉まりきらない。ヒンジ調整が必要。", "防火扉が閉まらない件"),
    ("給湯室の蛇口から水が止まらない。パッキン劣化と推定。", "蛇口の水漏れの事例"),
    ("駐輪場の屋根トタンが強風で一部めくれた。飛散注意。", "駐輪場の屋根の破損"),
    ("エントランス床タイルが浮き、つまずき危険。カラーコーン設置。", "床タイルの浮きの報告"),
    ("2階廊下の火災報知器が誤作動。点検を手配。", "火災報知器の誤作動"),
    ("空調室外機から異音。ファン軸受けの劣化か。", "空調の異音の件"),
    ("敷地内側溝が落ち葉で詰まり、排水不良。清掃実施。", "側溝の詰まり・排水不良"),
    ("601号室からの生活騒音について階下より苦情。", "騒音の苦情事例"),
    ("集合玄関のオートロックが開きっぱなし。制御盤確認要。", "オートロックの不具合"),
    ("外壁タイルの一部が剥落し地面に落下。立入制限を実施。", "外壁タイル剥落の報告"),
    ("共用トイレの換気扇が回らない。モーター交換の見込み。", "換気扇が動かない件"),
    ("駐車場ゲートのバーが上がらず車両が出られない。", "駐車場ゲートの故障"),
    ("屋内消火栓の圧力計が規定値を下回る。点検依頼。", "消火栓の圧力低下"),
    ("植木の枝が越境し隣地から苦情。剪定を予定。", "越境した植木への苦情"),
    ("エントランス自動ドアのセンサー反応が鈍い。清掃と調整。", "自動ドアのセンサー不良"),
    ("地下ピットに汚水の滞留。ポンプ稼働を確認中。", "地下ピットの汚水滞留"),
    ("共用廊下のLED照明が点滅を繰り返す。安定器の不良か。", "照明の点滅の事例"),
    ("メールボックスの鍵が破損し開かないと入居者から連絡。", "メールボックスの鍵の破損"),
    ("受電設備の月次点検で軽微な絶縁低下を指摘された。", "受電設備の絶縁低下"),
    ("屋上フェンスの一部が腐食。転落防止のため補修要。", "屋上フェンスの腐食"),
    ("ゴミ集積所の扉が破損し閉まらない。カラス被害の懸念。", "ゴミ集積所の扉の破損"),
]


# --- ハードネガティブ10問（語彙は既存文書と重なるが内容が異なる） ------------
#
# recall@k はコーパスが小さいうちは易しく飽和する。ここでは「同じ設備名を含む別事象」を
# 意図的に置き、質問に対して正解が紛らわしい文書より上位に来るか（win rate）を測る。
# タプル: (本文, 質問, 紛らわしい既存文書の _SEARCH_DOCS インデックス)
_HARD_NEGATIVES: list[tuple[str, str, int]] = [
    (
        "エレベーターの走行音がうるさいと2階入居者から苦情。巻上機の防振ゴム劣化を調査予定。",
        "エレベーターの騒音に関する苦情",
        2,  # エレベーター停止（故障）と混同しやすい
    ),
    (
        "3階居室の窓ガラスの結露がひどくサッシ枠にカビが発生。換気の指導と防露フィルムを検討。",
        "窓の結露とカビの相談",
        0,  # 窓ガラスのひび割れと混同しやすい
    ),
    (
        "宅配ボックスの扉が物理的に変形して閉まらない。いたずらの可能性があり警察へ相談予定。",
        "宅配ボックスの扉の変形",
        7,  # 電子錠の電池切れと混同しやすい
    ),
    (
        "屋上防水の全面改修工事について3社から見積を取得。次年度予算での実施を計画中。",
        "屋上防水の改修工事の計画",
        3,  # 防水シートの浮き（不具合報告）と混同しやすい
    ),
    (
        "駐車場ゲートのリモコン送信機を増設してほしいと入居者から要望があった。",
        "駐車場ゲートのリモコン追加の要望",
        20,  # ゲートバーの故障と混同しやすい
    ),
    (
        "火災報知器の電池切れ警告音が鳴っているとの連絡。該当住戸の電池交換で解消した。",
        "報知器の電池切れ警告への対応",
        13,  # 報知器の誤作動と混同しやすい
    ),
    (
        "外壁タイルの汚れが目立つため高圧洗浄を実施。美観が回復した。",
        "外壁タイルの洗浄作業",
        18,  # タイルの剥落と混同しやすい
    ),
    (
        "受水槽の法定清掃を実施し、水質検査も適合。報告書を保管した。",
        "受水槽の清掃と水質検査",
        5,  # 受水槽の漏水と混同しやすい
    ),
    (
        "エントランス自動ドアのガラスに衝突防止シールを追加で貼付した。",
        "自動ドアの衝突防止対策",
        23,  # センサー不良と混同しやすい
    ),
    (
        "敷地内側溝のコンクリート蓋が破損し段差が発生。仮養生のうえ交換を手配。",
        "側溝の蓋の破損",
        15,  # 側溝の落ち葉詰まりと混同しやすい
    ),
]


def search_cases() -> list[SearchCase]:
    base = [
        SearchCase(doc_id=f"eval/search/{i:03d}.json", raw_text=doc, question=q)
        for i, (doc, q) in enumerate(_SEARCH_DOCS)
    ]
    hard = [
        SearchCase(
            doc_id=f"eval/search/h{i:03d}.json",
            raw_text=doc,
            question=q,
            distractor_doc_id=f"eval/search/{d:03d}.json",
        )
        for i, (doc, q, d) in enumerate(_HARD_NEGATIVES)
    ]
    return base + hard


# --- 忠実性20問（検索文書の事実に基づく。judge が根拠適合を採点） --------------
_FAITHFULNESS: list[tuple[str, str]] = [
    ("窓ガラスのひび割れにどう対応した？", "飛散防止フィルムを応急施工した"),
    ("駐車場の照明の原因は？", "電球切れと思われる"),
    ("エレベーター停止時の対応は？", "保守会社へ連絡した"),
    ("屋上防水の懸念は何か？", "降雨時の漏水懸念"),
    ("落書きへの対応は？", "清掃業者へ除去を依頼した"),
    ("受水槽の漏水はどう止めた？", "バルブの増し締めで一旦停止した"),
    ("手すりの不具合の原因は？", "ボルトの緩み"),
    ("宅配ボックスの不具合の推定原因は？", "電池切れの可能性"),
    ("害虫の巣への対応予定は？", "専門業者に駆除を依頼予定"),
    ("防火扉の不具合に必要な作業は？", "ヒンジ調整が必要"),
    ("給湯室の蛇口の推定原因は？", "パッキンの劣化"),
    ("駐輪場の屋根はなぜ破損した？", "強風で一部めくれた"),
    ("火災報知器の状態は？", "誤作動した"),
    ("空調室外機の異音の推定原因は？", "ファン軸受けの劣化"),
    ("側溝の詰まりの原因は？", "落ち葉"),
    ("601号室に関する苦情の内容は？", "生活騒音"),
    ("外壁タイル剥落後の措置は？", "立入制限を実施した"),
    ("駐車場ゲートで何が起きた？", "バーが上がらず車両が出られない"),
    ("消火栓の点検で何が分かった？", "圧力計が規定値を下回る"),
    ("ゴミ集積所の扉の破損で懸念されることは？", "カラス被害の懸念"),
]


def faithfulness_cases() -> list[FaithfulnessCase]:
    return [FaithfulnessCase(question=q, grounded_fact=f) for q, f in _FAITHFULNESS]
