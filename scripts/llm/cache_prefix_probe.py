# -*- coding: utf-8 -*-
"""床の前置きが「便ごとに組み直されて壊れているか」を、実験で確かめる計器。

★なぜ要るか(2026-08-23・研究室HQ msg DISPATCH-aegis-gl-1787493567341 の発注)
  HQの実測= 大書込(>=30,000)は全便の9.0%だが**書込の77.2%を作る**。
  その便の cache_read 中央値は 10,656(普通の便は111,728)=
  **前置きが約1万トークンの位置で壊れ、以降を丸ごと書き直している**。
  HQの仮説= 壊れる位置に居るのは `gitStatus`(システムプロンプトへ毎回入る git の状態)。
  この作業ツリーは常に動いている(実測 変更349件 / 直近24hのcommit 99本)ので、
  `claude -p --resume` が便ごとにプロセスを立て直す=前置きを組み直す時に、
  gitStatus が前便と違えば**そこから後ろが全部書き直しになる**、という筋書きだ。

★この計器がやること= **同じセッションへ短い便を続けて撃ち、間に何を挟むかだけ変える。**
  A) 作業ツリーを一切触らずに2便          → 前置きが動かない側
  B) 間にcommitを1本挟んでから1便         → gitStatus の「Recent commits」が動く側
  それぞれの `cache_read` / `cache_creation` を記録して並べる。
  ★Aが全ヒット・Bが大書込なら仮説は当たり。Aでも大書込が出るなら犯人は別に居る。

★測定の妥当性で気をつけた点(§3「検証が失敗したら、まず検証の妥当性を疑う」)
  ・この作業ツリーは**他の部屋も同時に触っている**(15分に1本commitが入る)。
    → A の前後で `HEAD` と `git status --porcelain` の指紋を取り、
      **動いていたらその回のAは無効**として捨てる(黙って混ぜない)。
  ・道具を使わせない短い便にする= 出力の揺れで読み値が濁らないように。

使い方:
  python scripts/llm/cache_prefix_probe.py            # A2便+B1便(commitは自動で1本作る)
  python scripts/llm/cache_prefix_probe.py --no-commit  # Aだけ(commitを作らない)
  python scripts/llm/cache_prefix_probe.py --model sonnet
  python scripts/llm/cache_prefix_probe.py --share    # ★実験でなく**過去の記録**で取り分を測る
"""
import argparse
import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROMPT = "「あ」とだけ答えろ。道具は使うな。説明も要らない。"


def git(*args):
    p = subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.stdout.strip()


def tree_fingerprint():
    """gitStatus に出る物の指紋= HEAD と 変更ファイル一覧。"""
    return (git("rev-parse", "HEAD"), hash(git("status", "--porcelain")))


def one_turn(model, session=None, label="", env_extra=None):
    """`claude -p` を1便撃って usage を返す。session=None なら新規セッション。"""
    argv = ["claude", "-p", PROMPT, "--model", model, "--output-format", "json"]
    if session:
        argv += ["--resume", session]
    env = dict(os.environ)
    env.update(env_extra or {})
    t0 = time.time()
    p = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    if p.returncode != 0:
        print("  ★便が失敗した(%s): %s" % (label, (p.stderr or p.stdout or "")[:400]))
        return None
    try:
        d = json.loads(p.stdout)
    except ValueError:
        print("  ★JSONで返ってこなかった(%s): %s" % (label, p.stdout[:400]))
        return None
    u = d.get("usage") or {}
    cd = u.get("cache_creation") or {}
    rec = {
        "label": label,
        "session": d.get("session_id"),
        "cr": u.get("cache_read_input_tokens", 0) or 0,
        "cc": u.get("cache_creation_input_tokens", 0) or 0,
        "cc1h": cd.get("ephemeral_1h_input_tokens", 0) or 0,
        "cc5m": cd.get("ephemeral_5m_input_tokens", 0) or 0,
        "inp": u.get("input_tokens", 0) or 0,
        "out": u.get("output_tokens", 0) or 0,
        "sec": round(time.time() - t0, 1),
    }
    print("  %-28s 読込 %8d / 書込 %8d (1h %d / 5m %d) %.1f秒"
          % (label, rec["cr"], rec["cc"], rec["cc1h"], rec["cc5m"], rec["sec"]))
    return rec


def report_share(hours, big):
    """★実験は「gitStatusで壊れる」を示すが、**過去の大書込の何割がそれか**は別の問いだ。

    やり方= 記録の便を時刻順に並べ、**前便との隙間に commit が入っていたか**を数える。
    ★これは**下限**だ= commitしていない編集(ファイルを保存しただけ)でも gitStatus は動くが、
      git log には出ない。だから「commit在り」は取りこぼす側に倒れている。
    """
    import bisect
    from datetime import datetime, timedelta, timezone
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import floor_burn as fb

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = fb.scan_detail(since)
    if not rows:
        print("直近 %g 時間に記録が無い。" % hours)
        return 1
    commits = sorted(int(x) for x in git(
        "log", "--since=%g hours ago" % (hours + 1), "--format=%ct").split() if x.isdigit())
    per = {}
    for r in rows:
        per.setdefault(r["sid"], []).append(r)
    big_c = big_n = norm_c = norm_n = 0
    big_cc_with = big_cc_all = 0
    for rs in per.values():
        rs.sort(key=lambda r: r["dt"])
        for prev, cur in zip(rs, rs[1:]):
            a, b = prev["dt"].timestamp(), cur["dt"].timestamp()
            has = bisect.bisect_right(commits, b) - bisect.bisect_left(commits, a) > 0
            if cur["cc"] >= big:
                big_n += 1
                big_c += has
                big_cc_all += cur["cc"]
                big_cc_with += cur["cc"] if has else 0
            else:
                norm_n += 1
                norm_c += has
    print("■ 過去の記録での取り分(直近%g時間 / 継続の便だけ / 大書込の線 %d)" % (hours, big))
    print("  commit %d本 / 継続の便 %d本" % (len(commits), big_n + norm_n))
    print("  大書込 %6d本 のうち 前便との隙間にcommit在り %6d本 (%.1f%%)"
          % (big_n, big_c, pct(big_c, big_n)))
    print("  普通便 %6d本 のうち 前便との隙間にcommit在り %6d本 (%.1f%%)  ←下敷き(基準率)"
          % (norm_n, norm_c, pct(norm_c, norm_n)))
    print("  大書込の書込量 %d のうち commit在りの便が作った分 %d (%.1f%%)"
          % (big_cc_all, big_cc_with, pct(big_cc_with, big_cc_all)))
    print("  ★commitしていない編集でも gitStatus は動く=この値は**下限**だ。")
    return 0


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--no-commit", action="store_true",
                    help="Bを回さない(commitを1本も作らない)")
    ap.add_argument("--share", action="store_true",
                    help="実験でなく過去の記録を読み、大書込のうちcommitが挟まった割合を出す")
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--big", type=int, default=30000)
    ap.add_argument("--env", action="append", default=[],
                    help="NAME=VALUE を子プロセスへ足す(対策の効き目を測る時に使う)")
    a = ap.parse_args()
    env_extra = dict(kv.split("=", 1) for kv in a.env if "=" in kv)
    if a.share:
        return report_share(a.hours, a.big)

    print("■ 前置きが便ごとに壊れているかの実験 (model=%s)" % a.model)
    if env_extra:
        print("  足す環境変数= %s" % ", ".join("%s=%s" % kv for kv in env_extra.items()))
    rows = []

    print("\n【種】新しいセッションを1本立てる(この便の書込は初回=避けられない分)")
    seed = one_turn(a.model, label="種(新規セッション)", env_extra=env_extra)
    if not seed or not seed["session"]:
        print("★セッションが取れなかった。ここで止める。")
        return 1
    sid = seed["session"]
    rows.append(seed)
    print("  セッション= %s" % sid)

    print("\n【A】作業ツリーを一切触らずに、続けて2便")
    fp0 = tree_fingerprint()
    a1 = one_turn(a.model, sid, "A-1(無変更)", env_extra)
    a2 = one_turn(a.model, sid, "A-2(無変更)", env_extra)
    fp1 = tree_fingerprint()
    rows += [r for r in (a1, a2) if r]
    a_valid = (fp0 == fp1)
    if not a_valid:
        print("  ★★A は無効だ= 実験中に他の部屋が作業ツリーを動かした(HEAD/変更一覧が変わった)。")
        print("     前 HEAD=%s / 後 HEAD=%s" % (fp0[0][:8], fp1[0][:8]))
    else:
        print("  A の間、作業ツリーは動いていない(HEAD=%s のまま)。" % fp0[0][:8])

    b = None
    if not a.no_commit:
        print("\n【B】間に commit を1本挟んでから1便(gitStatus の Recent commits が動く)")
        stamp = os.path.join(ROOT, "local", "_work", "cache_probe_stamp.txt")
        os.makedirs(os.path.dirname(stamp), exist_ok=True)
        with open(stamp, "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
        # ★local/ は gitignore されているので、commit の中身ではなく
        #   「commitが1本増えたこと」自体を効かせる(--allow-empty)。
        git("commit", "--allow-empty", "-m",
            "chore(計測): 前置きキャッシュ実験の目印(イージス研究室・空commit)")
        print("  HEAD %s → %s" % (fp1[0][:8], git("rev-parse", "HEAD")[:8]))
        b = one_turn(a.model, sid, "B(間にcommit1本)", env_extra)
        if b:
            rows.append(b)

    print("\n■ 並べる")
    for r in rows:
        print("  %-28s 読込 %8d  書込 %8d" % (r["label"], r["cr"], r["cc"]))

    print("\n■ 読み")
    if a1 and a2:
        if not a_valid:
            print("  A= 無効(他の部屋がツリーを動かした)。判定しない。")
        elif a2["cc"] < 2000 and a2["cr"] > 10000:
            print("  A= ほぼ全ヒット(書込 %d)。前置きが動かない限り壊れていない。" % a2["cc"])
        else:
            print("  ★A でも書込 %d が出た= 犯人は gitStatus 以外にも居る。" % a2["cc"])
    if b and a2:
        if b["cc"] >= max(10000, a2["cc"] * 5):
            print("  B= 書込 %d(Aの %d に対して大きい)= **commitで前置きが壊れている**。"
                  % (b["cc"], a2["cc"]))
            print("     壊れた位置の目安= B の読込 %d トークン(そこまでは生きていた)。" % b["cr"])
        elif env_extra:
            print("  B= 書込 %d しか出ない= **足した環境変数が効いている**(前置きが壊れない)。"
                  % b["cc"])
        else:
            print("  ★B でも書込は %d しか出ない= commit は主因ではない。仮説は外れ。" % b["cc"])

    tag = "_" + "_".join(sorted(env_extra)) if env_extra else ""
    out = os.path.join(ROOT, "local", "_work", "cache_prefix_probe%s.json" % tag)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"ts": time.strftime("%Y-%m-%dT%H:%M:%S+09:00"), "model": a.model,
                   "env": env_extra, "a_valid": a_valid, "rows": rows}, f, ensure_ascii=False, indent=1)
    print("\n  生の値= %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
