#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回送の申し送り(escalate note)の回帰テスト。

★何を守るテストか(2026-08-15 イージス研究室・実害から作った)
  Chamiが 10:46 に画像加工を人事部門へ投げ、**22秒後に「間違えてChatGPTに貼った。無視して」
  と取り消した**。人事部門がその取り消しを処理し終える前に回送が組まれ、イージス研究室には
  取り消しの存在が1文字も伝わらないまま上申された(受け手は無効な依頼に着手した)。
  真因は2つ:
    ① `_escalate_to_head` の note が定型1行で、**上げ元の判断も後続便も載っていなかった**
    ② `session_relay.build_envelope` が **note を1文字も描画していなかった**(積んでも届かない)

★外へ出る手だけ偽物にする= キュー(inbox.db)と LOCAL を一時ディレクトリへ差し替える。
  判定・分岐(msg_idの前後比較 / noteの組み立て / 封筒の描画)は**本物のまま**回す。

実行= python tests/test_escalate_note.py
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FAILED = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def main():
    tmp = tempfile.mkdtemp(prefix="esc_note_")
    try:
        os.makedirs(os.path.join(tmp, "queue"), exist_ok=True)
        # 部門長を引く先(実物と同じ形の名簿。Discordへは出ない)
        with open(os.path.join(tmp, "discord_channels.json"), "w", encoding="utf-8") as f:
            json.dump([{"name": "イージス研究室", "id": "1", "dept": "aegis-gl"},
                       {"name": "人事部門", "id": "2", "dept": "hr-room"}], f, ensure_ascii=False)

        import dept_daemon as D
        D.LOCAL = tmp                      # ★偽物にするのは「読み書きの先」だけ

        from leasequeue import LeaseQueue
        q = LeaseQueue(os.path.join(tmp, "queue", "inbox.db"))
        # 上げ元(hr-room)の箱: 依頼の便 → その後に取り消しの便
        ask = "1538000818685616159"        # 10:46 画像加工の依頼
        cancel = "1538000963774709812"     # 10:46:31 「間違えてChatGPTに貼った。無視して」
        old = "1537999687808720937"        # それより前の便(混ぜてはいけない)
        for m, txt in ((old, "十王星南の追加差分"),
                       (ask, "サイズ適正化&高画質化をよろしく。"),
                       (cancel, "間違えてChatGPTに貼るつもりがここに貼ってしまった。無視して")):
            q.enqueue(json.dumps({"msg_id": m, "content": txt, "channel": "人事部門"},
                                 ensure_ascii=False), msg_id=m, dept="hr-room")
        q.close()

        me = D.Daemon.__new__(D.Daemon)    # __init__ は常駐の配線を張るので通さない
        me.dept = "hr-room"
        me._head_cache = "aegis-gl"        # 部門長の解決はDiscord API=ここでは固定

        rec = {"msg_id": ask, "content": "サイズ適正化&高画質化をよろしく。", "channel": "人事部門",
               "author": "chami_fusoh"}

        # ① 後続便の検出: 後の便だけを拾い、前の便は拾わない
        after = D.Daemon._pending_after(me, rec)
        check("後続便を拾う", cancel in after, after)
        check("後続便に『無視して』の本文が載る", "無視して" in after, after)
        check("前の便は混ぜない", old not in after, after)

        # ② 実際に上申して、キューへ入った body の note を見る
        ok = D.Daemon._escalate_to_head(me, rec, raw_line="{}",
                                        reply="これはhrの持ち場を外れる。画像を生成する道具が無い。")
        check("上申できた", ok is True)
        q = LeaseQueue(os.path.join(tmp, "queue", "inbox.db"))
        rows = [r for r in q.peek_ready(dept="aegis-gl", limit=10)]
        q.close()
        check("部門長の箱へ1件入った", len(rows) == 1, str(len(rows)))
        note = (rows[0]["body"].get("note") if rows else "") or ""
        check("noteに上げ元の返信が載る", "道具が無い" in note, note[:200])
        check("noteに後続便の警告が載る", "後に届いた未処理の便" in note, note[:200])
        check("noteに取り消しの本文が載る", "無視して" in note, note[:300])

        # ③ 封筒が note を描画する(積んでも描かなければ届かない=真因②)
        import session_relay as R
        env = R.build_envelope(dict(rows[0]["body"]), is_work=True, dept="aegis-gl")
        check("封筒に申し送り枠が出る", "--- 申し送り(" in env)
        check("封筒に取り消しの本文が出る", "無視して" in env)
        check("申し送りは本文より前に出る",
              env.index("--- 申し送り(") < env.index("--- 本文ここから ---"))
        # noteが無い便では1文字も足さない(封筒を毎便太らせない)
        env2 = R.build_envelope({"msg_id": "9", "content": "ふつうの便", "channel": "イージス研究室"},
                                is_work=False, dept="aegis-gl")
        check("noteが無ければ枠を出さない", "--- 申し送り(" not in env2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILED:
        print(f"★FAIL {len(FAILED)}件: " + " / ".join(FAILED))
        sys.exit(1)
    print("全PASS")


if __name__ == "__main__":
    main()
