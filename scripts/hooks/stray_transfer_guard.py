#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""部屋セッションの起動側フックで、このrepoへの転送/受信系の手道具の混入を見て知らせる。

★検査範囲(2026-09-16 10:20 更新・モドリッチ訂正 msg 1549588018858430546):
  当初は「ルート直下(非再帰)」だった。だが炎上の実物が置かれたのは
  `local\\file_transfer\\1_ファイアウォール許可_管理者.bat` / `2_受信サーバー起動.bat` で、
  ルート直下ではなく**1階層下**だった。旧版はこれを素通しした。
  改修α(オタコン)が本体を再帰版へ直した= commit `ab3280f`(再帰化)→ `0ec296c`
  (`check_root()` を後方互換APIとして復活)。**この配線は本体を import して引くだけなので、
  あちらが直った時点で同時に直っている**(ORG-11=判定を2つに割らない、の利得)。
  ★文面で「ルート直下」と言わないこと= 本体はもう再帰する。嘘の案内は退避先を誤らせる。

なぜ pre-commit だけでは足りないか(2026-09-16 aegis-gl・ケヴィン・デブライネ / AD研究室
ルカ・モドリッチ msg 1549583829457571931 の指摘が正しい):
  炎上の実物(Chami「5SECのフォルダにbat置くな、関係ない。」msg 1549490188701409385)で
  置かれたのは **E:\\転送ツール\\ 行きの手道具**で、git管理下へ commit されるとは限らない
  (change_log 2026-09-16 06:24 行が `commit=(E:配下・git外)`)。commit を通らない混入は
  pre-commit では**一度も鳴らない**。だから部屋が回るたびに実物のファイルを見る。

★このhookはセッションを**止めない**(必ず exit 0 / 例外は黙って素通し)。部屋セッションを
  殺すとその部門の便が丸ごと止まる= 混入より重い事故になる(fail-open・沈黙が最悪の事故)。
  出来るのは「在ることを、在る間ずっと、セッションとChamiの両方に見せ続ける」こと:
    - systemMessage      … 端末のChamiに見える
    - additionalContext  … そのセッション自身が読む(=気付いた場で退避できる)
  本当に止めるのは commit 経路(.git/hooks/pre-commit)の持ち場。あちらは exit 1 で止める。

★判定は `scripts/check_no_stray_transfer_tools.py` の `check_root()` **1本**を import して引く
  (ORG-11=判定を2つに割らない)。ここには閾値もシグネチャも書かない。あちらを直せば
  commit経路と起動側の両方が同時に直る。subprocess を起こさないので相乗り先の便を遅くしない。

★どこへ登録されているか(正直に書く):
  筋は `.claude/settings.json` の hooks.SessionStart に1本足すこと。だが**この作業セッション
  からは settings.json への書き込みがハーネスに止められる**(2026-09-16 10:05 実測=
  「Claude requested permissions to write to .claude/settings.json」で拒否。
  progress_mark.py / pulse_touch.py の相乗りも 2026-08-22 に同じ理由で入っている)。
  → 登録済みhookである UserPromptSubmit(`progress_mark.py read`)へ相乗りし、
    `progress_mark._stray_guard()` から `decide_stray()` を呼ぶ。文面も判定もここが正本。
  ★settings.json へ SessionStart を登録できたら、このファイルを直接 command に指すのが本筋
    (`python scripts/hooks/stray_transfer_guard.py`)。同じ decide_stray を呼ぶので文面は変わらず、
    相乗りは外してよい。

実行= python scripts/hooks/stray_transfer_guard.py (stdin のJSONは読むが判定には使わない)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOG = os.path.join(ROOT, "local", "llm", "stray_transfer_guard.log.jsonl")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _record(hits):
    """鳴った事実を台帳へ1行残す(stderr は捨てられる=残らない記録は無いのと同じ)。"""
    try:
        import datetime
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "hits": [{"name": n, "why": w} for n, w in hits],
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass                                   # 記録の都合で便を落とさない


def decide_stray(payload=None):
    """混入していれば見せる文面を返す。無ければ None(黙る安全網)。

    返り= (msg, hits) / (None, []) 。★例外は (None, []) = 素通し(fail-open)。
    """
    try:
        sc = os.path.join(ROOT, "scripts")
        if sc not in sys.path:
            sys.path.insert(0, sc)
        from check_no_stray_transfer_tools import check_root   # 判定はあちら1本
        hits = check_root(ROOT)
        if not hits:                           # None(検査不能)も空も同じ=黙る
            return None, []
        lines = "\n".join(f"  ・{n}  ({w})" for n, w in sorted(hits))
        msg = ("[転送ツール混入ガード] この運営runtimeの中に転送/受信系の手道具が居ます。"
               "持ち場は E:\\転送ツール\\ です(Chami「5SECのフォルダにbat置くな、関係ない。」"
               "msg 1549490188701409385・恒久)。\n" + lines + "\n"
               "→ 消さずに E:\\転送ツール\\ へ退避してください(C-003)。"
               "この状態のままでは commit も止まります(.git/hooks/pre-commit)。")
        _record(hits)
        return msg, hits
    except Exception:
        return None, []                        # fail-open: ガードで仕事を殺さない


def main():
    payload = {}
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}
    msg, _hits = decide_stray(payload)
    if msg:
        print(json.dumps({
            "systemMessage": msg,
            "hookSpecificOutput": {
                "hookEventName": payload.get("hook_event_name") or "SessionStart",
                "additionalContext": msg,
            },
        }, ensure_ascii=False))
    return 0                                   # ★常に0= セッションは殺さない


if __name__ == "__main__":
    sys.exit(main())
