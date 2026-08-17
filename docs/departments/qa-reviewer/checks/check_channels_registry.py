#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台帳 local/discord_channels.json の不変条件チェック (QA回帰・A-7)。
不変条件: 各行に name/id/dept が揃う・idは17-20桁数字・id重複なし・dept重複は**登録制**。

★2026-08-18 (イージス研究室): dept重複を「一律FAIL」から**登録制**へ変えた。
  旧仕様は「dept重複=受信箱共有=返信先の取り違え」として無条件にFAILしていた
  (初出= 学習ルーム1/2 の実害 2026-07-16)。だが実測で前提が2つ崩れている:
    ① learning-coach が2部屋を持つのは**設計**である。Chami指示 2026-08-12
       (msg ESC-hr-room-1536840263278788708)は 1525703027942494298 / 1526283504696950794 の
       両方を名指しで「どちらもこの部門」と扱っており、dept_daemon.py:1675 の注記もそれを写している。
    ② 返信先は dept からは引いていない。dept_daemon.handle() は便ごとの
       `rec["channel"]`(dept_daemon.py:4992)をそのまま persona_send へ渡す(同:5445)ので、
       同じdeptの2部屋でも**来た部屋へ返る**。取り違えの経路は現存しない。
       (辞書化で片方が消える罠は replied_recheck.py:104 に実物付きで残っている=あれは
        `{dept: id}` を作った側の穴で、台帳側の穴ではない)
  → **黙らせる**のではなく**登録する**。登録には「どの部屋idの組か」まで書かせるので、
    3部屋目が黙って増えたり、別の部屋が同じdeptを名乗ったりすれば従来どおりFAILする。
  ★未登録のdept重複は今までどおりFAIL(既定は「見ない」ではなく「疑う」側のまま)。
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
REG = os.path.join(ROOT, "local", "discord_channels.json")

# 複数の部屋を持ってよいdeptの登録簿。値= 許可する部屋idの**集合**(増減したらFAIL)。
# ★ここへ足すのは「1部門が複数の部屋を持つことをChamiが決めた」時だけ。
#   足す前に、その経路が dept から返信先を引いていないことを実物で確かめること。
MULTI_ROOM = {
    # 質問-chamiの学習と癒しのルーム1 / ルーム2(姉軍団)。Chami指示 2026-08-12。
    "learning-coach": {"1525703027942494298", "1526283504696950794"},
}


def main():
    errs = []
    try:
        chs = json.load(open(REG, encoding="utf-8"))
    except Exception as e:
        print(f"FAIL: 台帳が読めない: {e}")
        return 1
    if not isinstance(chs, list) or not chs:
        print("FAIL: 台帳が空か配列でない")
        return 1
    ids, depts = {}, {}
    for i, c in enumerate(chs):
        name, cid, dept = c.get("name"), str(c.get("id", "")), c.get("dept")
        if not name:
            errs.append(f"行{i}: nameが空")
        if not (cid.isdigit() and 17 <= len(cid) <= 20):
            errs.append(f"行{i} ({name}): id形式不正 [{cid}]")
        if not dept:
            errs.append(f"行{i} ({name}): deptが空")
        if cid in ids:
            errs.append(f"id重複: {cid} ({ids[cid]} / {name})")
        ids[cid] = name
        depts.setdefault(dept, []).append((cid, name))
    # dept重複= 登録簿に在るものだけ許す。許すのは「その部屋idの組」までで、
    # 部屋が増えても減っても差し替わってもFAILする(=黙らせていない)。
    multi = 0
    for dept, rows in sorted(depts.items()):
        if len(rows) <= 1:
            continue
        want = MULTI_ROOM.get(dept)
        got = {cid for cid, _ in rows}
        if want is None:
            errs.append(f"dept重複(未登録): {dept} ({' / '.join(n for _, n in rows)})"
                        " = 受信箱共有・返信先取り違えの穴。設計なら MULTI_ROOM へ部屋idごと登録する")
        elif got != want:
            errs.append(f"dept重複(登録と不一致): {dept} 実際={sorted(got)} 登録={sorted(want)}"
                        " = 部屋の増減が登録簿へ反映されていない")
        else:
            multi += 1
    # 登録したのに実際は1部屋以下= 登録簿の腐り(消し忘れ)。静かに通さない。
    for dept, want in sorted(MULTI_ROOM.items()):
        if len(depts.get(dept, [])) <= 1:
            errs.append(f"MULTI_ROOM の登録が実体と合わない: {dept} は今 "
                        f"{len(depts.get(dept, []))}部屋しか無い(登録={sorted(want)})")
    if errs:
        print(f"FAIL: check_channels_registry ({len(errs)}件)")
        for e in errs:
            print("  -", e)
        return 1
    print(f"PASS: check_channels_registry ({len(chs)}ch・id重複なし"
          f"・dept重複は登録済{multi}件のみ)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
