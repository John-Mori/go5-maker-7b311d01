"""Shift-JIS(cp932) の DMMアフィ報酬明細CSVを解析する。

実CSVの列(2026-09 実物のエクスポートで確認):
    サービス, 品番, 商品タイトル, 販売金額, 報酬体系, 報酬件数, 報酬額

★列は「名前」で引く(位置で引かない)。DMM側で列が増減しても、
  必須列が在る限り動く。必須列が欠けたら黙らず ReportFormatError を投げる
  (GLの穴=「列が変わった」を握り潰さないため)。
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

# DMMアフィCSVの列名(実物準拠)。別名も許容する。
COL_SERVICE = "サービス"
COL_CODE = "品番"
COL_TITLE = "商品タイトル"
COL_SALE = "販売金額"
COL_TYPE = "報酬体系"
COL_COUNT = "報酬件数"
COL_AMOUNT = "報酬額"

REQUIRED_COLUMNS = (COL_SERVICE, COL_CODE, COL_TYPE, COL_COUNT, COL_AMOUNT)


class ReportFormatError(ValueError):
    """CSVの形が想定と違う(列欠落など)。黙って0件にせず、これを投げる。"""


@dataclass
class RewardRow:
    service: str
    product_code: str
    title: str
    sale_price: int | None
    reward_type: str
    reward_count: int
    reward_amount: int
    raw: dict = field(default_factory=dict, repr=False)


def _to_int(value: str | None) -> int:
    """"1,912" や "560円" のような表記も整数へ。空は0。"""
    if value is None:
        return 0
    s = str(value).strip().replace(",", "").replace("円", "").replace("¥", "")
    if s in ("", "-"):
        return 0
    try:
        return int(float(s))
    except ValueError as e:
        raise ReportFormatError(f"数値として読めない値: {value!r}") from e


def _to_int_or_none(value: str | None) -> int | None:
    if value is None or str(value).strip() in ("", "-"):
        return None
    return _to_int(value)


def parse_report_text(text: str) -> list[RewardRow]:
    """デコード済みテキスト → 明細行。テスト・パイプの合流点はここ。"""
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise ReportFormatError("CSVが空(ヘッダ行すら無い)")

    header = [h.strip() for h in header]
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise ReportFormatError(
            f"必須列が欠けています: {missing} / 実際の列: {header}"
        )
    idx = {name: header.index(name) for name in header}

    def cell(row: list[str], name: str) -> str | None:
        i = idx.get(name)
        if i is None or i >= len(row):
            return None
        return row[i]

    rows: list[RewardRow] = []
    for lineno, row in enumerate(reader, start=2):
        if not any(c.strip() for c in row):
            continue  # 空行スキップ
        try:
            rows.append(
                RewardRow(
                    service=(cell(row, COL_SERVICE) or "").strip(),
                    product_code=(cell(row, COL_CODE) or "").strip(),
                    title=(cell(row, COL_TITLE) or "").strip(),
                    sale_price=_to_int_or_none(cell(row, COL_SALE)),
                    reward_type=(cell(row, COL_TYPE) or "").strip(),
                    reward_count=_to_int(cell(row, COL_COUNT)),
                    reward_amount=_to_int(cell(row, COL_AMOUNT)),
                    raw={name: cell(row, name) for name in header},
                )
            )
        except ReportFormatError as e:
            raise ReportFormatError(f"{lineno}行目: {e}") from e
    return rows


def load_report_csv(path: str | Path, encoding: str = "cp932") -> list[RewardRow]:
    """CSVファイル → 明細行。既定 cp932(Shift-JIS)。

    cp932 でデコードできなければ utf-8-sig / utf-8 を試すが、
    どれも失敗したら例外を上げる(握り潰さない)。
    """
    data = Path(path).read_bytes()
    last_err: Exception | None = None
    for enc in (encoding, "utf-8-sig", "utf-8"):
        try:
            text = data.decode(enc)
            return parse_report_text(text)
        except UnicodeDecodeError as e:
            last_err = e
            continue
    raise ReportFormatError(f"文字コードを判定できない: {path} ({last_err})")
