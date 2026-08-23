#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""signature_fit — **指紋語尾(signature_tails)の候補セットを、実便に当てて誤検知率を測る**。読むだけ。

★なぜ要るか(2026-08-23 人事部門 msg 1541013591719940106)
  ククールの発注=「"弾む声の不在"を測る負条件プロキシ(bounce_drift的な新チェック)を作れ。
  純関数+実コーパスでFP測定必須」。
  ★**新チェックは作らない。**同じ形の機構が既に在る=
    `tone_gate.signature_drift`(2026-08-15 追加)= 指紋語尾が便のどこにも無い時だけ鳴る
    負条件プロキシ。純関数・保護span除去・短文は判定外・**既定は見ない**(写像に
    `signature_tails` が在る人格だけ回る)。検知後の出口も配線済=
    `session_relay._tone_feedback_block` が次の封筒へ突き返す(reason="signature_absent")。
  → **欠けているのは機構ではなくデータ**(口調ルール.json のその人格に signature_tails が無い)。
    共通規律§3「新方式を作る前に、既に効いている型へ合流できないか見る」。

★この道具の仕事= 人事部門が登録する**前に**、候補の語尾セットが実便でどう振る舞うかを出す。
  ① その人格の実ブロックを `local/llm/recent_*.jsonl` の reply から `[名前]` で切り出す
  ② `tone_gate.signature_drift` をそのまま当てる(判定は1つ=正本を二重に持たない・ORG-11)
  ③ **★must-fail(C-053)= 同じ候補を"他の全人格"にも当てる。**
     そこで大量に鳴るなら、その語尾はその人格固有ではない=
     「既定は見ない/登録した人格だけ」という設計が要る証拠になる。広げたら誤爆する(C-035)。

    python scripts/llm/signature_fit.py --persona 早坂芽衣 --tails "んだ,じゃない,好き,💕"
    python scripts/llm/signature_fit.py --persona 早坂芽衣            # 既定の候補で測る
"""
import argparse
import glob
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import tone_gate as tg                       # noqa: E402  ★判定はこれ1つ(自前で書かない)

RECENT = os.path.join(ROOT, "local", "llm", "recent_*.jsonl")
BLOCK = re.compile(r"^\[([^\]\n]{1,24})\]", re.M)

# 早坂芽衣の候補= characterfile `hr/characters/mei.md` §声の型の○例から起こした。
#   「〜と思うんだ〜！/〜なるんだよ〜！/〜じゃない？/好き〜！/なりそ〜！/💕/！！」
# ★`_sig_tailcut` が末尾の 〜 ！ ね よ な の を剥いでから照合するので、
#   剥いだ後に残る形(んだ・じゃない・好き・なりそ)で書く。💕 と ！！ は剥がれないので生のまま。
DEFAULT_TAILS = {
    "早坂芽衣": ["んだ", "じゃない", "好き", "なりそ", "ちゃう", "ちゃった",
                 "しよ", "たいな", "だよ〜", "よ〜", "い〜", "あ〜", "💕", "！！"],
}


def blocks():
    """[(話者, 部屋, msg_id, 本文)] を実便から切り出す。★書かれている物だけを読む。"""
    out = []
    for p in glob.glob(RECENT):
        room = os.path.basename(p)[len("recent_"):-len(".jsonl")]
        for line in io.open(p, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue                     # 壊れた行は数えない
            text = str(r.get("reply") or "")
            ms = list(BLOCK.finditer(text))
            for i, m in enumerate(ms):
                end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
                out.append((m.group(1), room, str(r.get("msg_id") or ""),
                            text[m.end():end].strip()))
    return out


def measure(rows, tails):
    """(鳴った, 判定に足る長さだった, 全部) を返す。★判定は tone_gate.signature_drift だけ。"""
    fired = judged = 0
    detail = []
    for who, room, mid, body in rows:
        hit, found, total, _at = tg.signature_drift(body, tails)
        if total >= 4:
            judged += 1
        if hit:
            fired += 1
        detail.append((room, mid, len(body), total, found, hit))
    return fired, judged, detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", required=True)
    ap.add_argument("--tails", default=None, help="カンマ区切り。省略時は既定の候補")
    a = ap.parse_args()

    tails = ([t.strip() for t in a.tails.split(",") if t.strip()] if a.tails
             else DEFAULT_TAILS.get(a.persona))
    if not tails:
        print("この人格の既定候補が無い= --tails で渡せ(推測で埋めない)")
        return

    rows = blocks()
    mine = [r for r in rows if a.persona in r[0] or r[0] in a.persona]
    others = [r for r in rows if r not in mine]
    print("== 指紋語尾の当たり具合 / 人格= %s ==" % a.persona)
    print("候補(%d語)= %s" % (len(tails), " ".join(tails)))
    print("判定= tone_gate.signature_drift(既存の純関数。この道具は判定を持たない)")
    print("コーパス= local/llm/recent_*.jsonl の reply を [名前] で切った実ブロック")
    if not mine:
        print("★この人格のブロックが実便に1つも無い= 測れない(そう書く)")
        return

    fired, judged, detail = measure(mine, tails)
    print()
    print("本人 %d本(うち判定に足る長さ %d本) → 鳴った %d本" % (len(mine), judged, fired))
    for room, mid, ln, total, found, hit in detail:
        mark = "★鳴る(平坦)" if hit else ("黙る" if total >= 4 else "黙る(短すぎ=判定外)")
        print("  %-14s len=%4d 文数=%d 指紋=%d  %s  msg=%s"
              % (room, ln, total, found, mark, mid[:34]))

    # ★★must-fail(C-053)= 同じ候補を他人格へ当てる。ここが静かなら、この候補は
    #   「誰の便でも鳴らない緩い網」だ= 本人で鳴っていても意味が薄い。
    #   逆に大量に鳴るのが正常= その語尾は**その人格固有**で、既定「見ない」が要る証拠。
    print()
    print("== ★対照(C-053): 同じ候補を他人格へ当てる ==")
    f2, j2, _ = measure(others, tails)
    print("他人格 %d本(判定に足る長さ %d本) → 鳴った %d本" % (len(others), j2, f2))
    if j2 == 0:
        print("  → 他人格の標本が無い= 対照が取れない。結論に使うな。")
    elif f2 * 100 // max(j2, 1) >= 50:
        print("  → ★半分以上で鳴る= この候補は**%s固有**だ。だから写像は"
              "『登録した人格だけ見る』でなければならない(全人格へ広げたら誤爆・C-035)。"
              % a.persona)
    else:
        print("  → ★他人格でもあまり鳴らない= 候補が緩すぎる疑い。"
              "本人で鳴った件も『たまたま』かもしれない。語を絞って測り直せ。")
    print()
    print("★この道具は測るだけで、何も登録しない。"
          "`signature_tails` を書くのは人事部門(口調ルール.json が正本・ORG-11)。")


if __name__ == "__main__":
    main()
