"""テスト用の合成CSVを cp932 で作る。★実データは使わない(全て架空)。

実物の列順に合わせる:
    サービス, 品番, 商品タイトル, 販売金額, 報酬体系, 報酬件数, 報酬額
"""
from __future__ import annotations

from pathlib import Path

HEADER = ["サービス", "品番", "商品タイトル", "販売金額", "報酬体系", "報酬件数", "報酬額"]

# 架空データ(実在の作品・品番ではない)
ROWS_DAY1 = [
    ["同人 同人", "d_000001", "テスト作品アルファ", "1100", "ダイレクト", "1", "385"],
    ["同人 同人", "d_000002", "テスト作品ベータ", "990", "カテゴリ", "3", "1000"],
    ["同人 同人", "d_000003", "テスト作品ガンマ", "660", "カテゴリ", "2", "500"],
    ["FANZAブックス FANZAブックス", "b000001", "テスト書籍デルタ", "660", "ダイレクト", "2", "560"],
    ["同人 同人", "d_000004", "テスト作品イプシロン", "1800", "サービス新規", "1", "1800"],
]
ROWS_DAY2 = [
    ["同人 同人", "d_000001", "テスト作品アルファ", "1100", "ダイレクト", "2", "770"],
    ["同人 同人", "d_000002", "テスト作品ベータ", "990", "カテゴリ", "5", "1650"],
]


def _to_csv(rows: list[list[str]]) -> str:
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER)
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def write_cp932_csv(path: Path, rows: list[list[str]]) -> Path:
    path.write_bytes(_to_csv(rows).encode("cp932"))
    return path


def write_bad_csv(path: Path) -> Path:
    """必須列(報酬額)が欠けたCSV。"""
    text = "サービス,品番,商品タイトル\n同人 同人,d_1,タイトル\n"
    path.write_bytes(text.encode("cp932"))
    return path


def write_zero_byte_csv(path: Path) -> Path:
    """0バイトファイル(ダウンロード途中断・空応答を模す)。"""
    path.write_bytes(b"")
    return path


def write_header_only_csv(path: Path) -> Path:
    """ヘッダ行だけで明細0行 = 正常な「売上ゼロ」。取得失敗と混同してはいけない。"""
    path.write_bytes((",".join(HEADER) + "\n").encode("cp932"))
    return path


def write_html_login_csv(path: Path) -> Path:
    """セッション失効時にログイン画面のHTMLがCSVの体(200)で返るケース。"""
    html = (
        "<!DOCTYPE html><html><head><title>ログイン</title></head>"
        "<body>ログインしてください</body></html>"
    )
    path.write_bytes(html.encode("utf-8"))
    return path
