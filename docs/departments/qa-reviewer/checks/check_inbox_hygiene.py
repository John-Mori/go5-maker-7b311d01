#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""local/inbox/ の衛生チェック (QA回帰・A-7)。
不変条件: inbox直下の.jsonlは台帳のdept名のみ (台帳外の名前=INC-86の罠の再来。
sweepガードで食われはしないが、置いた本人は配達も回収もされない箱を見張ることになる)。

★2026-09-16 イージス研究室が自分の取り残しを畳んだ= 箱の名前は**2種類ある**。
    `<dept>.jsonl`          デーモン宛ての便
    `<dept>.session.jsonl`  セッション宛ての写し(2026-09-10 に分離・発注=研究室HQ)
  後者を足したのはイージス研究室(change_log 2026-09-10T06:40:48・dept=aegis-gl)で、
  その手番でこの検査を直さなかった。結果、**生きている箱4つを「台帳外だから
  local/_work/ へ退避しろ」と言い続ける赤**になっていた(実測= aegis-gl / hq /
  keiei-kikaku / research-room。うち hq.session.jsonl は当日16:01に書かれている現役)。
  言うとおりに退避すればセッションへの配達が止まる= **誤発火する安全網**だった。
  ★直したのは「読み方」だけだ= 台帳に無い名前は今までどおり赤にする(下の変異で実証)。
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))


def main():
    reg = os.path.join(ROOT, "local", "discord_channels.json")
    inbox = os.path.join(ROOT, "local", "inbox")
    depts = {str(c.get("dept", "")) for c in json.load(open(reg, encoding="utf-8"))}
    errs, seen = [], 0
    if os.path.isdir(inbox):
        for fn in sorted(os.listdir(inbox)):
            if not fn.endswith(".jsonl"):
                continue
            seen += 1
            dept = fn[: -len(".jsonl")]
            # ★`.session` は箱の種類であって名前の一部ではない。剥がしてから台帳と突き合わせる。
            #   剥がすのはこの1語だけ= 知らない接尾辞(`aegis-gl.tmp` 等)は今までどおり赤。
            if dept.endswith(".session"):
                dept = dept[: -len(".session")]
            if dept not in depts:
                errs.append(f"台帳外の箱: local/inbox/{fn} (INC-86の罠。退避は local/_work/ へ)")
    if errs:
        print(f"FAIL: check_inbox_hygiene ({len(errs)}件)")
        for e in errs:
            print("  -", e)
        return 1
    print(f"PASS: check_inbox_hygiene (箱{seen}個・全て台帳内のdept名)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
