# -*- coding: utf-8 -*-
"""FCC安全起動器(C-049 執行形5)の検査。

★受け入れ条件1= 「4条件それぞれについて、**欠けた状態を実際に作って**起動を拒むところを見た」。
  だからこの検査は `"..." in src` を1つも使わない。
  **本物のフォルダを作り、本物の git clone/init を打ち、本物の環境値を渡して**
  `preflight()` を通す。偽物にしてよいのは**外へ出る手(claudeの実起動)だけ**で、
  それは preflight を直接呼ぶことで自然に外れる(判定と分岐は本物のまま)。

★must-fail= 各条件について「壊した時に鳴る」だけでなく「**直した時に黙る**」も見る。
  片側だけだと『常に鳴る安全網』(=無視される)を PASS と誤認する。
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "scripts", "llm"))
from fcc_launch import (build_plan, preflight, parse_add_dirs,     # noqa: E402
                        prod_roots, find_secrets, HQ_ROOT, HOME_CLAUDE)

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("[PASS] %s" % name)
    else:
        FAILS.append(name)
        print("[FAIL] %s %s" % (name, detail))


def only(reasons, letter):
    """理由リストのうち指定の条件(A〜F)のものだけ。"""
    return [r for r in reasons if r.startswith(letter + ":")]


PUBLIC_URL = "https://github.com/John-Mori/go5-maker-7b311d01.git"


def _git(p, *args):
    return subprocess.run(["git", "-C", p] + list(args), capture_output=True,
                          text=True, timeout=60)


def make_clone(root, name="clone", origin=PUBLIC_URL):
    """公開repoの別クローンの体裁を**本物で**作る。

    ★2026-08-23(研究室HQ差し戻し・C-041)で変えた所=
      旧版は `git init` だけで **remote を設定していなかった**。
      それだと「追跡済み=公開済み」の検査が、**一度も公開されていないファイルを通す**のを
      緑のまま見逃す(=テストが穴を証明していた)。今は既定で origin と
      remote側の ref(refs/remotes/origin/main)まで作る=本物のクローンと同じ形。
      `origin=None` を渡せば **remote無し**の版になる(そちらでは通ってはいけない)。
    """
    p = os.path.join(root, name)
    os.makedirs(p, exist_ok=True)
    subprocess.run(["git", "init", "-q", p], capture_output=True, timeout=60)
    _git(p, "config", "user.email", "test@example.invalid")
    _git(p, "config", "user.name", "fcc gate test")
    io.open(os.path.join(p, "app.js"), "w", encoding="utf-8").write("// public\n")
    _git(p, "add", "app.js")
    _git(p, "commit", "-q", "-m", "public")
    if origin:
        _git(p, "remote", "add", "origin", origin)
        publish(p)
    return p


def publish(p):
    """remote側のツリーを HEAD に合わせる(=`git push` 済みの状態を本物のrefで作る)。"""
    _git(p, "update-ref", "refs/remotes/origin/main", "HEAD")


def main():
    tmp = tempfile.mkdtemp(prefix="fcc_gate_test_")
    try:
        wd = make_clone(tmp)
        cfg = os.path.join(tmp, "cfg")
        os.makedirs(cfg, exist_ok=True)

        # ---- 0. 4条件が揃った状態= **通る**(通らない検査は何も検証していない)
        base = build_plan(wd, cfg, [])
        r0 = preflight(base)
        check("G-0 A〜F が揃った使い捨てクローンは**通る**(空の拒否理由)",
              r0 == [], r0)

        # ---- A. 本番の作業ツリーを指したら拒む
        prod = prod_roots()[0]
        ra = preflight(build_plan(prod, cfg, []))
        check("G-A1 本番の作業ツリーを workdir にすると拒む", only(ra, "A"), ra)

        sub = os.path.join(prod, "scripts")
        ra2 = preflight(build_plan(sub, cfg, []))
        check("G-A2 本番ツリーの**配下**でも拒む(親を1段ずつ実在で突き合わせる)",
              only(ra2, "A"), ra2)

        ra3 = preflight(build_plan(HQ_ROOT, cfg, []))
        check("G-A3 00_AI-HQ を workdir にすると拒む", only(ra3, "A"), ra3)

        bare = os.path.join(tmp, "notaclone")
        os.makedirs(bare, exist_ok=True)
        ra4 = preflight(build_plan(bare, cfg, []))
        check("G-A4 .git の無いただのフォルダは『クローンではない』と拒む",
              only(ra4, "A"), ra4)

        ra5 = preflight(build_plan(os.path.join(tmp, "nothere"), cfg, []))
        check("G-A5 実在しないフォルダは拒む(存在しない物を通さない)",
              only(ra5, "A"), ra5)

        # ---- B. --add-dir に 00_AI-HQ / 本番
        rb = preflight(build_plan(wd, cfg, ["--add-dir", HQ_ROOT]))
        check("G-B1 --add-dir 00_AI-HQ を拒む(引数を実際に解析している)",
              only(rb, "B"), rb)

        rb2 = preflight(build_plan(wd, cfg, ["--add-dir=" + HQ_ROOT]))
        check("G-B2 --add-dir=... の書き方でも拾う(= の形を取りこぼさない)",
              only(rb2, "B"), rb2)

        rb3 = preflight(build_plan(wd, cfg, ["-p", "x", "--add-dir", os.path.join(HQ_ROOT, "departments")]))
        check("G-B3 00_AI-HQ の**配下**でも拒む", only(rb3, "B"), rb3)

        rb4 = preflight(build_plan(wd, cfg, ["--add-dir", prod]))
        check("G-B4 --add-dir が本番の作業ツリーでも拒む", only(rb4, "B"), rb4)

        check("G-B5 直すと黙る= --add-dir 無しでは B は鳴らない",
              only(preflight(build_plan(wd, cfg, ["-p", "x"])), "B") == [])

        # ---- C. CLAUDE_CONFIG_DIR
        rc = preflight(build_plan(wd, HOME_CLAUDE, []))
        check("G-C1 本番の ~/.claude を指すと拒む", only(rc, "C"), rc)

        rc2 = preflight(build_plan(wd, os.path.join(HOME_CLAUDE, "projects"), []))
        check("G-C2 ~/.claude の**配下**でも拒む", only(rc2, "C"), rc2)

        rc3 = preflight(build_plan(wd, "", []))
        check("G-C3 空(=既定の ~/.claude が読まれる)を拒む", only(rc3, "C"), rc3)

        check("G-C4 直すと黙る= 使い捨ての設定フォルダなら C は鳴らない",
              only(preflight(build_plan(wd, cfg, [])), "C") == [])

        # ---- D. 秘密ファイル(1種類ずつ実際に置いて、消すと黙るまで見る)
        for rel, why in [(".env", ".env"),
                         ("api_token.txt", "*token*"),
                         ("my_secret.json", "*secret*"),
                         ("cache.db", "*.db")]:
            p = os.path.join(wd, rel)
            io.open(p, "w", encoding="utf-8").write("x\n")
            rd = preflight(build_plan(wd, cfg, []))
            hit = bool(only(rd, "D"))
            os.remove(p)
            gone = not only(preflight(build_plan(wd, cfg, [])), "D")
            check("G-D(%s) 置くと拒み、消すと黙る" % why, hit and gone,
                  "置いた時=%s / 消した時=%s" % (hit, not gone))

        ld = os.path.join(wd, "local")
        os.makedirs(ld, exist_ok=True)
        io.open(os.path.join(ld, "note.txt"), "w", encoding="utf-8").write("x\n")
        rd2 = preflight(build_plan(wd, cfg, []))
        check("G-D(local/) 台帳フォルダが在ると拒む", only(rd2, "D"), rd2)
        shutil.rmtree(ld)

        deep = os.path.join(wd, "a", "b", "c")
        os.makedirs(deep, exist_ok=True)
        io.open(os.path.join(deep, ".env"), "w", encoding="utf-8").write("K=1\n")
        rd3 = preflight(build_plan(wd, cfg, []))
        check("G-D(深い階層) 配下を実際に歩いて見つける(直下だけ見ていない)",
              only(rd3, "D"), rd3)
        shutil.rmtree(os.path.join(wd, "a"))

        # ★.git の中は歩かない= 公開repoのクローンが自分の .git で必ず落ちる、を避ける
        gitobj = os.path.join(wd, ".git", "shallow.db")
        io.open(gitobj, "w", encoding="utf-8").write("x\n")
        check("G-D(.git 除外) .git 配下は数えない(常に誤発火する安全網にしない)",
              not only(preflight(build_plan(wd, cfg, [])), "D"))
        os.remove(gitobj)

        # ★D の要= 「既に公開されている」と「持ち込み」を分ける。
        #   実測= 公開repoには update_token.ps1 / js/secret-reveal.js 等が**7件**追跡されている。
        #   名前当てだけで拒むと C-049 が許した唯一の使い道が永久に起動できない。
        tp = os.path.join(wd, "update_token.ps1")
        io.open(tp, "w", encoding="utf-8").write("# public\n")
        fired_untracked = bool(only(preflight(build_plan(wd, cfg, [])), "D"))
        _git(wd, "add", "update_token.ps1")
        _git(wd, "commit", "-q", "-m", "add token script")
        fired_committed = bool(only(preflight(build_plan(wd, cfg, [])), "D"))
        publish(wd)                                   # ← remote側のツリーにも載せる
        fired_published = bool(only(preflight(build_plan(wd, cfg, [])), "D"))
        check("G-D(公開の別) 未追跡=拒む / commitしただけ=まだ拒む / 公開済み=通す",
              fired_untracked and fired_committed and not fired_published,
              "未追跡=%s commitのみ=%s 公開済み=%s"
              % (fired_untracked, fired_committed, fired_published))

        # ★★C-041 の差し戻し= 「追跡済み」を「公開済み」の代理にしていた穴。
        #   remote が無い / 知らない remote のフォルダでは、**commitされていても**
        #   どこにも出ていない=名前当てのまま拒否側へ倒れること。
        #   ★旧版の make_clone は remote を設定していなかったので、この形が緑のまま通っていた。
        nr = make_clone(tmp, "noremote", origin=None)     # remote無しの本物のgitフォルダ
        io.open(os.path.join(nr, ".env"), "w", encoding="utf-8").write("BSKY_APP_PW=x\n")
        _git(nr, "add", "-f", ".env")
        _git(nr, "commit", "-q", "-m", "committed but never published")
        check("G-D(remote無し) commit済みでも remote が無ければ**公開の証明が無い**=拒む",
              only(preflight(build_plan(nr, cfg, [])), "D"),
              preflight(build_plan(nr, cfg, [])))

        ur = make_clone(tmp, "unknownremote", origin="https://example.invalid/who/knows.git")
        io.open(os.path.join(ur, ".env"), "w", encoding="utf-8").write("BSKY_APP_PW=x\n")
        _git(ur, "add", "-f", ".env")
        _git(ur, "commit", "-q", "-m", "published somewhere unknown")
        publish(ur)
        check("G-D(知らないremote) 許可リストに無い remote では追跡済みでも拒む",
              only(preflight(build_plan(ur, cfg, [])), "D"),
              preflight(build_plan(ur, cfg, [])))

        check("G-D(直すと黙る) 許可リストの origin へ向け直すと同じ物が通る",
              (_git(ur, "remote", "set-url", "origin", PUBLIC_URL) is not None
               and not only(preflight(build_plan(ur, cfg, [])), "D")),
              preflight(build_plan(ur, cfg, [])))

        # remote URL の均し(https / ssh / .git 有無 が同じ物として当たること)
        from fcc_launch import _norm_origin, PUBLIC_ORIGINS      # noqa: E402
        forms = ["https://github.com/John-Mori/go5-maker-7b311d01.git",
                 "https://github.com/John-Mori/go5-maker-7b311d01",
                 "git@github.com:John-Mori/go5-maker-7b311d01.git",
                 "ssh://git@github.com/John-Mori/go5-maker-7b311d01/"]
        check("G-D(URLの形) https/ssh/.git有無 のどれでも同じ公開repoとして当たる",
              all(_norm_origin(u) in PUBLIC_ORIGINS for u in forms),
              [_norm_origin(u) for u in forms])
        check("G-D(似て非なるURL) 別ホスト・別リポは当たらない",
              not any(_norm_origin(u) in PUBLIC_ORIGINS for u in
                      ["https://github.com/John-Mori/go5-maker-7b311d01-evil",
                       "https://gitlab.com/John-Mori/go5-maker-7b311d01",
                       "https://github.com/someone/go5-maker-7b311d01"]))

        _git(wd, "rm", "-q", "-f", "update_token.ps1")
        _git(wd, "commit", "-q", "-m", "drop")
        publish(wd)

        # ---- E. 祖先の CLAUDE.md / MEMORY.md
        parent = os.path.join(tmp, "withctx")
        os.makedirs(parent, exist_ok=True)
        io.open(os.path.join(parent, "CLAUDE.md"), "w", encoding="utf-8").write("# ctx\n")
        wd2 = make_clone(parent, "inner")
        re1 = preflight(build_plan(wd2, cfg, []))
        check("G-E1 祖先に CLAUDE.md が在ると拒む(cwdの上から自動で本文へ載る)",
              only(re1, "E"), re1)

        io.open(os.path.join(wd, "CLAUDE.md"), "w", encoding="utf-8").write("# public\n")
        check("G-E2 **作業フォルダ自身**の CLAUDE.md では鳴らない(公開repoの中身=既に出ている)",
              not only(preflight(build_plan(wd, cfg, [])), "E"))
        os.remove(os.path.join(wd, "CLAUDE.md"))

        # ---- F. --add-dir が作業フォルダの外
        outside = os.path.join(tmp, "outside")
        os.makedirs(outside, exist_ok=True)
        rf = preflight(build_plan(wd, cfg, ["--add-dir", outside]))
        check("G-F1 作業フォルダの外を --add-dir すると拒む", only(rf, "F"), rf)

        insid = os.path.join(wd, "sub")
        os.makedirs(insid, exist_ok=True)
        check("G-F2 作業フォルダの**中**なら F は鳴らない",
              not only(preflight(build_plan(wd, cfg, ["--add-dir", insid])), "F"))

        # ---- 解析そのもの
        check("G-P1 --add-dir の3つの書き方を全部拾う",
              parse_add_dirs(["--add-dir", "a", "--add-dir=b", "-p", "x",
                              "--add-dir", "c"]) == ["a", "b", "c"],
              parse_add_dirs(["--add-dir", "a", "--add-dir=b", "-p", "x", "--add-dir", "c"]))

        check("G-P2 --add-dir が最後で値が無い時に落ちない",
              parse_add_dirs(["--add-dir"]) == [])

        # ---- 合わせ技= 複数欠けたら**全部**出す(直す側が一度に見られる)
        rall = preflight(build_plan(prod, HOME_CLAUDE, ["--add-dir", HQ_ROOT]))
        got = {r[0] for r in rall}
        check("G-X 複数欠けたら A/B/C を全部並べる(最初の1つで打ち切らない)",
              {"A", "B", "C"} <= got, sorted(got))

        # ---- 検査自身が例外で落ちたら**拒否側**へ倒す(fail-close)
        import fcc_launch
        orig = fcc_launch.check_d
        try:
            fcc_launch.check_d = lambda p: (_ for _ in ()).throw(RuntimeError("boom"))
            fcc_launch.CHECKS[3] = ("D", fcc_launch.check_d)
            rx = preflight(build_plan(wd, cfg, []))
            check("G-Z 検査が例外で落ちたら**起動を拒む**(判定不能を通さない)",
                  any("判定不能" in r for r in rx), rx)
        finally:
            fcc_launch.check_d = orig
            fcc_launch.CHECKS[3] = ("D", orig)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=== 全PASS ===" if not FAILS else "=== FAIL %d件: %s" % (len(FAILS), FAILS))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
