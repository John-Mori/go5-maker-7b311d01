"""日次サマリ+前日比 → 送信本文(プレーンテキスト)。

★本文は FANZA売上=ローカル/手渡し限定の性質。ネット公開経路に置かない。
  (どこへ出すかは senders 側の設定で決まる。ここは文面だけ作る。)
"""
from __future__ import annotations

from .aggregate import DailySummary
from .state import Delta


def _yen(n: int) -> str:
    return f"{n:,}円"


def _sign(n: int) -> str:
    return f"+{n:,}" if n >= 0 else f"{n:,}"


def _pct_str(p: float | None) -> str:
    if p is None:
        return "(前日データ無し)"
    return f"({'+' if p >= 0 else ''}{p:.1f}%)"


def format_report(summary: DailySummary, delta: Delta, title: str = "FANZAアフィ売上レポート") -> str:
    lines: list[str] = []
    lines.append(f"■ {title}  {summary.date}")
    lines.append(
        f"報酬合計: {_yen(summary.total_amount)} / {summary.total_count}件  "
        f"(明細{summary.n_rows}行)"
    )
    if delta.prev_date:
        lines.append(
            f"前日比({delta.prev_date}比): "
            f"{_sign(delta.amount)}円 {_pct_str(delta.amount_pct)} / "
            f"{_sign(delta.count)}件 {_pct_str(delta.count_pct)}"
        )
    else:
        lines.append("前日比: 前回データが無いため今回が基準です")

    if summary.conversion_rate is not None:
        lines.append(
            f"総成約率: {summary.conversion_rate * 100:.2f}%  "
            f"(クリック{summary.clicks:,})"
        )

    lines.append("")
    lines.append("― 報酬体系別 ―")
    for t, b in sorted(summary.by_type.items(), key=lambda kv: kv[1].amount, reverse=True):
        lines.append(f"  {t}: {_yen(b.amount)} / {b.count}件")

    lines.append("")
    lines.append("― サービス別 ―")
    for name, b in sorted(
        summary.by_service.items(), key=lambda kv: kv[1].amount, reverse=True
    ):
        lines.append(f"  {name}: {_yen(b.amount)} / {b.count}件")

    lines.append("")
    lines.append("― 上位作品(報酬額) ―")
    for i, p in enumerate(summary.top_products, start=1):
        title_short = p["title"][:24] + ("…" if len(p["title"]) > 24 else "")
        lines.append(
            f"  {i}. {_yen(p['amount'])} / {p['count']}件  "
            f"[{p['product_code']}] {title_short}"
        )

    if summary.unknown_types:
        lines.append("")
        lines.append(
            "【注意】未知の報酬体系を検出(DMM側で列/値が変わった可能性): "
            + ", ".join(summary.unknown_types)
        )
    return "\n".join(lines)
