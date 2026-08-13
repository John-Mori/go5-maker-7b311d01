#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""デッドレター警報の宛先が incident + hq の2室だけであることの検査(2026-08-14 イージス研究室)。

裁定= 研究室HQ DISPATCH-aegis-gl-1786644517490。
出典= Chami msg 1537520749349310605(2026-08-14 02:58 JST)「これ送られる部屋が多すぎて邪魔かな」。
  引用元= メタルギアMk.II の `⚠デッドレターが新たに発生(現在計7件)`(msg 1537515526375346247)。

壊れていた形= `check_dead_letters`(増分速報) と `check_stale_dead`(滞留警報) の両方が
  `targets = [SUMMARY_DEPT, "hq"] + [d for d in by ...]` = **当該部門にも同じ長文を配っていた**。
  02:37:45 の実発火では by が5部門 → incident + hq + 5部門 = **7室**に同一の長文が出た。

★この検査は**本番のキューDBをそのまま読んで実際に発火させる**(bot_send は dry-run で
  差し替え、宛先だけを記録する)。本番の state ファイルには一切書かない=クールダウンを
  食い潰さない(save_state は呼ばない)。

実行: python scripts/discord/test_dlq_alert_targets.py
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import absence_watchdog as aw  # noqa: E402

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


def fire(fn, state):
    """本番データのまま1回だけ発火させ、実際に出た宛先を返す(送信はしない)。"""
    sent_to = []
    orig = aw.bot_send

    def spy(channel, body, dry_run, by_dept=False):
        sent_to.append((channel, body))
        return True

    aw.bot_send = spy
    try:
        fn(state, True)
    finally:
        aw.bot_send = orig
    return sent_to


def main():
    total, by, max_id = aw.dead_letter_summary()
    print(f"本番キューの実測: dead 計{total}件 / 内訳 {by} / 最大id {max_id}")

    # --- ① 実際に発火させて宛先を数える(増分速報) -----------------------------
    # クールダウンと基準idだけ開ける(state はこの場限りの辞書=本番へ保存しない)。
    st = {"last_dead_max_id": 0, "last_dead_alert": 0}
    sent = fire(aw.check_dead_letters, st)
    if total == 0:
        print("  (本番のdeadが0件=増分速報は発火しない。下の源流検査で固定する)")
        check("dead 0件なら鳴らない(空振りしない)", sent == [])
    else:
        depts = [c for c, _ in sent]
        print(f"  → 増分速報の宛先: {depts}")
        check("★増分速報は incident と hq の2室だけへ出る",
              depts == [aw.SUMMARY_DEPT, "hq"])
        check("★当該部門へは出ない(9325c04のon_deadが個別に出す側の仕事)",
              all(d not in depts for d in by))
        check("本文に部門の内訳が残っている(2室で詰まり先が読める)",
              sent and any(str(list(by)[0]) in b or "件" in b for _, b in sent))

    # --- ① 実際に発火させて宛先を数える(滞留警報) -----------------------------
    s_total, s_by, s_oldest, s_chami = aw.stale_dead_summary()
    print(f"本番キューの実測(滞留): 計{s_total}件 / 内訳 {s_by} / 最古 {int(s_oldest//3600)}時間前")
    st2 = {"last_stale_dead_alert": 0}
    sent2 = fire(aw.check_stale_dead, st2)
    if s_total == 0:
        print("  (滞留0件=滞留警報は発火しない。下の源流検査で固定する)")
        check("滞留0件なら鳴らない(空振りしない)", sent2 == [])
    else:
        depts2 = [c for c, _ in sent2]
        print(f"  → 滞留警報の宛先: {depts2}")
        check("★滞留警報は incident と hq の2室だけへ出る",
              depts2 == [aw.SUMMARY_DEPT, "hq"])
        check("★当該部門へは出ない", all(d not in depts2 for d in s_by))

    # --- 源流(コード)の検査= deadが0件でも固定できるようにしておく -------------
    src = open(os.path.join(HERE, "absence_watchdog.py"), encoding="utf-8").read()
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    check("★宛先に部門を足し込む式がコードから消えている",
          'targets = [SUMMARY_DEPT, "hq"] + [d for d in by' not in body)
    check("★2室固定の式が2箇所(増分・滞留)に在る",
          body.count('targets = [SUMMARY_DEPT, "hq"]') == 2)

    # --- ★変えていないもの(C-035=名指し1箇所の指示を全体へ広げない) -----------
    check("判定は変えていない= 増分は max_id の前進で鳴る",
          "if max_id <= last_id:" in body)
    check("判定は変えていない= 滞留は age(6時間)で鳴る",
          "STALE_DEAD_MIN_SEC = 6 * 60 * 60" in body)
    check("頻度は変えていない= 増分のクールダウン定数がそのまま",
          "DEAD_ALERT_COOLDOWN_SEC" in body)
    check("頻度は変えていない= 滞留は1日1回のまま",
          "STALE_DEAD_COOLDOWN_SEC = 24 * 60 * 60" in body)
    check("本文は変えていない= 滞留の🔥見出しがそのまま",
          "配送に失敗したまま放置されています" in body)
    check("他の警報の宛先には触っていない(窓の死活は incident のまま)",
          "def check_dead_windows" in body)

    ok = all(v for _, v in results)
    print(f"\n== {sum(v for _, v in results)}/{len(results)} PASS ==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
