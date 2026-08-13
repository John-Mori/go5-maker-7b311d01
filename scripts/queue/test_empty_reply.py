#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rc=0 の空返答を「口座エラーと同じ箱」に入れないことの検査(2026-08-14 イージス研究室)。

発注= 研究室HQ DISPATCH-aegis-gl-1786644123784。HQの問い=
  「`rc=0` かつ `result` が空を、クレジット切れ(=口座の問題)と**同じ箱**で扱ってよいか」。
答え= **違う箱**。この検査がその答えを固定する。

壊れていた実物(local/llm/request_log.jsonl の実測)=
  2026-08-13 03:08:59 / 03:14:08 / 03:19:39 / 03:24:51 / 03:29:58 と
             15:26:22 / 15:27:58 / 15:33:06 / 15:38:14 / 15:39:44 の **llm-qa 10回**
  (+ 2026-07-30 03:09:57 の future-room 1回)。いずれも rc=0 / is_error:false /
  stop_reason:end_turn で**本文だけが無い**。10回の total_cost_usd 合計 **$9.19** を
  払って部屋には1文字も出ず、DISPATCH-llm-qa-1786558097396 と -1786602372875 の
  2便が deliveries=6 で dead になった。
  ★セッションの記録(c78fec20…)を見ると、その秒にセッションは
    「No response requested.」(出力7トークン)と答えている= **便を機械の通知だと読んで
    返事を省いていた**。口座は生きている(課金が通っている)。

受け入れ条件(HQ)=
  ① rc=0+空返答を**再現させた検査**が在ること。口座エラー側の挙動が変わっていないことも同時に固定する。
  ② その状態で便が6回で dead にならない(=交代して復帰する)か、dead になるなら通知が出る。

実行: python scripts/queue/test_empty_reply.py
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
import session_relay as sr  # noqa: E402

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


# --- 実測の形を写した応答(全文は request_log で500字に切られているので、観測できた
#     キーと値だけを写している。判定に効くのは rc / is_error / result の3つだけだ) ---
EMPTY = {"is_error": False, "duration_api_ms": 2734, "num_turns": 1,
         "stop_reason": "end_turn", "session_id": "c78fec20-faa1-4df8-86ba-439ca8189ad6",
         "total_cost_usd": 1.4581030000000001,
         "usage": {"input_tokens": 1, "cache_creation_input_tokens": 144746,
                   "cache_read_input_tokens": 20926, "output_tokens": 7}}
EMPTY_OUT = json.dumps(EMPTY, ensure_ascii=False)

LIMIT = {"type": "result", "subtype": "success", "is_error": True,
         "api_error_status": 429, "num_turns": 1,
         "result": "You've hit your session limit · resets 2:40am (Etc/GMT-9)",
         "session_id": "a14edd36-72f7-4bb4-86ec-a4e559176e8c"}
CREDIT = {"type": "result", "subtype": "success", "is_error": True,
          "api_error_status": 400, "num_turns": 1,
          "result": "Credit balance is too low",
          "session_id": "a14edd36-72f7-4bb4-86ec-a4e559176e8c"}
OK = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 1,
      "result": "こっちで測って直しておいたよ。", "session_id": "x"}
OK2 = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 1,
       "result": "作り直した方から返す。", "session_id": "S2-new"}


def drive(seq, entry=None, dept="qa-empty-test"):
    """relay() を**本物のまま**1便回し、外へ出る手だけ偽物に差し替える(2026-08-14)。

    差し替えるのは ①claudeの起動(`_run_claude`) ②ファイル/スレッドを触る周辺だけ。
    ★判定側(`looks_like_empty_reply` / `_looks_like_session_missing` / `_reply_of`)と
      催促・交代の枝は**一切差し替えない**= ここが検査したい本体だからだ。
    seq= `_run_claude` が順に返す (data, rc, out)。戻り値 (reply, ok, 呼び出しの記録, 保存された entry)。
    """
    calls = []
    saved = {}

    def fake_run(prompt, token, session_id=None, model=None, timeout=None,
                 hard_timeout=None, on_soft=None):
        calls.append({"prompt": prompt, "sid": session_id})
        d, rc, out = seq[len(calls) - 1]
        return d, rc, out, 1.0

    ent = {"active_session_id": "S1", "generation": 3, "char_fp": "cf",
           "status": "ready", "context_tokens": 1000}
    if entry:
        ent.update(entry)
    table = {dept: ent}
    patches = {
        "_run_claude": fake_run,
        "load_sessions": lambda: table,
        "save_sessions": lambda t: None,
        "save_room": lambda d, e: saved.update({"entry": dict(e)}),
        "_record": lambda *a, **k: None,
        "_log": lambda *a, **k: None,
        "_boot_prompt": lambda *a, **k: "BOOT",
        "build_envelope": lambda *a, **k: "ENV",
        "discipline_fingerprint": lambda: "fp",
        "_char_fingerprint": lambda conf: "cf",
        "_char_parts": lambda conf: {},
        "_ledger_lines": lambda d: [],
        "_join_maintenance": lambda d, timeout=None: 0,
        "_schedule_maintenance": lambda *a, **k: None,
        "_work_snapshot": lambda: None,
        "_work_audit": lambda *a, **k: None,
        "_write_handoff": lambda *a, **k: (None, ""),
        "_self_check": lambda *a, **k: "",
        "run_compact": lambda *a, **k: (True, ""),
        "_measure_context_now": lambda sid: (0, False),
        "_note_usage": lambda *a, **k: 0,
        "_recent_append": lambda *a, **k: None,
        "_should_rotate": lambda e: (False, "", ""),
        "_refresh_deferred": lambda e: (False, ""),
        "_refresh_hold": lambda e, r, n: (False, ""),
        "relay_model": lambda c: "sonnet",
    }
    orig = {k: getattr(sr, k) for k in patches}
    for k, v in patches.items():
        setattr(sr, k, v)
    try:
        reply, ok = sr.relay(dept, {"msg_id": "M-flow", "content": "テスト便"}, {}, "TOK")
    finally:
        for k, v in orig.items():
            setattr(sr, k, v)
    return reply, ok, calls, (saved.get("entry") or {})


def main():
    # --- ① 第3の箱の判定(=これが本体) ---------------------------------------
    check("★rc=0で本文が無い応答を「空返答」と判定できる(実物の形)",
          sr.looks_like_empty_reply(0, EMPTY, EMPTY_OUT) is True)
    check("本文がある応答は空返答ではない",
          sr.looks_like_empty_reply(0, OK, json.dumps(OK)) is False)

    # --- ① 口座・上限側の挙動が1文字も変わっていないこと -----------------------
    check("★上限エラー(rc=1)は空返答の箱に入らない=従来の枝のまま",
          sr.looks_like_empty_reply(1, LIMIT, json.dumps(LIMIT, ensure_ascii=False)) is False)
    check("★クレジット切れ(rc=1)は空返答の箱に入らない=世代交代しない(2026-07-25の穴を踏まない)",
          sr.looks_like_empty_reply(1, CREDIT, json.dumps(CREDIT, ensure_ascii=False)) is False)
    check("認証失敗は空返答の箱に入らない(INC-109=やり直さない枝が先)",
          sr.looks_like_empty_reply(0, {}, "Failed to authenticate (401)") is False)
    check("セッション不明は空返答の箱に入らない(従来どおり素直に世代交代)",
          sr.looks_like_empty_reply(0, {}, "No conversation found with session ID: x") is False)
    check("応答そのものが読めなかった(data=None)時も空返答として拾う(黙って死なせない)",
          sr.looks_like_empty_reply(0, None, "") is True)
    check("is_error:true なら rc=0 でも空返答扱いにしない前に本文が空=拾う"
          "(★どちらにせよ交代で復帰する側へ倒す)",
          sr.looks_like_empty_reply(0, {"is_error": True, "result": "x"}, "") is True)

    # --- 催促の文面が、実測の死に方を名指しで潰していること ---------------------
    n = sr.EMPTY_REPLY_NUDGE
    check("★催促の文が『No response requested.』を名指しで禁じている(実測の死に方)",
          "No response requested." in n)
    check("催促がChamiの発言と誤解されない(機械の催促だと明記)", "Chamiの発言ではない" in n)
    check("催促が『返す物が無いなら理由を1行』まで書かせる(沈黙を残さない)", "沈黙" in n)

    # --- ② 交代の枝が実際にコードに在ること -----------------------------------
    src = open(os.path.join(ROOT, "scripts", "llm", "session_relay.py"),
               encoding="utf-8").read()
    check("★空返答なら催促を1回だけ挟む枝が在る", "EMPTY_REPLY_NUDGE" in src
          and "_empty_nudged = True" in src)
    check("★催促しても空なら世代交代へ倒す枝が在る",
          "空返答(催促も空)→世代交代" in src)
    check("★空返答**以外**は従来どおり交代せず1回で諦める(条件が残っている)",
          "if not _looks_like_session_missing(out) and not _empty_nudged:" in src)

    # --- ★②' 経路そのものを**実行で**通す(2026-08-14 追加) --------------------
    #   注文= 研究室HQ DISPATCH-aegis-gl-1786645062923 §2。
    #     「上の3項目はソース文字列の一致=**動作ではなく文面**の検査だ。行を書き直したら
    #       偽陰性になるし、**催促→交代の経路そのものを通す検査が無い**。
    #       この作りだと**本番の初発火が実質の初検証**になる」。
    #   → `_run_claude` を偽物に差し替えて **relay() を本物のまま**回し、
    #     「催促が1回だけ飛ぶ / 2回目も空なら新セッションで作り直す」を**実行で**見る。
    for name, seq, want in (
        ("催促で返った=交代しない",
         [(EMPTY, 0, EMPTY_OUT), (OK, 0, json.dumps(OK))], 2),
        ("催促も空=世代交代して作り直す",
         [(EMPTY, 0, EMPTY_OUT), (EMPTY, 0, EMPTY_OUT),
          (OK2, 0, json.dumps(OK2))], 3),
        ("★口座エラー(rc=1)は催促も交代もせず1回で諦める",
         [(CREDIT, 1, json.dumps(CREDIT, ensure_ascii=False))], 1),
    ):
        reply, ok, calls, ent = drive(seq)
        print(f"  [{name}] _run_claude {len(calls)}回 / ok={ok} / 世代={ent.get('generation')}")
        check(f"{name}= claudeを{want}回だけ回す", len(calls) == want)
        if want == 2:
            check("★催促は1回だけ・文面は EMPTY_REPLY_NUDGE そのもの",
                  calls[1]["prompt"] == sr.EMPTY_REPLY_NUDGE)
            check("★催促は**同じセッション**へ投げる(記憶を捨てない)",
                  calls[1]["sid"] == EMPTY["session_id"])
            check("催促で返った便はそのまま配る(世代は上がらない)",
                  ok is True and reply == OK["result"] and ent.get("generation") == 3)
        elif want == 3:
            check("★2回目も空→3回目は session_id 無し=**新セッション**で作り直す",
                  calls[2]["sid"] is None)
            # ★空返答の交代では引き継ぎを作らない(引き継ぎ文を書かせる相手が、
            #   まさに答えを返せないセッションだからだ)= 欠落の一言が末尾に付くのが正しい。
            check("★交代後の返信がChamiへ返る(便を殺さない)",
                  ok is True and (reply or "").startswith(OK2["result"]))
            check("引き継げなかったことを1行で告げている(黙って記憶を落とさない)",
                  "引き継げなかった" in (reply or ""))
            check("世代が1つ上がり、対応表が新しいセッションを指す",
                  ent.get("generation") == 4
                  and ent.get("active_session_id") == OK2["session_id"])
        else:
            check("★口座エラーは催促を投げない(2026-07-25の枝のまま・箱が混ざっていない)",
                  all(c["prompt"] != sr.EMPTY_REPLY_NUDGE for c in calls))
            check("★口座エラーは交代せず ok=False で諦める(新セッションを作らない)",
                  ok is False and reply is None)

    # --- ② dead になった時に通知が出ること(9325c04 のBが効く経路) -------------
    sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))
    from leasequeue import LeaseQueue  # noqa: E402
    import tempfile
    import shutil
    d = tempfile.mkdtemp(prefix="qa_empty_")
    try:
        seen = []
        q = LeaseQueue(os.path.join(d, "q.db"), lease_sec=1, max_deliveries=2)
        q.on_dead = lambda info: seen.append(info)
        q.enqueue({"content": "空返答で落ちる便"}, msg_id="M-empty", dept="llmqa")
        for _ in range(5):
            c = q.claim(dept="llmqa", who="t")
            if c:
                q.nack(c["id"])          # 空返答は外部要因ではない=返金しない(普通に数える)
        st = q._db.execute("SELECT status FROM queue WHERE msg_id='M-empty'").fetchone()
        check("空返答は返金しない=毒として普通に数えられる(無限ループを作らない)", st[0] == "dead")
        check("★dead になるなら通知が出る(9325c04のBが効いている)", len(seen) == 1)
        check("消えない記録がDBの隣に残る",
              os.path.exists(os.path.join(d, "dead_letters.jsonl")))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # --- ③ 実測の裏取り: 壊れた実物がログに在ること ---------------------------
    log = os.path.join(ROOT, "local", "llm", "request_log.jsonl")
    n_empty = 0
    for line in open(log, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("state") == "failed" and "rc=0" in r.get("evidence", "") \
                and r.get("dept") in ("llm-qa", "future-room"):
            n_empty += 1
    check(f"★壊れた実物がログに在る(llm-qa+future-room の rc=0 失敗 {n_empty}件・11件以上)",
          n_empty >= 11)

    ok = all(v for _, v in results)
    print(f"\n== {sum(v for _, v in results)}/{len(results)} PASS ==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
