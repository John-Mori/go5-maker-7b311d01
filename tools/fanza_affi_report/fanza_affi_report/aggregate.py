"""明細行 → 日次サマリ。

見るべき数字の土台は分析部門(shorts-analyst)の SA-H008:
  総成約率 = 報酬件数 / クリック数。★クリックはこの報酬CSVに無い列なので、
  別ソース(アクセスレポート)が渡された時だけ算出する。無ければ N/A。
中身の定義は分析部門と擦り合わせる前提(GL指示)。ここは構造だけ固定する。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .parser import RewardRow

# 実物で確認済みの報酬体系。これ以外が来たら unknown_types に載せて気づく。
KNOWN_REWARD_TYPES = ("ダイレクト", "カテゴリ", "サービス新規")


@dataclass
class Bucket:
    count: int = 0
    amount: int = 0

    def add(self, count: int, amount: int) -> None:
        self.count += count
        self.amount += amount

    def to_dict(self) -> dict:
        return {"count": self.count, "amount": self.amount}


@dataclass
class DailySummary:
    date: str
    n_rows: int = 0
    total_count: int = 0
    total_amount: int = 0
    by_type: dict[str, Bucket] = field(default_factory=dict)
    by_service: dict[str, Bucket] = field(default_factory=dict)
    top_products: list[dict] = field(default_factory=list)
    unknown_types: list[str] = field(default_factory=list)
    clicks: int | None = None  # 別ソースがあれば注入

    @property
    def conversion_rate(self) -> float | None:
        if not self.clicks:
            return None
        return self.total_count / self.clicks

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "n_rows": self.n_rows,
            "total_count": self.total_count,
            "total_amount": self.total_amount,
            "by_type": {k: v.to_dict() for k, v in self.by_type.items()},
            "by_service": {k: v.to_dict() for k, v in self.by_service.items()},
            "top_products": self.top_products,
            "unknown_types": self.unknown_types,
            "clicks": self.clicks,
            "conversion_rate": self.conversion_rate,
        }


def _normalize_service(name: str) -> str:
    """"同人 同人" のように重複表記されるので1語へ畳む。"""
    parts = name.split()
    if len(parts) == 2 and parts[0] == parts[1]:
        return parts[0]
    return name.strip()


def summarize(
    rows: list[RewardRow], date: str, top_n: int = 10, clicks: int | None = None
) -> DailySummary:
    s = DailySummary(date=date, clicks=clicks)
    by_type: dict[str, Bucket] = defaultdict(Bucket)
    by_service: dict[str, Bucket] = defaultdict(Bucket)
    unknown: set[str] = set()

    for r in rows:
        s.n_rows += 1
        s.total_count += r.reward_count
        s.total_amount += r.reward_amount
        by_type[r.reward_type].add(r.reward_count, r.reward_amount)
        by_service[_normalize_service(r.service)].add(r.reward_count, r.reward_amount)
        if r.reward_type and r.reward_type not in KNOWN_REWARD_TYPES:
            unknown.add(r.reward_type)

    s.by_type = dict(by_type)
    s.by_service = dict(by_service)
    s.unknown_types = sorted(unknown)

    # 上位作品(報酬額の大きい順)。同一品番は合算。
    per_product: dict[str, dict] = {}
    for r in rows:
        key = r.product_code or r.title
        p = per_product.setdefault(
            key,
            {"product_code": r.product_code, "title": r.title, "count": 0, "amount": 0},
        )
        p["count"] += r.reward_count
        p["amount"] += r.reward_amount
    s.top_products = sorted(
        per_product.values(), key=lambda p: p["amount"], reverse=True
    )[:top_n]
    return s
