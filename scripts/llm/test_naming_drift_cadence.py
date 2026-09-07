# -*- coding: utf-8 -*-
"""持続ドリフト便の**鳴り方**(いつ鳴らすか)の回帰ガード(2026-09-08 イージス研究室)。

発注= 人事部門ククール msg 1546651338312523827
  「無人の見張りが**答えの出た裁定**を毎時間、有人部屋へ撃ち続けている= 鳴り方を機構で直せ」。

0歩目に見た壊れている実物(local/_state/envelope_naming_watch.jsonl・drift_alert 17行):
  04:38 / 05:38 / 06:38 / 07:38 と**1時間おきに同じ44行の便**が hr-room へ落ちていた。
  原因は「顔ぶれ(`sig()`)が変わった時だけ鳴らす」という**集合の一致**での抑制だ=
  窓14日が1時間ずつ滑るたび、しきい値(5件/3日/2人格)の縁に居る組が出たり入ったりする。
  実物の1時間ごとの差分= 04:38「一ノ瀬怜>怜」が増える / 05:38「ククール>ク」が入れ替わる /
  06:38「シャビ・アロンソ>シャビ・アロンソ」が抜ける / 07:38「一ノ瀬怜>一ノ瀬!」が抜ける。
  **集合は毎時ずれる= sig は毎時変わる= 毎時 full-dump。**抑制の設計そのものが誤りだった。

直した形= 集合の一致ではなく**組の記憶**(`naming_drift_check.diff_pairs`):
  ① 今まで一度も知らせていない組が立った時だけ鳴る
  ② 既報でも banned が False→True(禁止後の再発へ変わった)なら鳴る
  ③ 組の記憶は PAIR_TTL_DAYS 日で忘れる= 窓から完全に出た組が後日また立てば再び鳴る
  ★①〜③のどれも無い時刻は**鳴らさない**(組が消えただけ・件数が動いただけでは鳴らさない)。

規律(00_AI-HQ/departments/00_common/手順_must-fail検査.md):
  - 判定と分岐は本物のまま。偽物にするのは**外へ出る手**(notify_drift)と台帳ファイルだけ。
  - 検査対象は毎回ソースから読んで exec(.pyc の偽PASSを踏まない)。
  - 最後に must-fail= 実装を「動く別の実装」へ変異させ、この検査が落ちるか確かめる。
    ★変異①は**この改修の前の実装そのもの**= これが赤にならなければ、この検査は
      「毎時鳴る」を捕まえられていない=置く意味が無い。

実行: python scripts/llm/test_naming_drift_cadence.py
      python scripts/llm/test_naming_drift_cadence.py --mutate   … 変異だけ回す
"""
import io
import json
import os
import shutil
import sys
import tempfile
import types

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
PJ = os.path.dirname(os.path.dirname(HERE))
NDC = os.path.join(HERE, "naming_drift_check.py")
WATCH = os.path.join(PJ, "scripts", "_daemons", "envelope_naming_watch.py")

FAIL = []


def ok(cond, name, detail=""):
    print(("  OK   " if cond else "  FAIL ") + name + (("  " + detail) if detail else ""))
    if not cond:
        FAIL.append(name)


def load(path, name):
    """★ソースから読んで exec= .pyc の偽PASSを踏まない。"""
    src = open(path, encoding="utf-8").read()
    mod = type(sys)(name)
    mod.__file__ = path
    exec(compile(src, path, "exec"), mod.__dict__)
    return mod


# ────────────────────────────────────────────────── 治具(組の形・台帳の形)
def drift(target, found, forbidden=0, count=6):
    """`scan()` が返す形。forbidden>0 = 禁止に名指しで載せた後も出ている(=banned)。"""
    return {"target": target, "found": found, "expected": ["怜"], "count": count,
            "days": 3, "personas": ["オタコン", "トトリ"],
            "first": "2026-09-02T00:00:00", "last": "2026-09-08T00:00:00",
            "voc": count, "judgeable": count,
            "reasons": ({"forbidden": forbidden} if forbidden
                        else {"override_allowed": count})}


A = drift("一ノ瀬怜", "一ノ瀬")
B = drift("ルカ・モドリッチ", "ルカ")
C = drift("シャビ・アロンソ", "シャビ")
A_BANNED = drift("一ノ瀬怜", "一ノ瀬", forbidden=6)


def row(ts, persona, target, found, reason="override_allowed"):
    """本物の台帳行の形。★near は**裸の姓**の現場= フル名除外(別検査)に食われない。"""
    return {"ts": ts, "dept": "aegis-gl", "event": "naming", "persona": persona,
            "target": target, "found": found, "expected": ["怜"],
            "reason": reason, "source": "dispatch", "msg_id": "",
            "near": "この件は%sへ回す。手が空いているのは" % found,
            "excerpt": "[%s]\n%sさん、着手前の一声です。" % (persona, found), "voc": 1}


def pair_rows(target, found, tag):
    """1組を持続ドリフトのしきい値(5件/3日/2人格)へちょうど乗せる6行。"""
    out = []
    for day in ("2026-09-02", "2026-09-05", "2026-09-08"):
        for i, persona in enumerate(("オタコン", "トトリ")):
            out.append(row("%sT1%d:0%d:00" % (day, i, len(tag)), persona, target, found))
    return out


L_AB = pair_rows("一ノ瀬怜", "一ノ瀬", "a") + pair_rows("ルカ・モドリッチ", "ルカ", "b")
L_ABC = L_AB + pair_rows("シャビ・アロンソ", "シャビ", "c")


def write_rows(path, rows, pad=0):
    """★pad= 回ごとにファイルの大きさを変える行(event が naming ではない=集計に入らない)。

    見張りは「台帳が伸びていなければ何もしない」ので、伸びない治具だと2回目以降が
    材料版の一致で素通りし、**抑制が効いた**ように見えてしまう(偽PASS)。
    """
    with io.open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        for i in range(pad):
            f.write(json.dumps({"ts": "2026-09-08T23:59:%02d" % i, "event": "naming_fix",
                                "persona": "オタコン", "target": "一ノ瀬怜",
                                "found": "一ノ瀬"}, ensure_ascii=False) + "\n")


def replay(w, ndc, tmp, tag, ledgers, state0=None):
    """見張りを**本物のまま**N回まわし、外へ出た便だけを受け取る。

    ★偽物にするのは `notify_drift`(外へ出る手)と `_log` だけ= 判定・分岐・状態書き込みは本物。
      dry は使わない= dry で抑制を確かめると「dry だから黙った」と見分けが付かない。
    """
    state = os.path.join(tmp, "state_%s.json" % tag)
    if state0 is not None:
        io.open(state, "w", encoding="utf-8").write(json.dumps(state0, ensure_ascii=False))
    led = os.path.join(tmp, "ledger_%s.jsonl" % tag)
    sent = []
    w.STATE_DRIFT = state
    w._log = lambda d: None
    w.notify_drift = lambda body, dry: (sent.append(body), "sent")[1]
    w.load_drift = lambda: ndc
    ndc.AUDIT = led                                  # 材料版もこの治具の台帳を見る
    for i, rows in enumerate(ledgers):
        write_rows(led, rows, pad=i)
        w.run_drift(types.SimpleNamespace(force=False, drift_ledger=led,
                                          selftest="", dry=False), False)
    return sent, state


# ───────────────────────────────────────────────── T1 組の記憶(鳴る/黙る)
def t1(n):
    print("[1] diff_pairs= 初出と禁止後の再発だけで鳴る")
    d1 = n.diff_pairs({}, [A, B], "2026-09-08")
    ok(sorted(d1["fresh"]) == ["ルカ・モドリッチ>ルカ", "一ノ瀬怜>一ノ瀬"],
       "1a 記憶が空= 2組とも初出(初回は必ず鳴る)", str(d1["fresh"]))
    d2 = n.diff_pairs(d1["pairs"], [A, B], "2026-09-08")
    ok(not d2["fresh"] and not d2["rebanned"],
       "1b 同じ顔ぶれで2回目= 鳴らさない", str(d2))
    # ★これが実物の壊れ方= 組が抜けて、また戻る(窓が滑るだけで起きる)。
    d3 = n.diff_pairs(d2["pairs"], [A], "2026-09-08")
    ok(not d3["fresh"] and not d3["rebanned"],
       "1c ★組が**消えた**だけ= 鳴らさない(旧実装はここで sig が変わって鳴った)", str(d3))
    d4 = n.diff_pairs(d3["pairs"], [A, B], "2026-09-08")
    ok(not d4["fresh"] and not d4["rebanned"],
       "1d ★消えた組が**戻った**だけ= 鳴らさない(記憶に残っている=既報)", str(d4))
    d5 = n.diff_pairs(d4["pairs"], [A, B, C], "2026-09-08")
    ok(d5["fresh"] == ["シャビ・アロンソ>シャビ"],
       "1e 本当に新しい組が立ったら鳴る(初出はその1組だけ)", str(d5["fresh"]))
    ok(n.pair_key(A) == "一ノ瀬怜>一ノ瀬", "1f 組の鍵に banned の『!』を混ぜない",
       n.pair_key(A_BANNED))


def t1b(n):
    print("[1b] 禁止後の再発への切り替わりは鳴らす(節目を黙って通さない)")
    d1 = n.diff_pairs({}, [A], "2026-09-08")
    d2 = n.diff_pairs(d1["pairs"], [A_BANNED], "2026-09-08")
    ok(d2["rebanned"] == ["一ノ瀬怜>一ノ瀬"] and not d2["fresh"],
       "1g banned が False→True= 鳴る(初出ではなく再発として)", str(d2))
    d3 = n.diff_pairs(d2["pairs"], [A_BANNED], "2026-09-08")
    ok(not d3["rebanned"], "1h True→True= もう鳴らさない(切り替わった一度だけ)", str(d3))
    d4 = n.diff_pairs(d3["pairs"], [A], "2026-09-08")
    d5 = n.diff_pairs(d4["pairs"], [A_BANNED], "2026-09-08")
    ok(not d5["rebanned"],
       "1i 禁止行が窓から出て戻っただけでは鳴らさない(banned の記憶は下がらない)", str(d5))


# ──────────────────────────────────────────────────────── T2 忘れる(TTL)
def t2(n):
    print("[2] PAIR_TTL_DAYS= 窓から完全に出た組は忘れて、再発で鳴らし直す")
    ok(n.PAIR_TTL_DAYS == n.WINDOW_DAYS,
       "2a TTL は窓と同じ日数(窓に居る間は既報のまま)", "%d日" % n.PAIR_TTL_DAYS)
    mem = {"一ノ瀬怜>一ノ瀬": {"last": "2026-08-25", "banned": False}}   # 14日前
    d = n.diff_pairs(mem, [A], "2026-09-08")
    ok(not d["fresh"], "2b ちょうど14日= まだ覚えている(鳴らさない)", str(d["fresh"]))
    mem = {"一ノ瀬怜>一ノ瀬": {"last": "2026-08-24", "banned": False}}   # 15日前
    d = n.diff_pairs(mem, [A], "2026-09-08")
    ok(d["fresh"] == ["一ノ瀬怜>一ノ瀬"],
       "2c 15日ぶり= 忘れている=**再発として鳴る**", str(d["fresh"]))
    # ★int の 20260825 は py3.11 以降の fromisoformat が**読めてしまう**ので混ぜない=
    #   「読めない値」の検査に、読める値を置くと検査が嘘になる。
    for bad in ({"last": None, "banned": False}, {"last": "きのう", "banned": False},
                {"last": "2026-99-99", "banned": False}, {"last": [], "banned": False}):
        d = n.diff_pairs({"一ノ瀬怜>一ノ瀬": bad}, [A], "2026-09-08")
        ok(d["fresh"] == ["一ノ瀬怜>一ノ瀬"],
           "2d 日付が読めない記憶= 忘れる側へ倒す(fail-open・最悪もう一度鳴るだけ)",
           str(bad))
    d = n.diff_pairs({"一ノ瀬怜>一ノ瀬": "こわれた"}, [A], "2026-09-08")
    ok(d["fresh"] == ["一ノ瀬怜>一ノ瀬"], "2e 記憶が辞書ですらない= 同じく鳴る側へ")
    d = n.diff_pairs("こわれた", [A], "2026-09-08")
    ok(d["fresh"] == ["一ノ瀬怜>一ノ瀬"], "2f 記憶ごと壊れている= 同じく鳴る側へ")


# ─────────────────────────────────────────────── T3 旧stateからの移行
def t3(n):
    print("[3] seed_pairs= 旧state(顔ぶれ文字列)から記憶を作る")
    seeded = n.seed_pairs("一ノ瀬怜>一ノ瀬!|ルカ・モドリッチ>ルカ", "2026-09-08")
    ok(sorted(seeded) == ["ルカ・モドリッチ>ルカ", "一ノ瀬怜>一ノ瀬"],
       "3a 『!』を落として組の鍵にする", str(sorted(seeded)))
    ok(seeded["一ノ瀬怜>一ノ瀬"]["banned"] is True and
       seeded["ルカ・モドリッチ>ルカ"]["banned"] is False,
       "3b 『!』は banned の欄へ移す(移行直後に偽の再発を鳴らさないため)")
    d = n.diff_pairs(seeded, [A_BANNED, B], "2026-09-08")
    ok(not d["fresh"] and not d["rebanned"],
       "3c ★移行の初回は黙る= 既報8組を『初出』と読んで余計な full-dump を撃たない", str(d))
    ok(n.seed_pairs("", "2026-09-08") == {} and n.seed_pairs(None, "2026-09-08") == {},
       "3d 旧stateが空= 記憶も空(=初回は鳴る側。沈黙で始めない)")


# ───────────────────────────────────────── T4 便の本文(既報は1行へ畳む)
def t4(n):
    print("[4] build_drift_body= 鳴った理由の組だけ開き、既報は1行へ畳む")
    w = load(WATCH, "watch_body")
    drifts = [A, B, C, drift("ククール", "ク"), drift("三笠", "三"),
              drift("ケヴィン・デブライネ", "デブライネ")]
    focus = {"fresh": ["シャビ・アロンソ>シャビ"], "rebanned": [], "pairs": {}}
    # 引いた分= 実物と同じ形(重複154件 / フル名56件)。★ここを空で渡すと 4f が素通りする。
    dup = [{"target": "一ノ瀬怜", "found": "一ノ瀬", "count": 154}]
    fn = [{"target": "一ノ瀬怜", "found": "一ノ瀬", "count": 56}]
    body = w.build_drift_body(n, drifts, [], dup, fn, focus)
    full = w.build_drift_body(n, drifts, [], dup, fn, None)
    ok(body.count("使っている人格=") == 1,
       "4a 開くのは鳴った1組だけ(残り5組は畳む)", "実測%d組を展開" % body.count("使っている人格="))
    ok("既報 5組" in body, "4b 畳んだ分は**数と顔ぶれを見せる**(黙って消さない)")
    ok("- **初めて立った組 1**= シャビ・アロンソ>シャビ" in body,
       "4c 便の頭に『なぜ今これが鳴ったか』が在る")
    ok(len(body) < len(full), "4d 畳んだ便は全展開より短い",
       "%d字 → %d字(%d行 → %d行)"
       % (len(full), len(body), len(full.splitlines()), len(body.splitlines())))
    ok(full.count("使っている人格=") == 6,
       "4e focus=None(手叩き・古い呼び出し元)は従来どおり全部開く",
       "実測%d" % full.count("使っている人格="))
    ok("裁定を頼む" not in body and "もう裁定は頼まない" in body,
       "4f ★答えの出た裁定(フル名56件=違反ではない)をもう一度頼まない(C-046)")
    ok("この便を出した理由" not in full,
       "4g 理由の欄は focus が在る時だけ(無い時に嘘の理由を書かない)")
    ok("重複 154件" in body and "フル名を書いただけ 56件" in body,
       "4h 引いた数は**残す**= 静かにするために『引いた分』ごと消さない(0件に見せない義務)")


# ──────────────────────────────── T5 見張りを本物のまま4回まわす(実物の壊れ方)
def t5(n, tmp):
    print("[5] ★実物の壊れ方の再現= 組がばたつく4時間で何回鳴るか")
    w = load(WATCH, "watch_real")
    sent, state = replay(w, n, tmp, "real", [L_AB, L_ABC, L_AB, L_ABC])
    ok(len(sent) == 2, "5a 4回まわして**2回だけ**鳴る(1回目=初出2組 / 2回目=新しい1組)",
       "実測%d回" % len(sent))
    ok(len(sent) > 1 and "シャビ・アロンソ>シャビ" in sent[1],
       "5b 2回目の便は『シャビが初めて立った』と言っている")
    st = json.load(io.open(state, encoding="utf-8"))
    ok(sorted(st.get("pairs") or {}) ==
       ["シャビ・アロンソ>シャビ", "ルカ・モドリッチ>ルカ", "一ノ瀬怜>一ノ瀬"],
       "5c 記憶が state に残る(次の時刻もここから読む)", str(sorted(st.get("pairs") or {})))
    ok(int(st.get("quiet_rounds") or 0) == 2,
       "5d 黙った回も数える= 見張りが生きている証拠を残す(jsonlは増やさない)",
       "連続%s回" % st.get("quiet_rounds"))


def t6(n, tmp):
    print("[6] 旧state(pairs 欄が無い)から始めた初回が黙る= 移行で1本撃たない")
    w = load(WATCH, "watch_mig")
    old = {"material": "むかしの版", "drift": n.sig(n.scan(_rows_of(n, tmp, L_AB))),
           "checked": "2026-09-08T07:38:34+0900", "last": "sent"}
    sent, _ = replay(w, n, tmp, "mig", [L_AB], state0=old)
    ok(not sent, "6a 旧stateと同じ顔ぶれ= 移行の初回は鳴らない", "実測%d回" % len(sent))


def _rows_of(n, tmp, rows):
    p = os.path.join(tmp, "_seed.jsonl")
    write_rows(p, rows)
    return n.load_rows(p)


# ─────────────────────────────────────────────────────────── T7 本番の実測
def t7(n, tmp):
    print("[7] 本番の見張り記録での実測= 数を口で言わない")
    log = os.path.join(PJ, "local", "_state", "envelope_naming_watch.jsonl")
    if not os.path.exists(log):
        ok(True, "7a 記録が無い環境= 飛ばす")
        return
    sigs = []
    for ln in io.open(log, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        r = json.loads(ln)
        if r.get("event") == "drift_alert":
            sigs.append((r.get("ts", ""), r.get("sig") or ""))
    seen, ring = {}, 0
    for ts, s in sigs:
        drifts = []
        for k in s.split("|"):
            if not k:
                continue
            b = k.endswith("!")
            t_, f_ = (k[:-1] if b else k).split(">", 1)
            drifts.append(drift(t_, f_, forbidden=1 if b else 0))
        day = (ts or "2026-09-08")[:10]
        d = n.diff_pairs(seen, drifts, day)
        seen = d["pairs"]
        ring += 1 if (d["fresh"] or d["rebanned"]) else 0
    old = sum(1 for _, s in sigs if s)
    ok(ring < old, "7a 本番の記録を再生すると鳴る回数が減る(=この修理は空振りではない)",
       "drift_alert %d行 → 新方式 %d回" % (old, ring))
    today = [ts for ts, _ in sigs if ts[:10] == "2026-09-08"]
    print("      2026-09-08 の drift_alert= %d行(%s)"
          % (len(today), "、".join(t[11:16] for t in today)))


# ─────────────────────────────────────────────────────────────── MUST-FAIL
def must_fail(n, tmp):
    print("MUST-FAIL 実装を『動く別の実装』へ変異させて、この検査が落ちるか")
    red = 0
    total = 0

    def mutant(path, name, old, new):
        p = os.path.join(tmp, name + ".py")
        s = open(path, encoding="utf-8").read()
        if old not in s:
            return None
        open(p, "w", encoding="utf-8").write(s.replace(old, new, 1))
        shutil.rmtree(os.path.join(tmp, "__pycache__"), ignore_errors=True)
        return load(p, name)

    # 変異①= **この改修の前の実装**へ戻す(顔ぶれの一致で黙らせる)。動きはする。
    #   ★これが赤にならなければ、この検査は「毎時鳴る」を捕まえていない。
    total += 1
    m = mutant(WATCH, "mut_sigequal",
               '    if not ns.force and not diff["fresh"] and not diff["rebanned"]:',
               '    if not ns.force and st.get("drift") == ds:')
    if m is None:
        ok(False, "変異①の変異点が見つからない(検査が古い)")
    else:
        sent, _ = replay(m, load(NDC, "ndc_m1"), tmp, "m1", [L_AB, L_ABC, L_AB, L_ABC])
        ok(len(sent) == 4, "変異①(顔ぶれの一致で黙らせる=旧実装)= [5a]が落ちる(2→4回)",
           "実測%d回= 組がばたつくたびに毎時撃つ" % len(sent))
        red += 1 if len(sent) == 4 else 0

    # 変異②= 旧stateからの移行を捨てる(記憶が無ければ空から始める)。動きはする。
    total += 1
    m = mutant(WATCH, "mut_nomigrate",
               '        prev_pairs = ndc.seed_pairs(st.get("drift") or "", today)',
               "        prev_pairs = {}")
    if m is None:
        ok(False, "変異②の変異点が見つからない(検査が古い)")
    else:
        nm = load(NDC, "ndc_m2")
        old = {"material": "むかしの版", "drift": nm.sig(nm.scan(_rows_of(nm, tmp, L_AB))),
               "last": "sent"}
        sent, _ = replay(m, nm, tmp, "m2", [L_AB], state0=old)
        ok(len(sent) == 1, "変異②(移行を捨てる)= [6a]が落ちる(0→1回・既報が全部初出になる)",
           "実測%d回" % len(sent))
        red += 1 if len(sent) == 1 else 0

    # 変異③= 禁止後の再発への切り替わりを鳴らさない(初出だけ見る)。動きはする。
    total += 1
    m = mutant(NDC, "mut_norebanned",
               "            rebanned.append(k)", "            pass")
    if m is None:
        ok(False, "変異③の変異点が見つからない(検査が古い)")
    else:
        d = m.diff_pairs(m.diff_pairs({}, [A], "2026-09-08")["pairs"],
                         [A_BANNED], "2026-09-08")
        ok(not d["rebanned"], "変異③(再発を鳴らさない)= [1g]が落ちる(節目が黙って通る)")
        red += 1 if not d["rebanned"] else 0

    # 変異④= 記憶を忘れない(TTLを外す)。動きはする=より静かにさえなる。
    total += 1
    m = mutant(NDC, "mut_neverforget",
               '        if _age_days(v.get("last"), day) <= ttl_days:',
               "        if True:")
    if m is None:
        ok(False, "変異④の変異点が見つからない(検査が古い)")
    else:
        d = m.diff_pairs({"一ノ瀬怜>一ノ瀬": {"last": "2026-08-24", "banned": False}},
                         [A], "2026-09-08")
        ok(not d["fresh"], "変異④(忘れない)= [2c]が落ちる(一度鳴った組は二度と鳴らない)")
        red += 1 if not d["fresh"] else 0

    # 変異⑤= 読めない日付を「新しい」へ倒す(覚えている側=より静か)。動きはする。
    total += 1
    m = mutant(NDC, "mut_failclosed", "        return ttl_infinite()", "        return 0")
    if m is None:
        ok(False, "変異⑤の変異点が見つからない(検査が古い)")
    else:
        d = m.diff_pairs({"一ノ瀬怜>一ノ瀬": {"last": "きのう", "banned": False}},
                         [A], "2026-09-08")
        ok(not d["fresh"], "変異⑤(壊れた記憶を信じる)= [2d]が落ちる(沈黙の事故へ倒れる)")
        red += 1 if not d["fresh"] else 0

    # 変異⑥= 便を畳まない(全数を毎回展開する=発注前の形)。動きはする。
    total += 1
    m = mutant(WATCH, "mut_nofold", "        if key and ndc.pair_key(d) not in key:",
               "        if False:")
    if m is None:
        ok(False, "変異⑥の変異点が見つからない(検査が古い)")
    else:
        body = m.build_drift_body(n, [A, B, C], [], None, None,
                                  {"fresh": ["シャビ・アロンソ>シャビ"], "rebanned": [],
                                   "pairs": {}})
        ok(body.count("使っている人格=") == 3, "変異⑥(畳まない)= [4a]が落ちる(1→3組を展開)",
           "実測%d" % body.count("使っている人格="))
        red += 1 if body.count("使っている人格=") == 3 else 0

    print("  変異 %d件中%d件が狙いどおり赤" % (total, red))
    if red != total:
        FAIL.append("must-fail(変異が赤にならない)")


if __name__ == "__main__":
    only_mut = "--mutate" in sys.argv
    tmp = tempfile.mkdtemp(prefix="ndc_cadence_")
    try:
        ndc = load(NDC, "ndc_real")
        if not only_mut:
            t1(ndc)
            t1b(ndc)
            t2(ndc)
            t3(ndc)
            t4(ndc)
            t5(load(NDC, "ndc_t5"), tmp)
            t6(load(NDC, "ndc_t6"), tmp)
            t7(load(NDC, "ndc_t7"), tmp)
        must_fail(ndc, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n結果: %s (失敗 %d件)" % ("PASS" if not FAIL else "FAIL", len(FAIL)))
    for f in FAIL:
        print("  - " + f)
    sys.exit(1 if FAIL else 0)
