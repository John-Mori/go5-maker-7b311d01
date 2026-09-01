"""日次サマリの保存と前日比。

一つのCSV=ある期間の明細(日付列が無い)。よって「前日比」は
  今日パースしたサマリ vs 前回保存したサマリ
で取る。状態はローカルのJSON1本(利用者PCの中だけ)。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .aggregate import DailySummary


@dataclass
class Delta:
    amount: int
    count: int
    prev_date: str | None
    amount_pct: float | None
    count_pct: float | None

    def to_dict(self) -> dict:
        return {
            "amount": self.amount,
            "count": self.count,
            "prev_date": self.prev_date,
            "amount_pct": self.amount_pct,
            "count_pct": self.count_pct,
        }


def _pct(now: int, prev: int) -> float | None:
    if prev == 0:
        return None
    return (now - prev) / prev * 100.0


class StateStore:
    """{date: summary_dict} を1ファイルで持つ。追記のみ・既存日は上書き更新。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data: dict[str, dict] = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                # 壊れた状態ファイルで黙って落とさない=空から始めるが握り潰さず呼び元へ委ねる
                raise

    def latest_before(self, date: str) -> dict | None:
        earlier = sorted(d for d in self._data if d < date)
        return self._data[earlier[-1]] if earlier else None

    def record(self, summary: DailySummary) -> None:
        self._data[summary.date] = summary.to_dict()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def delta_against_previous(self, summary: DailySummary) -> Delta:
        prev = self.latest_before(summary.date)
        if not prev:
            return Delta(
                amount=summary.total_amount,
                count=summary.total_count,
                prev_date=None,
                amount_pct=None,
                count_pct=None,
            )
        return Delta(
            amount=summary.total_amount - prev["total_amount"],
            count=summary.total_count - prev["total_count"],
            prev_date=prev["date"],
            amount_pct=_pct(summary.total_amount, prev["total_amount"]),
            count_pct=_pct(summary.total_count, prev["total_count"]),
        )
