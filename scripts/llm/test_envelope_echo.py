#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""strip_envelope_echo の検査(2026-09-03 / 研究室HQ・止血)。

検体= local/_work/envelope_echo_specimens.json(軍議 2026-09-03 01:55 の実物2通をAPIで取得)。
陽性2件・陰性(誤爆してはいけない)5件。must-fail= 実装を外した時に陽性が落ちること。

  python scripts/llm/test_envelope_echo.py
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import meta_strip                                # noqa: E402

SPEC = os.path.join(ROOT, "local", "_work", "envelope_echo_specimens.json")

# --- 陰性(切ってはいけない) -------------------------------------------------
NEG = [
    ("普通の返信",
     "うん、届いてるとこは既読・着手も付いてる。\n\nどうする:\n1. このままでいい\n2. 全部屋へ流す"),
    ("事故を論じる便(引用符つき)",
     "アロンソ、封筒の「=== この部屋のセッション状態 ===」がそのまま出てた。\n"
     "受信時刻: 2026-09-03T01:55:03 の便だ。原因を追う。"),
    ("コードブロックで貼った再現手順",
     "再現はこれ。\n\n```\n=== この部屋のセッション状態 ===\n世代: 第8世代\n投稿者: chami_fusoh\n```\n\n以上だ。"),
    ("引用ブロック(>)で写した封筒",
     "> === この部屋のセッション状態 ===\n> 世代: 第8世代\n\nこれが出てた。俺の見立てはこうだ。"),
    ("主マーカー1本だけ(裏づけ無し)",
     "封筒の ■規律: 前便から変更なし の行が気になる。それだけ言っておく。"),
]


def main():
    ok, ng = 0, 0

    def check(label, got, want):
        nonlocal ok, ng
        if got == want:
            ok += 1
            print(f"  OK   {label}")
        else:
            ng += 1
            print(f"  NG   {label}: got={got} want={want}")

    print("[陽性] 実物の検体")
    if not os.path.exists(SPEC):
        print(f"  検体が無い: {SPEC}")
        return 2
    for rec in json.load(io.open(SPEC, encoding="utf-8")):
        body, hits = meta_strip.strip_envelope_echo(rec["content"])
        cut = len(rec["content"]) - len(body)
        print(f"  msg={rec['msg_id']} 元{len(rec['content'])}字 → 残{len(body)}字 "
              f"(落とした{cut}字) 署名={[h['marker'] for h in hits]}")
        check(f"msg={rec['msg_id']} 切れている", bool(hits), True)
        check(f"msg={rec['msg_id']} 封筒が残っていない",
              ("この部屋のセッション状態" in body or "■この部門の目的とKPI" in body
               or "total_tokens" in body), False)
    # ①は正常な返信が頭に在る= 空にしてはいけない / ②は全文が封筒= 空でよい
    recs = json.load(io.open(SPEC, encoding="utf-8"))
    b1, _ = meta_strip.strip_envelope_echo(recs[0]["content"])
    check("① 正常部分は残る(先頭が人格の台詞)", b1.startswith("ははっ"), True)
    b2, _ = meta_strip.strip_envelope_echo(recs[1]["content"])
    check("② 全文が封筒→空になる", b2.strip() == "", True)

    print("[陰性] 切ってはいけない本文")
    for label, text in NEG:
        body, hits = meta_strip.strip_envelope_echo(text)
        check(label, (body == text and not hits), True)

    # ------------------------------------------------------------------
    # [配線] 2026-09-03 イージス研究室(研究室HQからE-2の所有権を引き継いだ時に足した)
    #   HQの止血は経路①(常駐)と経路②(ミラー)へ入った。だが呼び出し元を数え直すと
    #   経路②は**非テストの呼び元が1つも無い**(mirror_to_discord は 2026-08-15 退役)。
    #   生きていて穴だったのは**経路③ 投函(dispatch → apply_naming_gate_only)**の方だ。
    #   ここでは「経路③で鳴る・ただし切らない」を実物の検体で固定する。
    #   ★本番の監査は汚さない(C-054)= GO5_LOCAL_DIR を temp に振ってから import する。
    print("[配線] 経路ごとにE-2が在るか")
    here = os.path.dirname(os.path.abspath(__file__))
    src_d = io.open(os.path.join(here, "dept_daemon.py"), encoding="utf-8").read()
    check("経路① 常駐 dept_daemon にE-2が在る(切る側)",
          "strip_envelope_echo" in src_d, True)

    import tempfile
    import importlib
    tmp = tempfile.mkdtemp(prefix="env_echo_")
    os.environ["GO5_LOCAL_DIR"] = tmp
    sys.path.insert(0, here)
    import output_gates
    importlib.reload(output_gates)               # LOCAL/META_AUDIT を tmp で解決させる
    envelope = recs[1]["content"]                # ②= 全文が封筒の実物
    out, summ = output_gates.apply_naming_gate_only(
        "gunji", "三笘薫", envelope, source="dispatch", msg_id="TEST-E2-DISPATCH")
    check("経路③ 投函で封筒エコーを検知する", summ.get("envelope_echo_warn", 0) >= 1, True)
    check("経路③ では**切らない**(便は書式そのものが情報。まず1回鳴らす)", out == envelope, True)
    audit = os.path.join(tmp, "llm", "meta_strip_audit.jsonl")
    rows = []
    if os.path.exists(audit):
        rows = [json.loads(x) for x in io.open(audit, encoding="utf-8") if x.strip()]
    warn = [r for r in rows if r.get("event") == "envelope_echo_warn"]
    check("経路③ の記録が1行残る", len(warn) == 1, True)
    check("経路③ の記録は source=dispatch で見分けられる",
          bool(warn) and warn[0].get("source") == "dispatch", True)
    check("経路③ の記録に『切っていない』が明記される",
          bool(warn) and warn[0].get("cut") is False, True)
    check("経路③ の記録に『切るなら何字か』が残る(切りへ上げる時の材料)",
          bool(warn) and warn[0].get("would_cut_chars", 0) > 0, True)
    check("正常な便では鳴らない(誤爆0)",
          output_gates.apply_naming_gate_only(
              "gunji", "三笘薫", "了解した。方針は2次元へ寄せる。",
              source="dispatch")[1].get("envelope_echo_warn", 0), 0)
    os.environ.pop("GO5_LOCAL_DIR", None)

    print(f"\n合計: OK={ok} NG={ng}")
    return 0 if ng == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
