# -*- coding: utf-8 -*-
"""
test_persona_queue_poller.py — ポーラーを**実行で**通す(§3)。

偽物にするのは外へ出る手だけ= wrangler(r2_get)と ingest の起動。
判定・分岐(済み判定・未知の人格の保留・壊れた行・カーソル前進・戻り値)は本物のまま走らせる。

走らせ方: python scripts/_daemons/test_persona_queue_poller.py
"""
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
BASE = "https://go5-sync.trustsignalbot.workers.dev/img/"
KEY_A = "a" * 64
KEY_B = "b" * 64


def load():
    spec = importlib.util.spec_from_file_location(
        "pqp", os.path.join(HERE, "persona_queue_poller.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Fake:
    """wrangler と ingest の代わり。R2 は dict、ingest は呼ばれた回数だけ数える。"""

    def __init__(self, m, r2, ledger, rc=0):
        self.m, self.r2, self.rc = m, r2, rc
        self.ingest = 0
        self.tmp = tempfile.mkdtemp(prefix="pqp_")
        m.LOCAL = self.tmp
        m.INBOX = os.path.join(self.tmp, "persona_inbox")
        m.SOURCES = os.path.join(self.tmp, "persona_avatar_sources")
        m.CURSOR = os.path.join(self.tmp, "persona_queue_cursor.json")
        m.LOG = os.path.join(self.tmp, "llm", "poller.jsonl")
        m.AVATARS = os.path.join(self.tmp, "persona_avatars.json")
        io.open(m.AVATARS, "w", encoding="utf-8").write(
            json.dumps(ledger, ensure_ascii=False))
        m.r2_get = self._get

        outer = self

        class _SP:  # ingest の起動だけ偽物にする(戻り値は本物と同じ形)
            @staticmethod
            def run(cmd, **kw):
                outer.ingest += 1
                return type("R", (), {"returncode": outer.rc})()
        m.subprocess = _SP

    def _get(self, key, dest):
        if key not in self.r2:
            return False
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        v = self.r2[key]
        io.open(dest, "wb").write(v if isinstance(v, bytes) else v.encode("utf-8"))
        return True

    def cursor(self):
        return json.load(io.open(self.m.CURSOR, encoding="utf-8"))

    def placed(self):
        out = []
        for dp, _, fns in os.walk(self.m.INBOX):
            for fn in fns:
                out.append(os.path.relpath(os.path.join(dp, fn), self.m.INBOX).replace("\\", "/"))
        return sorted(out)

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def q(*recs):
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs)


PASS = FAIL = 0


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        print("  FAIL %s\n    got : %r\n    want: %r" % (name, got, want))


def run(fake, argv=()):
    old = sys.argv
    sys.argv = ["poller"] + list(argv)
    try:
        return fake.m.main()
    finally:
        sys.argv = old


def main():
    # 1) 申告キューがまだ無い= 何もせず 0(fail-open。カーソルも作らない)
    f = Fake(load(), {}, {"アメス": []})
    check("キュー未作成→0/カーソル無し", [run(f), os.path.exists(f.m.CURSOR)], [0, False])
    f.close()

    # 2) 新着1件(既知の人格)= 投函口へ置き、ingest を1回だけ呼び、カーソルが1へ進む
    f = Fake(load(), {
        "persona/queue.jsonl": q({"persona": "アメス", "key": KEY_A, "ct": "image/png"}),
        KEY_A: b"\x89PNG",
    }, {"アメス": []})
    rc = run(f)
    check("新着1件→置く/ingest1回/カーソル1",
          [rc, f.placed(), f.ingest, f.cursor()["line"], f.cursor()["pending"]],
          [0, ["アメス/" + KEY_A[:12] + ".png"], 1, 1, []])

    # 3) 同じ状態でもう1周= 新着なし・ingest を呼ばない(空回しで台帳を触らない)
    before = f.ingest
    rc = run(f)
    check("2周目→ingest呼ばない", [rc, f.ingest - before, f.cursor()["line"]], [0, 0, 1])
    f.close()

    # 4) 台帳に既に同じURLが在る= 済み扱い。落とさず ingest も呼ばない。カーソルは進む
    f = Fake(load(), {
        "persona/queue.jsonl": q({"persona": "アメス", "key": KEY_A}),
        KEY_A: b"\x89PNG",
    }, {"アメス": [BASE + KEY_A]})
    rc = run(f)
    check("台帳に既在→何もせずカーソルだけ進む",
          [rc, f.placed(), f.ingest, f.cursor()["line"]], [0, [], 0, 1])
    f.close()

    # 5) 未知の人格= 捨てない・止めない。pending へ残し、カーソルは進める
    f = Fake(load(), {
        "persona/queue.jsonl": q({"persona": "誰それ", "key": KEY_A}),
        KEY_A: b"\x89PNG",
    }, {"アメス": []})
    rc = run(f)
    cur = f.cursor()
    check("未知の人格→保留(行は消えない)",
          [rc, f.placed(), f.ingest, cur["line"], [p["persona"] for p in cur["pending"]]],
          [0, [], 0, 1, ["誰それ"]])

    # 6) 台帳へその人格が足されたら、次の周回で pending から自然に流れる
    led = json.load(io.open(f.m.AVATARS, encoding="utf-8"))
    led["誰それ"] = []
    io.open(f.m.AVATARS, "w", encoding="utf-8").write(json.dumps(led, ensure_ascii=False))
    rc = run(f)
    check("台帳へ追加後→保留が流れる",
          [rc, f.placed(), f.ingest, f.cursor()["pending"]],
          [0, ["誰それ/" + KEY_A[:12] + ".png"], 1, []])
    f.close()

    # 7) 壊れた行が混ざっても、後続の正常な行は処理される(1行で全体を止めない)
    f = Fake(load(), {
        "persona/queue.jsonl": '{壊れてる\n' + q({"persona": "アメス", "key": KEY_B, "ct": "image/jpeg"}),
        KEY_B: b"\xff\xd8",
    }, {"アメス": []})
    rc = run(f)
    check("壊れた行→飛ばして後続を処理(拡張子もctから)",
          [rc, f.placed(), f.ingest, f.cursor()["line"]],
          [0, ["アメス/" + KEY_B[:12] + ".jpg"], 1, 2])
    f.close()

    # 8) 実体が R2 から取れない= 保留(黙って捨てない)。ingest は呼ばない
    f = Fake(load(), {
        "persona/queue.jsonl": q({"persona": "アメス", "key": KEY_A}),
    }, {"アメス": []})
    rc = run(f)
    cur = f.cursor()
    check("実体が取れない→保留",
          [rc, f.placed(), f.ingest, [p["key"] for p in cur["pending"]]], [0, [], 0, [KEY_A]])
    f.close()

    # 9) ingest が失敗したら戻り値 1(緑で握り潰さない)
    f = Fake(load(), {
        "persona/queue.jsonl": q({"persona": "アメス", "key": KEY_A}),
        KEY_A: b"\x89PNG",
    }, {"アメス": []}, rc=3)
    check("ingest失敗→戻り値1", run(f), 1)
    f.close()

    # 10) --dry-run= 何も置かず ingest も呼ばず、カーソルも書かない
    f = Fake(load(), {
        "persona/queue.jsonl": q({"persona": "アメス", "key": KEY_A}),
        KEY_A: b"\x89PNG",
    }, {"アメス": []})
    rc = run(f, ["--dry-run"])
    check("dry-run→無傷", [rc, f.placed(), f.ingest, os.path.exists(f.m.CURSOR)],
          [0, [], 0, False])
    f.close()

    # 11) 元画像と編集レシピを完成画像とは別に保管する
    edit = {"version": 1, "rot": 0, "crop": {"x": 10, "y": 20, "size": 300},
            "source": {"width": 900, "height": 1200}, "outputSize": 512}
    f = Fake(load(), {
        "persona/queue.jsonl": q({"persona": "アメス", "key": KEY_A, "ct": "image/png",
                                   "sourceKey": KEY_B, "sourceCt": "image/jpeg", "edit": edit}),
        KEY_A: b"\x89PNG", KEY_B: b"\xff\xd8original",
    }, {"アメス": []})
    rc = run(f)
    src = os.path.join(f.m.SOURCES, "アメス", KEY_B + ".jpg")
    meta = os.path.join(f.m.SOURCES, "アメス", KEY_A + ".json")
    meta_obj = json.load(io.open(meta, encoding="utf-8")) if os.path.exists(meta) else {}
    check("元画像と編集レシピを別保管",
          [rc, os.path.isfile(src), meta_obj.get("sourceKey"), (meta_obj.get("edit") or {}).get("crop", {}).get("size")],
          [0, True, KEY_B, 300])
    f.close()

    print("\n%d PASS / %d FAIL" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
