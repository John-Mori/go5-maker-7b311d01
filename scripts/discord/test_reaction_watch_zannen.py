# -*- coding: utf-8 -*-
"""残念スタンプ `Zannen` の配線が本当に効いているかの検査(2026-09-20 イージス研究室)。

発注= 改善提案部門『型_残念スタンプ集計_2026-09-20.md』§3 の受け入れ条件4点。配線はC-015でこちら。
  1. 残念が付いた実投稿を巡回が kind="zannen" として拾える(must-pass)
  2. watch_conflicts が鳴らない
  3. must-fail: WATCH行を消すと拾えなくなる(=拾えているのが配線由来だと実証)
  4. 炎上/改悪/再発の既存集計が1件も動かない(回帰)

★偽物にするのは**外へ出る手だけ**(検査の作法 SKILL: test-must-fail)。
  差し替える= Discord API(Api) / トークン / 部屋一覧 / 投函(send) / 書き込み先のパス / session_relay。
  **本物のまま通す**= watched() の照合 / collect() の絞り込み / group_by_kind() の並び /
  dept_body() の本文組み立て / stack_open_defects() の DEFECT_KINDS 絞り込みとソート /
  log_zannen() の冪等。=「拾えた」は実行の結果であって、ソースの文字列一致ではない。

  python scripts/discord/test_reaction_watch_zannen.py
  python scripts/discord/test_reaction_watch_zannen.py --mutant watch        # WATCH行を消す(must-fail)
  python scripts/discord/test_reaction_watch_zannen.py --mutant kindorder    # 便から落ちる誤実装
  python scripts/discord/test_reaction_watch_zannen.py --mutant defectkinds  # 不具合台帳を汚す誤実装
  ★--mutant は「動く別の実装」へ変えて**同じ検査**を流す(C-053)。赤(rc=1)になるのが正しい。
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import reaction_watch as rw                      # noqa: E402

_fails = []
_ran = []

CHAMI = {"id": "490925528367497227", "username": "chami_fusoh", "bot": False}
CID = "1234567890123456789"
GUILD = "1111111111111111111"
ZAN_MSG = "1551200000000000001"
ZAN_TEXT = "残念の実物。頼まれたのは台帳の読み替えなのに、新しい台帳を作って返した投稿。"

# ★本番の面(汚さないことを前後の (mtime, size) で確かめる)。★patchより先に控える
PROD = {
    "reaction_seen.jsonl": rw.LEDGER,
    "open_defects.jsonl": os.path.join(rw.LOCAL, "llm", "open_defects.jsonl"),
    "kaizen_repair_analysis.jsonl": rw.ZANNEN_STORE,
    "reaction_watch_kaizen_digest.md": rw.KAIZEN_DIGEST,
}

# 既存の日次タリー行(daily_repair_analysis.py が書く形。`kind` を持たない)= 1バイトも触らせない
TALLY = [
    {"ts": "2026-09-18T08:10:00+09:00", "window_h": 24, "dept": "aegis-gl", "total": 3,
     "by_cluster": {}, "top": [], "bad_lines": 0},
    {"ts": "2026-09-19T08:10:00+09:00", "window_h": 24, "dept": "hq", "total": 1,
     "by_cluster": {}, "top": [], "bad_lines": 0},
]


def ok(cond, name):
    print(("  OK  " if cond else "  NG  ") + name)
    _ran.append(name)
    if not cond:
        _fails.append(name)


def snapshot(paths):
    out = {}
    for k, p in paths.items():
        out[k] = (os.path.getmtime(p), os.path.getsize(p)) if os.path.exists(p) else None
    return out


# ---------------------------------------------------------------- 偽物(外へ出る手だけ)

def msg(mid, emoji, text, ts="2026-09-20T09:00:00.000000+00:00"):
    return {"id": mid, "content": text, "timestamp": ts,
            "author": {"username": "デブライネ", "id": "900"},
            "reactions": [{"emoji": emoji, "count": 1}]}


def messages():
    """入力= 残念1・再発1・改悪1・炎上1・対象外(❤️)1。全部Chamiが押した形。"""
    return [
        msg(ZAN_MSG, {"id": "1551163699656532078", "name": "Zannen"}, ZAN_TEXT),
        msg("1551200000000000002", {"id": "1531748428827201772", "name": "saihatsu"},
            "再発の実物。同じ穴にもう一度落ちた投稿。"),
        msg("1551200000000000003", {"id": "1541110670748156014", "name": "kaiaku"},
            "改悪の実物。前は動いていた道を塞いだ投稿。"),
        msg("1551200000000000004", {"id": "1541126866981752883", "name": "enjoh"},
            "炎上の実物。恒久対策まで行けと言われた投稿。"),
        msg("1551200000000000005", {"id": None, "name": "❤️"},
            "対象外の実物。許可制なので拾ってはいけない投稿。"),
    ]


class FakeApi:
    """Discordの返しだけを差し替える。判定(watched/humans絞り)は本物が実行する。"""

    def __init__(self, token):
        self.calls = 0
        self.rate_limited = 0
        self.errors = []
        self.reaction_paths = []

    def get(self, path):
        self.calls += 1
        if "/reactions/" in path:
            self.reaction_paths.append(path)
            return [CHAMI]
        if "/messages?" in path:
            return messages() if "after=" in path else []
        return {"guild_id": GUILD}          # /channels/{cid}


class RelayStub(types.ModuleType):
    """session_relay の**外へ出る手**(open_defects への追記)だけを止める。"""

    DEFECT_KIND_DEFECT = "defect"

    def __init__(self):
        types.ModuleType.__init__(self, "session_relay")
        self.stacked = []

    def open_defect(self, dept="", symptom="", broken="", noticed_at="", source="", kind=""):
        self.stacked.append({"dept": dept, "symptom": symptom, "broken": broken,
                             "source": source, "kind": kind})
        return ("DEF-%s-%04d" % (dept, len(self.stacked)), True)

    def mark_defect_enjo(self, dept, did, where=""):
        return False


# ---------------------------------------------------------------- 1巡回を本物のまま走らせる

def run_cycle(seed_tally=True, argv=None):
    """main() を**本物のまま**実走させ、(rc, 標準出力, 投函一式, 一時パス一式) を返す。"""
    tmp = tempfile.mkdtemp(prefix="zannen_")
    paths = {"ledger": os.path.join(tmp, "reaction_seen.jsonl"),
             "store": os.path.join(tmp, "kaizen_repair_analysis.jsonl"),
             "digest": os.path.join(tmp, "digest.md"),
             "chlog": os.path.join(tmp, "change_log.jsonl")}
    if seed_tally:
        with io.open(paths["store"], "w", encoding="utf-8") as f:
            for r in TALLY:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    io.open(paths["chlog"], "w", encoding="utf-8").close()

    relay = RelayStub()
    sys.modules["session_relay"] = relay          # ★import より先に差し込む
    sends = []

    keep = {k: getattr(rw, k) for k in
            ("Api", "read_token", "load_channels", "send", "LEDGER", "ZANNEN_STORE",
             "KAIZEN_DIGEST", "CHANGE_LOG", "_changelog_cache")}
    argv_keep, sleep_keep = sys.argv, rw.time.sleep
    try:
        rw.Api = FakeApi
        rw.read_token = lambda: "dummy-token"
        rw.load_channels = lambda: ([{"id": CID, "name": "イージス研究室",
                                      "dept": "aegis-gl"}], "検査(合成)")
        rw.send = lambda dept, body, dry_run, sender=None, tag="": (
            sends.append({"dept": dept, "body": body, "sender": sender, "tag": tag}), True)[1]
        rw.LEDGER = paths["ledger"]
        rw.ZANNEN_STORE = paths["store"]
        rw.KAIZEN_DIGEST = paths["digest"]
        rw.CHANGE_LOG = paths["chlog"]
        rw._changelog_cache = None
        rw.time.sleep = lambda *_a, **_k: None    # ★待ちだけ抜く(判定は1つも飛ばさない)
        sys.argv = argv or ["reaction_watch.py", "--hours", "24"]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = rw.main()
        return rc, buf.getvalue(), sends, paths, relay
    finally:
        for k, v in keep.items():
            setattr(rw, k, v)
        sys.argv, rw.time.sleep = argv_keep, sleep_keep
        sys.modules.pop("session_relay", None)


def store_rows(path):
    rows = []
    if os.path.exists(path):
        for line in io.open(path, encoding="utf-8"):
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def drop_zannen_from_watch():
    """★must-fail用の変異= 「動く別の実装」(残念を足す前の版)へ戻す。"""
    rw.WATCH = [w for w in rw.WATCH if w["id"] != "1551163699656532078"]
    rw.WATCH_BY_ID = {w["id"]: w for w in rw.WATCH if w["id"]}
    rw.WATCH_BY_CHAR = {w["name"]: w for w in rw.WATCH if not w["id"]}


# ---------------------------------------------------------------- 検査本体

def run():
    before = snapshot(PROD)

    # --- A 表の形(受け入れ条件2と、他kindを動かしていないことの静的な裏取り) -------------
    hit = rw.watched({"id": "1551163699656532078", "name": "Zannen"})
    ok(hit is not None and hit["kind"] == "zannen" and hit["label"] == "残念",
       "A-1 Zannen のIDで kind=zannen を引ける(照合はIDが主)")
    ok(rw.watched({"id": "1551163699656532078", "name": "改名後の別名"}) is not None,
       "A-2 名前が変わってもIDで拾える(WATCHの照合規約を壊していない)")
    ok(rw.KIND_ORDER == ["enjo", "kaiaku", "saihatsu", "zannen", "golazo", "ai"],
       "A-3 KIND_ORDER= 再発の後・ゴラッソの前(型 §2-2 の指定どおり)")
    ok(rw.DEFECT_KINDS == ("saihatsu", "enjo", "kaiaku"),
       "A-4 ★DEFECT_KINDS は不変(型 §2-5= 残念は恒久対策ゲートへ入れない)")
    ok(rw.REALTIME_KINDS == ("kaiaku",),
       "A-5 ★REALTIME_KINDS は不変(型 §2-6= 残念で夜中に部屋を起こさない)")
    ok(all("zannen" in t for t in (rw.ORDERS, rw.HEADING, rw.KAIZEN_SECTION)),
       "A-6 ORDERS / HEADING / KAIZEN_SECTION の3つとも zannen を持つ(欠けると KeyError で巡回が死ぬ)")
    # ★受け入れ条件2の実測(2026-09-20)= watch_conflicts は**既に** ['saihatsu','kaiaku'] を返す。
    #   react.py の ALIAS へ再発/改悪が機械印として入った 2026-09-04 からの既存の鳴り方で、
    #   残念の追加とは無関係(main() は警告だけ出して巡回を止めない=2026-09-09の判断)。
    #   よってここで見るのは「**Zannen が新しい衝突を増やしていないか**」だ。
    marks = rw.machine_marks()
    ok("Zannen" not in marks and "Zannen" not in rw.watch_conflicts(marks),
       "A-7 受け入れ条件2= Zannen は機械の印と衝突しない(実測の既存衝突= %s)"
       % (rw.watch_conflicts(marks) or "なし"))

    # --- B must-pass(入力を差し替えた実走で1本通す= 受け入れ条件1) ---------------------
    rc, out, sends, paths, relay = run_cycle()
    ok(rc == 0, "B-1 巡回が最後まで通る(rc=%s)" % rc)
    ok(len(sends) == 1 and sends[0]["dept"] == "aegis-gl",
       "B-2 部屋へ1本だけ組み上がる(実測 %d本)" % len(sends))
    body = sends[0]["body"] if sends else ""
    ok("残念" in body and "Zannen" in body,
       "B-3 ★便の本文に残念が出る(group_by_kind→dept_body を本物で通した結果)")
    ok("汲み取りの甘さ" in body,
       "B-4 本文が『後退でも再依頼でもない汲み取りの甘さ』と言い分けている")
    ok(ZAN_TEXT[:12] in body, "B-5 押された投稿の原文が本文に載る")
    for label in ("炎上", "改悪", "再発"):
        ok(label in body, "B-6 既存の %s も同じ便に残っている(回帰)" % label)
    ok("対象外の実物" not in body,
       "B-7 ❤️(WATCHに無い)は拾わない= 許可制が生きている")

    rows = store_rows(paths["store"])
    zrows = [r for r in rows if r.get("kind") == "zannen"]
    ok(len(rows) == len(TALLY) + 1 and len(zrows) == 1,
       "B-8 受け入れ条件1= 週次が読む面へ kind=zannen が1行だけ増える(実測 %d行)" % len(zrows))
    z = zrows[0] if zrows else {}
    ok(z.get("msg_id") == ZAN_MSG and ZAN_TEXT[:12] in (z.get("excerpt") or ""),
       "B-9 その行に msg_id と引用要旨が残る(後から何を汲み違えたか分類できる)")
    ok(z.get("dept") == "aegis-gl" and GUILD in (z.get("url") or ""),
       "B-10 部屋とジャンプリンクが残る(元投稿へ辿れる)")
    ok([json.dumps(r, ensure_ascii=False) for r in rows[:len(TALLY)]]
       == [json.dumps(r, ensure_ascii=False) for r in TALLY],
       "B-11 ★既存の日次タリー行は1バイトも動かない(相乗りであって書き換えではない)")
    ok("残念スタンプ 1件 → 新しく書いた 1件 / 既にあった 0件" in out,
       "B-12 巡回の出力が件数を数字で言う")

    # 回帰= 不具合台帳(世代をまたぐ器)の中身
    kinds = sorted(r["source"] for r in relay.stacked)
    ok(len(relay.stacked) == 3,
       "B-13 ★不具合台帳へ積まれたのは炎上/改悪/再発の3件だけ(実測 %d件)" % len(relay.stacked))
    ok(not any(ZAN_MSG in (r["broken"] or "") for r in relay.stacked),
       "B-14 ★★残念は open_defects へ1件も積まれない(型 §2-5・薄い信号で台帳を濁さない)")
    ok(len(set(kinds)) == 3,
       "B-15 積まれた3件の source が種類ごとに分かれている(混ぜて数えていない)")
    ok(relay.stacked[0]["source"] == rw.DEFECT_SOURCE_ENJO,
       "B-16 重い順(炎上が先)のソートが生きている= 残念の追加が並びを壊していない")

    # 冪等(投函が失敗して次回まるごと拾い直しても増えない)
    items = [{"kind": "zannen", "msg_id": ZAN_MSG, "dept": "aegis-gl", "channel": "x",
              "channel_id": CID, "posted_at": "", "detected_at": "2026-09-20T09:00:00",
              "content": ZAN_TEXT}]
    a1, d1, w1 = rw.log_zannen(items, GUILD, False, path=paths["store"])
    ok((a1, d1, w1) == (0, 1, ""),
       "B-17 同じ msg_id は二度書かない(実測 added=%d dup=%d)" % (a1, d1))
    ok(rw.log_zannen(items, GUILD, True, path=paths["store"])[2].startswith("dry-run"),
       "B-18 dry-run は記録先を汚さない")

    # --- C must-fail(受け入れ条件3= 拾えているのが WATCH 行のおかげだと実証) ------------
    keep = (rw.WATCH, rw.WATCH_BY_ID, rw.WATCH_BY_CHAR)
    try:
        drop_zannen_from_watch()
        rc2, out2, sends2, paths2, relay2 = run_cycle()
        body2 = sends2[0]["body"] if sends2 else ""
        ok("Zannen" not in body2 and "残念" not in body2,
           "C-1 ★WATCH行を消すと残念は便から消える(拾えているのは配線由来)")
        ok([r for r in store_rows(paths2["store"]) if r.get("kind") == "zannen"] == [],
           "C-2 ★WATCH行を消すと週次の面にも1行も出ない")
        ok(len(relay2.stacked) == 3 and "改悪" in body2 and "再発" in body2,
           "C-3 その時も既存3種は変わらず動く(残念だけが消える)")
    finally:
        rw.WATCH, rw.WATCH_BY_ID, rw.WATCH_BY_CHAR = keep

    # --- D 本番の面を1バイトも触っていない -------------------------------------------------
    after = snapshot(PROD)
    for k in PROD:
        ok(before[k] == after[k], "D-1 本番の %s を触っていない" % k)
    return not _fails


# ---------------------------------------------------------------- 変異体(C-053)

MUTANTS = {
    "watch": ("WATCH から Zannen 行を落とす(残念を足す前の版)", drop_zannen_from_watch),
    "kindorder": ("KIND_ORDER から zannen を落とす(拾うが便に出ない)",
                  lambda: rw.__setattr__("KIND_ORDER",
                                         [k for k in rw.KIND_ORDER if k != "zannen"])),
    "defectkinds": ("DEFECT_KINDS へ zannen を足す(不具合台帳を薄い信号で汚す)",
                    lambda: rw.__setattr__("DEFECT_KINDS",
                                           tuple(rw.DEFECT_KINDS) + ("zannen",))),
}


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--mutant" in sys.argv:
        name = sys.argv[sys.argv.index("--mutant") + 1]
        why, apply = MUTANTS[name]
        print("★変異体 %s= %s。この検査は赤(rc=1)になるのが正しい。\n" % (name, why))
        apply()
    good = run()
    print(("PASS 残念スタンプ `Zannen` の配線 %d/%d" % (len(_ran) - len(_fails), len(_ran)))
          if good else ("FAIL %d件: %s" % (len(_fails), " / ".join(_fails))))
    sys.exit(0 if good else 1)
