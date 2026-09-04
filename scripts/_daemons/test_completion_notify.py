#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""完遂通知(dispatch の from_dept 記録 + completion_notify)の検査(2026-09-04・aegis-gl)。

★C-053の作法どおり、**ソースの文字列一致では固めない**。
  外へ出る手(Discordへの投函)だけ偽物にして、**判定と分岐は本物のまま**経路を実行し、
  「実際に渡った宛先」を集めて突き合わせる。台帳も一時ディレクトリへ隔離する
  (`GO5_LOCAL_DIR`)ので、本番の request_log にもキューにも1行も書かない。

走らせ方:
  python scripts/_daemons/test_completion_notify.py
"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
JST = dt.timezone(dt.timedelta(hours=9))

# ★import より前に台帳の置き場を差し替える(モジュール定数は import 時に決まる)。
SANDBOX = tempfile.mkdtemp(prefix="cn_test_")
os.environ["GO5_LOCAL_DIR"] = SANDBOX
os.makedirs(os.path.join(SANDBOX, "llm"), exist_ok=True)

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
import completion_notify as cn      # noqa: E402
import dispatch as dsp              # noqa: E402

RESULTS = []


def chk(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"  {'PASS' if cond else '★FAIL'}  {name}{('  ' + detail) if detail else ''}")


def ts_ago(minutes):
    return (dt.datetime.now(JST) - dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S")


def write_ledgers(reqs, letters):
    with open(cn.REQUEST_LOG, "w", encoding="utf-8") as f:
        for r in reqs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(cn.PROCESSED, "w", encoding="utf-8") as f:
        for r in letters:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def run(argv=(), **kw):
    """main() を本物のまま走らせ、send() に渡った宛先を集める。"""
    sent = []

    def fake_send(to_dept, from_dept, body, dry_run):
        sent.append({"to": to_dept, "from": from_dept, "body": body, "dry": dry_run})
        return True, "(fake)"

    real, sys_argv = cn.send, sys.argv
    cn.send = fake_send
    sys.argv = ["completion_notify.py"] + list(argv)
    try:
        cn.main()
    finally:
        cn.send, sys.argv = real, sys_argv
    return sent


def letter(mid, dept, from_dept, explicit, work="骨格を参考へ寄せる", ts=None):
    return {"ts": ts or ts_ago(120), "dept": dept, "channel": "部屋", "author": "誰か",
            "content": "依頼本文", "msg_id": mid, "via": "dispatch", "audience": "ai",
            "work": work, "from_dept": from_dept, "from_dept_explicit": explicit}


def done(mid, dept, minutes, state="replied", landed="9999"):
    return {"ts": ts_ago(minutes), "request_id": mid, "dept": dept, "state": state,
            "evidence": f"discord_msg={landed} 部屋=どこか 分割1通の最終通を実在確認"}


# ---------------------------------------------------------------- completion_notify
def test_notify():
    print("\n■ completion_notify(判定と分岐は本物・投函だけ偽物)")

    # C-1 発注元が明示された便 → 発注元の部屋へ鳴る
    write_ledgers([done("1001", "shorts-analyst", 60)],
                  [letter("1001", "shorts-analyst", "research-room", True)])
    s = run()
    chk("C-1 発注元が明示された依頼は発注元の部屋へ鳴る",
        len(s) == 1 and s[0]["to"] == "research-room" and s[0]["from"] == "shorts-analyst",
        f"→ {[x['to'] for x in s]}")
    chk("C-1b 本文に着地msg_idが入る(成果の在りかへ辿れる)",
        len(s) == 1 and "9999" in s[0]["body"], "")
    chk("C-1c 本文に依頼の要旨が入る",
        len(s) == 1 and "骨格を参考へ寄せる" in s[0]["body"], "")
    chk("C-1d 本体は運ばない(依頼本文をそのまま貼らない)",
        len(s) == 1 and "依頼本文" not in s[0]["body"], "")

    # C-2 冪等= 2回目は鳴らない(completion_notified が追記されている)
    s2 = run()
    chk("C-2 同じ依頼で二度鳴らさない(冪等)", len(s2) == 0, f"→ {len(s2)}件")
    with open(cn.REQUEST_LOG, encoding="utf-8") as f:
        tail = f.read()
    chk("C-2b 冪等の根拠は request_log への追記(既存行は書き換えない)",
        '"completion_notified"' in tail and tail.count('"state": "replied"') == 1, "")

    # C-3 --from-dept が明示されていない便 → 推定しない(鳴らない)
    write_ledgers([done("1002", "shorts-analyst", 60)],
                  [letter("1002", "shorts-analyst", "hq", False)])
    chk("C-3 発注元が既定値(明示なし)の便は鳴らさない", len(run()) == 0)

    # C-4 自室完結 → 鳴らない
    write_ledgers([done("1003", "aegis-gl", 60)],
                  [letter("1003", "aegis-gl", "aegis-gl", True)])
    chk("C-4 発注元と請けた側が同じなら鳴らさない", len(run()) == 0)

    # C-5 請けた側が完遂後に自分で返している → 抑える(要件3)
    write_ledgers([done("1004", "copy-director", 60)],
                  [letter("1004", "copy-director", "research-room", True),
                   letter("2004", "research-room", "copy-director", True,
                          work="", ts=ts_ago(30))])
    chk("C-5 請けた側が自分で返していたら抑える", len(run()) == 0)

    # C-5b 返したのが完遂より**前**なら別件=抑えない
    write_ledgers([done("1005", "copy-director", 60)],
                  [letter("1005", "copy-director", "research-room", True),
                   letter("2005", "research-room", "copy-director", True,
                          work="", ts=ts_ago(90))])
    chk("C-5b 完遂より前の便では抑えない(別件だから)", len(run()) == 1)

    # C-5c ★並走= 同じ部門ペアで依頼が2件、請けた側の返信は1通だけ。
    #   初版は「そのペアに返信が1通でもあれば抑える」だったので**両方**黙って落ちた。
    #   (2026-09-04 qa-reviewer(ジェンティルドンナ)が挙げた「緑のまま通り抜ける壊れ方」・
    #    再現手順は msg=1545281379862843414 のまま使っている)
    #   1通は1件しか打ち消せない= 残り1件は鳴らなければならない。
    write_ledgers([done("1010", "copy-director", 60), done("1011", "copy-director", 60)],
                  [letter("1010", "copy-director", "research-room", True),
                   letter("1011", "copy-director", "research-room", True),
                   letter("2011", "research-room", "copy-director", True,
                          work="req1011だけの返信", ts=ts_ago(30))])
    s5c = run()
    chk("C-5c 並走2件に返信1通なら、残り1件は鳴る(抑制は依頼1件分しか消費しない)",
        len(s5c) == 1, f"→ {len(s5c)}件")

    # C-5d 返信が2通あれば2件とも抑える(消費モデルが鳴らし過ぎない側の証拠)
    write_ledgers([done("1012", "copy-director", 60), done("1013", "copy-director", 60)],
                  [letter("1012", "copy-director", "research-room", True),
                   letter("1013", "copy-director", "research-room", True),
                   letter("2012", "research-room", "copy-director", True, work="",
                          ts=ts_ago(30)),
                   letter("2013", "research-room", "copy-director", True, work="",
                          ts=ts_ago(29))])
    chk("C-5d 並走2件に返信2通なら両方とも抑える", len(run()) == 0)

    # C-5e 返信が1通も無ければ並走2件とも鳴る(基準線)
    write_ledgers([done("1014", "copy-director", 60), done("1015", "copy-director", 60)],
                  [letter("1014", "copy-director", "research-room", True),
                   letter("1015", "copy-director", "research-room", True)])
    chk("C-5e 並走2件に返信0通なら2件とも鳴る", len(run()) == 2)

    # C-6 完遂したてはまだ触らない(請けた側が自分で返す猶予)
    write_ledgers([done("1006", "copy-director", 2)],
                  [letter("1006", "copy-director", "research-room", True)])
    chk("C-6 猶予(min-age)内は鳴らさない", len(run()) == 0)
    chk("C-6b 猶予を0にすれば鳴る(窓の判定が効いている証拠)",
        len(run(["--min-age-min", "0"])) == 1)

    # C-7 古すぎる完遂は触らない(入れた瞬間に過去を全部鳴らさない)
    write_ledgers([done("1007", "copy-director", 60 * 48)],
                  [letter("1007", "copy-director", "research-room", True)])
    chk("C-7 窓(since-hours)より古い完遂は鳴らさない", len(run()) == 0)

    # C-8 dispatch を通らない依頼(Chami発など)は宛先が無いので鳴らさない
    write_ledgers([done("1008", "copy-director", 60)], [])
    chk("C-8 便が見つからない依頼は鳴らさない(推定しない)", len(run()) == 0)

    # C-9 dry-run では投函も追記もしない
    write_ledgers([done("1009", "copy-director", 60)],
                  [letter("1009", "copy-director", "research-room", True)])
    s9 = run(["--dry-run"])
    with open(cn.REQUEST_LOG, encoding="utf-8") as f:
        body9 = f.read()
    chk("C-9 --dry-run は台帳へ書かない", '"completion_notified"' not in body9,
        f"(送信の呼び出し自体は {len(s9)}件・dry旗={s9[0]['dry'] if s9 else '-'})")


# ---------------------------------------------------------------- dispatch の記録側
def test_dispatch_records_from_dept():
    print("\n■ dispatch.py が便レコードへ発注元を残す(一時キューDBで経路実行)")
    qdb = os.path.join(SANDBOX, "queue", "inbox.db")
    os.makedirs(os.path.dirname(qdb), exist_ok=True)
    real_qdb = dsp.QUEUE_DB
    dsp.QUEUE_DB = qdb
    try:
        # work を空にする= 表投稿の経路に入らない(本番の部屋へは1文字も出さない)
        ok1, mid1 = dsp.dispatch("aegis-gl", "検査", "本文A", from_dept="research-room",
                                 from_dept_explicit=True)
        ok2, mid2 = dsp.dispatch("aegis-gl", "検査", "本文B", from_dept="hq",
                                 from_dept_explicit=False)
        recs = read_queue(qdb)
        chk("D-1 投函できた(隔離キュー)", ok1 and ok2, f"{mid1} / {mid2}")
        r1 = recs.get(mid1, {})
        r2 = recs.get(mid2, {})
        chk("D-2 便レコードに from_dept が載る",
            r1.get("from_dept") == "research-room", f"→ {r1.get('from_dept')!r}")
        chk("D-3 明示指定は from_dept_explicit=True で残る",
            r1.get("from_dept_explicit") is True, f"→ {r1.get('from_dept_explicit')!r}")
        chk("D-4 既定値の hq は explicit=False で区別できる",
            r2.get("from_dept") == "hq" and r2.get("from_dept_explicit") is False,
            f"→ {r2.get('from_dept')!r}/{r2.get('from_dept_explicit')!r}")
        chk("D-5 既存のキーを壊していない",
            all(k in r1 for k in ("ts", "dept", "channel", "author", "content",
                                  "msg_id", "via")), "")
    finally:
        dsp.QUEUE_DB = real_qdb


def read_queue(qdb):
    """一時キューDBから {msg_id: レコード} を読む(本文JSONを開く)。"""
    import sqlite3
    out = {}
    con = sqlite3.connect(qdb)
    try:
        for row in con.execute("SELECT body FROM queue"):
            try:
                r = json.loads(row[0])
                out[r.get("msg_id")] = r
            except Exception:
                pass
    finally:
        con.close()
    return out


def run_dispatch_main(argv, env_dept=None, qdb=None):
    """dispatch.main() を**本物のまま**走らせる(3階梯ガードも呼称ゲートも通る)。

    ★環境の GO5_DEPT だけを差し替える。表投稿には入らない(--work を付けない)。
    """
    real_qdb, real_argv = dsp.QUEUE_DB, sys.argv
    had = "GO5_DEPT" in os.environ
    old = os.environ.get("GO5_DEPT")
    if env_dept is None:
        os.environ.pop("GO5_DEPT", None)
    else:
        os.environ["GO5_DEPT"] = env_dept
    if qdb:
        dsp.QUEUE_DB = qdb
    sys.argv = ["dispatch.py"] + list(argv)
    try:
        return dsp.main()
    finally:
        dsp.QUEUE_DB, sys.argv = real_qdb, real_argv
        os.environ.pop("GO5_DEPT", None)
        if had:
            os.environ["GO5_DEPT"] = old


def test_env_from_dept():
    """★2026-09-04 HQ裁定(選択肢3)= 発注元を機械が載せる経路。

    人手の入口(--from-dept)は実測0件だった。部屋のセッションを起こす側
    (dept_daemon / session_relay)が子の環境へ `GO5_DEPT` を入れ、dispatch がそれを拾う。
    """
    print("\n■ 発注元を機械が載せる(GO5_DEPT・main を本物で実行)")
    qdb = os.path.join(SANDBOX, "queue", "env.db")
    os.makedirs(os.path.dirname(qdb), exist_ok=True)

    # E-1 --from-dept が無くても、環境に部門が居れば発注元として載る
    rc1 = run_dispatch_main(["--dept", "qa-reviewer", "--direct", "--from", "検査",
                             "--audience", "ai", "--body", "本文E1"],
                            env_dept="copy-director", qdb=qdb)
    recs = read_queue(qdb)
    e1 = [r for r in recs.values() if r.get("content") == "本文E1"]
    chk("E-1 --from-dept が無くても GO5_DEPT が発注元として載る",
        rc1 == 0 and len(e1) == 1 and e1[0].get("from_dept") == "copy-director",
        f"rc={rc1} → {e1[0].get('from_dept') if e1 else None!r}")
    chk("E-1b 機械が載せた発注元は explicit=True(完遂通知が鳴らす対象になる)",
        len(e1) == 1 and e1[0].get("from_dept_explicit") is True, "")
    chk("E-1c 出所が env として区別できる(人手/機械/既定を後から数えられる)",
        len(e1) == 1 and e1[0].get("from_dept_src") == "env",
        f"→ {e1[0].get('from_dept_src') if e1 else None!r}")

    # E-2 人手の明示は環境より強い(取り違えを人が直せる)
    run_dispatch_main(["--dept", "qa-reviewer", "--direct", "--from", "検査",
                       "--from-dept", "research-room", "--audience", "ai", "--body", "本文E2"],
                      env_dept="copy-director", qdb=qdb)
    e2 = [r for r in read_queue(qdb).values() if r.get("content") == "本文E2"]
    chk("E-2 --from-dept の明示は GO5_DEPT より優先される",
        len(e2) == 1 and e2[0].get("from_dept") == "research-room"
        and e2[0].get("from_dept_src") == "arg",
        f"→ {e2[0].get('from_dept') if e2 else None!r}")

    # E-3 どちらも無ければ従来どおり(既定 hq・explicit=False=常駐は鳴らさない)
    run_dispatch_main(["--dept", "qa-reviewer", "--direct", "--from", "検査",
                       "--audience", "ai", "--body", "本文E3"], env_dept=None, qdb=qdb)
    e3 = [r for r in read_queue(qdb).values() if r.get("content") == "本文E3"]
    chk("E-3 環境も明示も無ければ既定 hq・explicit=False(従来と同じ)",
        len(e3) == 1 and e3[0].get("from_dept") == "hq"
        and e3[0].get("from_dept_explicit") is False
        and e3[0].get("from_dept_src") == "default", "")

    # E-4 ★★3階梯ガードの入力を変えていない(既存の便を1本も落とさない証拠)。
    #   `--direct` 無しで配下部門(qa-reviewer・部門長=aegis-gl)へ出すと、従来は
    #   from_dept が既定 "hq" なので免除(ORG-42)に入らず**ブロック=rc 2**になる。
    #   ここで環境値をガードへ流していると `h == from_dept` が成立して**通ってしまう**=
    #   ガードの効き方が全部屋で変わる。それは3階梯(RULES §6.4)の変更であって、
    #   発注元の記録のついでに入れてよい変更ではない。だから記録専用にしてある。
    rc4 = run_dispatch_main(["--dept", "qa-reviewer", "--from", "検査",
                             "--audience", "ai", "--body", "本文E4"],
                            env_dept="aegis-gl", qdb=qdb)
    e4 = [r for r in read_queue(qdb).values() if r.get("content") == "本文E4"]
    chk("E-4 GO5_DEPT は3階梯ガードの判定を変えない(部門長でも --direct 無しは従来どおり止まる)",
        rc4 == 2 and len(e4) == 0, f"rc={rc4} / 投函{len(e4)}件")

    # E-5 session_relay の起こし口が実際に GO5_DEPT を載せる(ソース一致ではなく実行)
    try:
        import importlib
        sr = importlib.import_module("session_relay")
        env_with = sr._child_env("dummy-token", "aegis-gl")
        env_without = sr._child_env("dummy-token")
        chk("E-5 session_relay._child_env は dept を GO5_DEPT として子へ渡す",
            env_with.get("GO5_DEPT") == "aegis-gl", f"→ {env_with.get('GO5_DEPT')!r}")
        chk("E-5b dept が無い呼び出しでは載せない(空文字で騙らない)",
            "GO5_DEPT" not in env_without, "")
    except Exception as ex:
        chk("E-5 session_relay._child_env の実行", False, f"import/実行に失敗: {ex}")


def main():
    print("完遂通知の検査(台帳は一時ディレクトリへ隔離=本番へ1行も書かない)")
    print(f"  sandbox= {SANDBOX}")
    try:
        test_notify()
        test_dispatch_records_from_dept()
        test_env_from_dept()
    finally:
        shutil.rmtree(SANDBOX, ignore_errors=True)
    ng = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(ng)}/{len(RESULTS)} PASS")
    if ng:
        print("★FAIL: " + " / ".join(ng))
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
