# -*- coding: utf-8 -*-
"""台帳(open_defects.jsonl)の1件を閉じる**唯一の口**。生JSONを手打ちさせないための薄いCLI。

なぜ在るか(2026-08-12・イージス研究室 / 発注= 研究室HQ DISPATCH-aegis-gl-1786467265180):
  confirm を人/セッションが手で1行書く運用だったため、Windowsパスの `\\` を素で書いた行が
  2行できた(REQ-future-room-0a19d32276 / REQ-future-room-4bedba52c7)。
  読み取り側は壊れた行を**黙って飛ばす**ので、**終わった依頼が永久に未完了として
  全部屋の起動文に出続けた**。器を直す前に、まず**手打ちをやめさせる**のがこれだ。

使い方:
  python scripts/llm/close_item.py --id DEF-xxx-yyy --dept aegis-gl \
      --fixed "<直った実物の在りか>" --scene "<どの場面で見たか>" --by "ケヴィン・デ・ブライネ"

  一覧を見る:   python scripts/llm/close_item.py --list --dept aegis-gl
  台帳の点検:   python scripts/llm/close_item.py --health

掟(session_relay.confirm_defect と同じ。ここで緩めない):
  * `--fixed` は**機械が解決できる在りか**だけ= Discordのmsg_id/リンク・実在するパス・URL。
    **commitのhashは受理されない**(台帳であって、Chamiの画面で終わっている実物ではない)。
  * `--scene`(どの場面で確かめたか)は必須。
  * 追記のみ。既存行は絶対に書き換えない。受理されなかった行も**残す**(何が足りなかったかを読めるように)。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import session_relay as SR                                       # noqa: E402


def _list(dept):
    items = SR.fold_defects(dept or None)
    open_items = [d for d in items if d["status"] == SR.DEFECT_OPEN]
    if not open_items:
        print("未確認は0件です(dept=%s)。" % (dept or "全部門"))
        return 0
    print("未確認 %d件(dept=%s):" % (len(open_items), dept or "全部門"))
    for d in open_items:
        kind = "依頼" if d.get("kind") == SR.DEFECT_KIND_REQUEST else "不具合"
        sym = " ".join(d["symptom"].split())[:70]
        print("  [%s] (%s/%s) %s" % (d["id"], d["dept"], kind, sym))
        if d["rejected"]:
            print("      ★閉じようとして弾かれた記録 %d件: %s"
                  % (len(d["rejected"]), d["rejected"][-1]))
    return 0


def _health():
    bad = SR.defect_ledger_bad_lines()
    rows = SR._defect_read_rows()
    print("台帳: %s" % SR.DEFECTS_FILE)
    print("読めた行: %d / 読めなかった行: %d" % (len(rows), len(bad)))
    for n, why, head in bad:
        print("  - %d行目: %s | %s" % (n, why, head))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description="台帳の1件を閉じる(confirmを機械に書かせる)")
    ap.add_argument("--id", help="閉じる項目のID(DEF-… / REQ-…)")
    ap.add_argument("--dept", default="", help="部門ID(例 aegis-gl)")
    ap.add_argument("--fixed", default="", help="終わった実物の在りか(msg_id/リンク/パス/URL)")
    ap.add_argument("--scene", default="", help="どの場面で確かめたか")
    ap.add_argument("--by", default="", help="誰が確かめたか(人格名でよい)")
    ap.add_argument("--list", action="store_true", help="未確認の一覧を出す")
    ap.add_argument("--health", action="store_true", help="台帳に読めない行が無いか点検する")
    a = ap.parse_args()

    if a.health:
        return _health()
    if a.list:
        return _list(a.dept)
    if not a.id or not a.dept:
        ap.error("--id と --dept は必須です(一覧は --list、点検は --health)")

    # ★閉じる前に「その項目が本当に開いているか」を測る。
    #   存在しないIDへ confirm を積んでも fold_defects が (a) で落とすだけ= 黙って効かない。
    items = {d["id"]: d for d in SR.fold_defects(None)}
    d = items.get(a.id)
    if d is None:
        print("NG: そのIDは台帳に**開いていません**: %s" % a.id)
        print("    (--list で今の未確認を見てください。IDの写し間違いが多い)")
        return 2
    if d["status"] == SR.DEFECT_CONFIRMED:
        print("すでに確認済です: %s (fixed=%s)" % (a.id, d["fixed"][:80]))
        return 0
    if d["dept"] and a.dept and d["dept"] != a.dept:
        print("NG: 部門が違います。台帳の dept=%s / 渡された dept=%s" % (d["dept"], a.dept))
        return 2

    ok, why = SR.confirm_defect(dept=a.dept, did=a.id, fixed=a.fixed,
                                scene=a.scene, by=a.by)
    # ★confirm_defect は**弾いた時も行を残す**(何が足りなかったかを後から読めるように)。
    if not ok:
        print("受理されませんでした(行は台帳に残っています): %s" % why)
        return 3
    # 実際に畳んだ結果で確認する(=自己申告ではなく実測で閉じたと言う)。
    after = {x["id"]: x for x in SR.fold_defects(None)}.get(a.id)
    if after and after["status"] == SR.DEFECT_CONFIRMED:
        print("確認済にしました: %s" % a.id)
        print("  fixed= %s" % a.fixed)
        print("  scene= %s" % a.scene)
        return 0
    print("追記はしましたが、畳んだ結果はまだ**未確認**です(scene が短い等)。--list で確認を。")
    return 3


if __name__ == "__main__":
    sys.exit(main())
