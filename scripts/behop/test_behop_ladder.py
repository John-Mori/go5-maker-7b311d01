# -*- coding: utf-8 -*-
"""べホップの降格ラダーと --ping の検査 (2026-08-18 イージス研究室・研究室HQ依頼の恒久対策)。

なぜ在るか= 2026-08-17、ベホップが「生成失敗」で止まった。実測の道筋は
  gemini-2.5-pro=404 → gemini-flash-latest=503 → **中断**。下に生きている
  gemini-flash-lite-latest(200) へ降りずに終わっていた。しかも **--ping は緑のまま**だった
  (pingがListModelsしか叩かず、generateContent を一度も通していなかったため)。

★この検査の作り (共通規律§3):
  ソースの文字列一致では検査にならない=**外へ出る手 (_gen_once / list_models / Discord) だけ偽物**にし、
  **判定と分岐 (ラダーの構築・降格・終了コード) は本物のまま**実行で通す。
  「今その状態が無いから試せない」ものは、**その状態を作って渡す** (404/503/429を返す偽の_gen_once)。

★本番の記録を汚さない= import の前に GO5_LOCAL_DIR を一時フォルダへ向ける
  (gemini_usage は import 時に書き込み先を決めるため、この順序でないと本番の
   local/llm/gemini_usage.jsonl へ検査の行が混ざる)。

走らせ方= python scripts/behop/test_behop_ladder.py
"""
import contextlib
import io
import os
import sys
import tempfile
import urllib.error

os.environ["GO5_LOCAL_DIR"] = tempfile.mkdtemp(prefix="behop_test_")   # ★import より前
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import behop  # noqa: E402

_ok = 0
_ng = 0


def chk(label, cond):
    global _ok, _ng
    if cond:
        _ok += 1
        print("  PASS", label)
    else:
        _ng += 1
        print("  FAIL", label)


def gemini_usage_rows():
    import gemini_usage
    return gemini_usage.read_all()


def http(code):
    return urllib.error.HTTPError("http://x", code, "e", {}, None)


def fake_gen(codes):
    """モデル名→(例外 or 返す文字列) の台本を持つ偽の _gen_once。叩かれた順も記録する。"""
    calls = []

    def _f(key, model, payload):
        calls.append(model)
        v = codes.get(model, http(404))
        if isinstance(v, Exception):
            raise v
        return v
    return _f, calls


# ★2026-08-18 に本番キーの ListModels が実際に返した37種から採った一覧 (作り話ではない)。
# 画像/音声/別製品/gemma が混ざっているのが実態で、そこが梯子を汚していた。
AVAIL = ["gemini-2.5-pro", "gemini-pro-latest", "gemini-flash-latest", "gemini-2.5-flash",
         "gemini-flash-lite-latest", "gemini-2.5-flash-lite", "gemini-3.7-flash",
         "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.1-pro-preview",
         "gemini-3-pro-image", "gemini-3.1-flash-image-preview", "nano-banana-pro-preview",
         "gemini-2.5-flash-preview-tts", "lyria-3-pro-preview", "deep-research-pro-preview-12-2025",
         "antigravity-preview-05-2026", "gemini-robotics-er-2-preview", "gemma-4-31b-it",
         "gemini-2.5-computer-use-preview-10-2025"]


def main():
    behop.time.sleep = lambda *_a, **_k: None      # 検査で1.5秒×段数を待たない

    print("== ①序列: 名前から強さを読む ==")
    chk("pro > flash > flash-lite", behop.model_tier("gemini-2.5-pro") == 3
        and behop.model_tier("gemini-flash-latest") == 2
        and behop.model_tier("gemini-flash-lite-latest") == 1)
    chk("latestは同階層で番号付きより先",
        behop.model_score("gemini-pro-latest") > behop.model_score("gemini-2.5-pro"))
    chk("previewは同階層で安定版より後",
        behop.model_score("gemini-2.5-pro-preview-06-05") < behop.model_score("gemini-2.5-pro"))
    chk("★未知の新世代も名前だけで上位に来る(世代交代に追随)",
        behop.model_score("gemini-4-pro-latest") > behop.model_score("gemini-2.5-pro"))
    chk("読めない名前も捨てない(tier=0で残る)", behop.model_tier("nanika-999") == 0)
    chk("★日付を世代番号と読まない(12-2025の12を掴まない)",
        behop.model_gen("deep-research-pro-preview-12-2025") == 0.0)
    chk("世代番号は正しく読む(3.7 / 2.5)",
        behop.model_gen("gemini-3.7-flash") == 3.7 and behop.model_gen("gemini-2.5-pro") == 2.5)

    print("== ②テキストを返さないモデルを外す ==")
    for bad in ("gemini-3-pro-image", "nano-banana-pro-preview", "gemini-2.5-flash-preview-tts",
                "lyria-3-pro-preview", "deep-research-pro-preview-12-2025",
                "gemini-robotics-er-2-preview", "gemma-4-31b-it",
                "gemini-2.5-computer-use-preview-10-2025", "antigravity-preview-05-2026"):
        chk("梯子に入れない: %s" % bad, not behop.is_text_model(bad))
    for good in ("gemini-2.5-pro", "gemini-pro-latest", "gemini-3.7-flash", "gemini-flash-lite-latest"):
        chk("梯子に入れる: %s" % good, behop.is_text_model(good))

    print("== ③ラダー構築 ==")
    lad = behop.build_ladder(AVAIL)
    chk("先頭はproの段", behop.model_tier(lad[0]) == 3)
    chk("★先頭は latest エイリアス(世代交代をGoogle側が面倒みる段)", lad[0] == "gemini-pro-latest")
    chk("★末尾は必ず最軽量の段(下に降りきることを構造で保証)", behop.model_tier(lad[-1]) == 1)
    chk("★テキスト以外が1つも混ざらない", all(behop.is_text_model(m) for m in lad))
    chk("上限を超えない", len(lad) <= behop.LADDER_LIMIT)
    chk("重複しない", len(lad) == len(set(lad)))
    chk("★proだけで埋め尽くさずflashの段も通る", any(behop.model_tier(m) == 2 for m in lad))
    lad2 = behop.build_ladder(AVAIL, first="gemini-2.5-flash")
    chk("明示指定は先頭に来る", lad2[0] == "gemini-2.5-flash")
    chk("明示指定しても最軽量の段は末尾に残る", behop.model_tier(lad2[-1]) == 1)
    chk("★存在しない名前を固定で持たない(旧PREFERRED先頭2つが梯子に湧かない)",
        "gemini-3-pro-latest" not in lad and "gemini-3-pro" not in lad)
    chk("★未来のモデルは書き換えなしで先頭へ来る",
        behop.build_ladder(AVAIL + ["gemini-5-pro-latest"])[0] == "gemini-5-pro-latest")
    chk("★ListModelsが落ちて空でも梯子は空にならない(fail-open)",
        len(behop.build_ladder([])) >= 1)
    chk("非テキストしか無くても梯子は空にならない",
        len(behop.build_ladder(["nano-banana-pro-preview"])) >= 1)

    print("== ④降格: 8/17に実際に起きた並び (404→503→200) ==")
    orig = behop._gen_once
    try:
        f, calls = fake_gen({"gemini-2.5-pro": http(404), "gemini-pro-latest": http(429),
                             "gemini-flash-latest": http(503), "gemini-2.5-flash": http(503),
                             "gemini-flash-lite-latest": "こんにちは"})
        behop._gen_once = f
        text, used = behop.ask("K", "gemini-2.5-pro", "しつもん", (), AVAIL)
        chk("★下に生きている段まで降りて生成が通る(8/17の再演)", text == "こんにちは")
        chk("使われたモデルを返す", used == "gemini-flash-lite-latest")
        chk("上の段を飛ばさず順に叩いている", calls[0] == "gemini-2.5-pro" and len(calls) >= 3)

        fe, _ = fake_gen({"gemini-2.5-pro": "   ", "gemini-flash-lite-latest": "本文"})
        behop._gen_once = fe
        te, ue = behop.ask("K", "gemini-2.5-pro", "q", (), AVAIL)
        chk("★空応答を成功扱いにせず次の段へ降りる", te == "本文" and ue == "gemini-flash-lite-latest")

        f2, calls2 = fake_gen({m: http(503) for m in AVAIL})
        behop._gen_once = f2
        text2, used2 = behop.ask("K", "gemini-2.5-pro", "しつもん", (), AVAIL)
        chk("全段ダメでも例外で落ちない", used2 is None and isinstance(text2, str))
        chk("★失敗文に全段の内訳が出る(最後の1つだけ見せない)",
            "gemini-flash-lite-latest=HTTP 503" in text2 and "gemini-2.5-pro=HTTP 503" in text2)

        f3, _ = fake_gen({"gemini-flash-lite-latest": "OK"})
        behop._gen_once = f3
        t3, u3 = behop.ask("K", "gemini-2.5-pro", "q", (), [])
        chk("availが空(ListModels死)でも最後の綱で通る", u3 == "gemini-flash-lite-latest" and t3 == "OK")

        print("== ⑤--ping: ListModelsが緑でも実生成がダメなら非0 ==")
        behop.list_models = lambda key: list(AVAIL)
        f4, _ = fake_gen({m: http(503) for m in AVAIL})
        behop._gen_once = f4
        chk("★本番経路が死んでいれば ping は緑にならない",
            behop.do_ping("K", check_bot=False) != 0)
        f5, _ = fake_gen({"gemini-flash-lite-latest": "OK"})
        behop._gen_once = f5
        chk("降格してでも1発通れば ping は0", behop.do_ping("K", check_bot=False) == 0)
        behop.list_models = lambda key: (_ for _ in ()).throw(RuntimeError("net"))
        chk("ListModelsが落ちてもpingは例外で死なず判定を返す",
            behop.do_ping("K", check_bot=False) in (0, 6))

        print("== ⑦model無指定(None)の見え方と戻り値の約束 ==")
        # ★研究室HQ指摘(2026-08-18)= 降格の注記に「None が割当超過」と出ていた。
        #   Noneは割当超過していない=指定が無かっただけ。ログを読む人が誤解する。
        f6, _ = fake_gen({"gemini-pro-latest": http(429), "gemini-flash-lite-latest": "本文"})
        behop._gen_once = f6
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            t6, u6 = behop.ask("K", None, "q", (), AVAIL)
        note = buf.getvalue()
        chk("★注記に None と出さない(モデル無指定でも実名で言う)", "None" not in note)
        chk("降格元は梯子の先頭の実名", "gemini-pro-latest" in note and u6 == "gemini-flash-lite-latest")
        chk("無指定でも生成は通る", t6 == "本文")

        f7, _ = fake_gen({m: http(503) for m in AVAIL})
        behop._gen_once = f7
        rows_before = len(gemini_usage_rows())
        t7, u7 = behop.ask("K", None, "q", (), AVAIL, tag="nonecheck")
        row = [r for r in gemini_usage_rows() if r.get("tag") == "nonecheck"][-1]
        chk("★失敗行のモデル名も None ではなく実名", row.get("model") == "gemini-pro-latest")
        chk("1呼び出しで1行だけ増える", len(gemini_usage_rows()) == rows_before + 1)
        # ★docstringに書いた約束を検査で固定する= 成否は text ではなく used(None)で見る。
        chk("★全段ダメなら used は None (textは空にならない)", u7 is None and bool(t7))

        # ★研究室HQが入れた止血の回帰止め= 成功しても降りてくる途中の内訳を err に残す。
        #   ここが空に戻ると「429は0件」という嘘の集計に逆戻りし、課金判断の軸が壊れる。
        f8, _ = fake_gen({"gemini-pro-latest": http(429), "gemini-flash-lite-latest": "OK"})
        behop._gen_once = f8
        behop.ask("K", None, "q", (), AVAIL, tag="trailcheck")
        row8 = [r for r in gemini_usage_rows() if r.get("tag") == "trailcheck"][-1]
        chk("★降格して成功した行にも429の内訳が残る(集計の軸を空にしない)",
            row8.get("ok") is True and "429" in (row8.get("err") or ""))
    finally:
        behop._gen_once = orig

    print("== ⑥使用量の記録を壊していない ==")
    import gemini_usage                                        # noqa: E402
    rows = gemini_usage.read_all()
    chk("1呼び出し1行が残っている", len(rows) >= 5)
    chk("成功行にモデル名が入る", any(r.get("ok") and r.get("model") for r in rows))
    chk("★pingはtagで見分けられる(用途を混ぜない)", any(r.get("tag") == "ping" for r in rows))
    chk("失敗行にも理由が残る", any((not r.get("ok")) and r.get("err") for r in rows))
    chk("★本番の記録先へ書いていない", "behop_test_" in gemini_usage.USAGE_FILE)

    # -----------------------------------------------------------------------
    print("== ⑧束(who)と用途(tag)の取り違えを止める (研究室HQ 2026-08-18) ==")
    # なぜ在るか= comp_frames は429でホイミンの私用キーへ切り替えて続行する。
    #   _usage が "behop" 固定だった間、その行は事業用として記録されていた=集計の「束」が嘘をつく。
    #   ★キーを跨ぐ場面こそ課金判断の主役なので、そこが嘘だと数字ごと無意味になる。
    orig2 = behop._gen_once
    try:
        behop._gen_once = lambda key, model, payload: "OK"
        for kname in ("ベホップ", "ホイミン", "しらない名前"):
            behop.ask_pro("K", "q", (), "gemini-flash-latest",
                          tag="whocheck", who=behop.bundle_of(kname))
        w = [r for r in gemini_usage.read_all() if r.get("tag") == "whocheck"]
        chk("★私用キーで叩いた行が homin として残る",
            [r.get("who") for r in w] == ["behop", "homin", "unknown"])
        chk("★知らないキー名を behop に混ぜない", len(w) == 3 and w[2].get("who") == "unknown")
        chk("ask_pro もtagで用途を分けられる", all(r.get("tag") == "whocheck" for r in w))
    finally:
        behop._gen_once = orig2

    # -----------------------------------------------------------------------
    # ★ここは元々ソースの文字列一致で見ていた (研究室HQ 2026-08-18 初版)。**あれは検査ではない。**
    #   実例= gemini_responder.py に 'ask(content, tag="room")' は在り検査は緑だったが、
    #   それはホイミンの行で、**ベホップの経路は同じファイルの別の行**で "cli" のまま漏れていた
    #   (イージス研究室が e1cc39e で発見)。緑の検査の下で穴が生きていた。
    #   → 呼び出し側を**実行で通す**。外へ出る手 (HTTP・GAS・yt-dlp・Discord) だけ偽物にし、
    #     キーの切り替えと引数の受け渡しは本物のまま回して、**実際に渡った値**を見る。
    _root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

    def drive_frames(modname):
        """comp_frames / target_frames を実際に main() まで走らせ、ask_pro に渡った引数を集める。
        ★1件目で429を返して**キーを跨がせる**= 束(who)の取り違えはこの瞬間にしか出ない。"""
        sys.path.insert(0, os.path.join(_root, "scripts"))
        sys.path.insert(0, os.path.join(_root, "scripts", "comp"))
        import importlib
        cf = importlib.import_module("comp_frames")
        mod = cf if modname == "comp_frames" else importlib.import_module("target_frames")

        tmp = tempfile.mkdtemp(prefix="drv_")
        os.makedirs(os.path.join(tmp, "local"), exist_ok=True)
        with open(os.path.join(tmp, "local", "gemini_api_key.txt"), "w", encoding="utf-8") as f:
            f.write("HOMINKEY")                       # ★ベホップのキーと別物にする=跨いだのが見える
        seen = []

        def fake_ask_pro(key, prompt, image_paths=(), model="", tag="", who=""):
            seen.append({"key": key, "tag": tag, "who": who})
            if len(seen) == 1:
                return None, "quota"                  # 1本目=無料枠が尽きた→次のキーへ
            return '{"frameText":"あ","panelDesc":"い"}', "ok"

        saved = {"ask_pro": behop.ask_pro, "read": behop._read, "lm": behop.list_models,
                 "get": cf.gas_get, "write": cf.gas_write, "grab": cf.grab_frame,
                 "yt": cf.have_ytdlp, "which": cf.shutil.which, "root": cf.ROOT,
                 "sleep": cf.time.sleep, "argv": sys.argv}
        try:
            behop.ask_pro = fake_ask_pro
            behop._read = lambda p, w: "BEHOPKEY"
            behop.list_models = lambda k: [cf.BASE_MODEL]
            cf.gas_get = lambda q, tries=3: {"ok": True, "count": 1,
                                             "pending": [{"videoId": "vid1", "durationSec": 5}]}
            cf.gas_write = lambda items, tries=3: {"ok": True, "written": len(items)}
            cf.grab_frame = lambda vid, dur, work: os.path.join(work, "f.png")
            cf.have_ytdlp = lambda: True
            cf.shutil.which = lambda x: "/usr/bin/" + x
            cf.ROOT = tmp
            cf.time.sleep = lambda s: None
            sys.argv = ["x", "--dry"] if modname == "comp_frames" else ["x", "--dry", "vid1"]
            mod.main()
        finally:
            behop.ask_pro, behop._read, behop.list_models = saved["ask_pro"], saved["read"], saved["lm"]
            cf.gas_get, cf.gas_write, cf.grab_frame = saved["get"], saved["write"], saved["grab"]
            cf.have_ytdlp, cf.shutil.which, cf.ROOT = saved["yt"], saved["which"], saved["root"]
            cf.time.sleep, sys.argv = saved["sleep"], saved["argv"]
        return seen

    for name, want_tag in (("comp_frames", "comp_frames"), ("target_frames", "target_frames")):
        got = drive_frames(name)
        chk(f"★{name}: 実行して2キーを跨ぐ (429→次キー)", len(got) == 2)
        chk(f"★{name}: 用途タグが実際に渡る (既定のask_proに落ちていない)",
            len(got) == 2 and all(g["tag"] == want_tag for g in got))
        chk(f"★{name}: 私用キーへ跨いだ行の束が homin になる",
            len(got) == 2 and got[0] == {"key": "BEHOPKEY", "tag": want_tag, "who": "behop"}
            and got[1] == {"key": "HOMINKEY", "tag": want_tag, "who": "homin"})

    # ホイミンの部屋応対= handle() を実行し、ask() に実際に渡った tag を見る (送信は偽物)
    sys.path.insert(0, os.path.join(_root, "scripts", "llm"))
    import importlib
    gr = importlib.import_module("gemini_responder")
    seen_room = []
    saved_gr = {"ask": gr.ask, "send": gr.send, "log": gr.log, "app": gr.append_line,
                "be": gr.behop_enabled}
    try:
        gr.ask = lambda q, model=None, system_extra="", tag="cli": seen_room.append(tag) or "はい"
        gr.send = lambda ch, t: True
        gr.log = lambda rec: None
        gr.append_line = lambda p, l: None
        gr.behop_enabled = lambda: False              # ベホップ経路は⑨で別に見ている
        gr.handle({"channel": "研究室hq", "content": "こんにちは"}, "{}")
    finally:
        gr.ask, gr.send, gr.log = saved_gr["ask"], saved_gr["send"], saved_gr["log"]
        gr.append_line, gr.behop_enabled = saved_gr["app"], saved_gr["be"]
    chk("★ホイミンの部屋応対が実際に tag=room で呼ばれる", seen_room == ["room"])

    print("== ⑨CLI経由の実務も用途で割れる (2026-08-18 イージス研究室) ==")
    # なぜ在るか= 研究室HQは ask_gemini 側 (ホイミンの応対) に tag="room" を通したが、
    #   **ベホップの部屋応対は behop.py を subprocess で叩く経路**で、CLIにtagの口が無く
    #   既定の "cli" のまま記録されていた= 手打ちの --ask と実務が同じ札に混ざる (②と同型)。
    # ★上の237-239行のような「ソースに文字列が在るか」では、口が実際に効くかは分からない。
    #   ここは main() を実行で通し、台帳に落ちた行を見る。
    orig3, orig_read, orig_lm, orig_argv = behop._gen_once, behop._read, behop.list_models, sys.argv
    try:
        behop._gen_once = lambda key, model, payload: "OK"
        behop._read = lambda *a, **k: "K"                      # 本物の鍵を読まない
        behop.list_models = lambda key: list(AVAIL)
        sys.argv = ["behop.py", "--ask", "q", "--tag", "room"]
        with contextlib.redirect_stdout(io.StringIO()):
            rc = behop.main()
        last = gemini_usage_rows()[-1]
        chk("★CLIに--tagの口が在り、台帳までtagが届く", rc == 0 and last.get("tag") == "room")
        sys.argv = ["behop.py", "--ask", "q"]
        with contextlib.redirect_stdout(io.StringIO()):
            behop.main()
        chk("--tag無しは既定のcli(手打ちの意味)のまま", gemini_usage_rows()[-1].get("tag") == "cli")
    finally:
        behop._gen_once, behop._read = orig3, orig_read
        behop.list_models, sys.argv = orig_lm, orig_argv

    sys.path.insert(0, os.path.join(_root, "scripts", "llm"))
    import subprocess as _sp                                    # noqa: E402
    import gemini_responder as _gr                              # noqa: E402
    seen = {}

    class _R:
        returncode = 0

    def _fake_run(argv, **kw):
        seen["argv"] = argv
        return _R()
    orig_run = _sp.run
    try:
        _gr.subprocess.run = _fake_run                          # 外へ出る手だけ偽物
        ok = _gr.behop_answer("イージス研究室", "こんにちは")
        av = seen.get("argv") or []
        chk("★ベホップの部屋応対が実際に--tag roomを渡す(実行で確認)",
            ok and "--tag" in av and av[av.index("--tag") + 1] == "room")
        chk("応対の中身と宛先は壊していない", "--ask" in av and "--to" in av)
    finally:
        _gr.subprocess.run = orig_run

    print("\n== %d/%d PASS ==" % (_ok, _ok + _ng))
    return 1 if _ng else 0


if __name__ == "__main__":
    sys.exit(main())
