#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_daily_teian.py — 提案候補の日次チェーン(改修α・C-038恒久策)。

なぜ要るか:
  candidates_json.py(商品選定)が回るたびに候補JSONを丸ごと書き直し、④comments=[] /
  room_comments無し に戻る。vision と軍議(三笘/芽衣)を通す前に publish すると
  空ページが客先へ出る(2026-08-23の寸前事故)。しかも room_comments には自動生成器が
  無い=放置すると毎朝手で埋め直しになる。

何をするか(必ずこの順で通す):
  ① 退避   … 既存 candidates_<date>.json の {cid: comments / room_comments} を控える
  ② 再生成 … candidates_json.py(商品選定・product-scout)を実行(= comments空/room無しに戻る)
  ③ 引継ぎ … 退避分を cid で書き戻す(既に済んだ④comments/room_comments を守る=持続化)
  ④ vision … vision_comments.py で「まだ空の候補だけ」④comments を埋める(fail-open)
  ⑤ 配信   … publish_candidates.py(空配信ガード付き=全候補充填でなければ止まる)

  ★新しく入った cid の room_comments は自動生成器が無い=空のまま → ⑤のガードが止める
    (=軍議で手当が要ると分かる)。既存 cid は毎回引き継がれる=繰り返しの手作業はゼロ。
  ★あらすじ本文・秘密は一切 candidates_<date>.json 本体へ書かない(publishが丸ごとR2へ
    上げる=client漏れ)。ここは comments / room_comments だけを触る。

使い方:
  python scripts/teian/run_daily_teian.py                 # 今日(JST)を頭から通す
  python scripts/teian/run_daily_teian.py --dry-run       # 各段のコマンドと引継ぎ件数を表示のみ
  python scripts/teian/run_daily_teian.py --skip-generate # 再生成せず現ファイルへ vision→配信(復旧向け)
  python scripts/teian/run_daily_teian.py --no-publish    # 配信手前まで(手で確認してから publish)
"""
import argparse
import datetime
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
TEIAN_DIR = os.path.join(ROOT, "local", "teian")
GEN = os.path.join(ROOT, "docs", "departments", "product-scout", "tools", "candidates_json.py")
VISION = os.path.join(HERE, "vision_comments.py")
PUBLISH = os.path.join(HERE, "publish_candidates.py")


def jst_today() -> str:
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")


def _rc_ok(rc) -> bool:
    if not isinstance(rc, dict) or not rc.get("mitoma"):
        return False
    main = rc.get("main")
    return bool(main.get("text")) if isinstance(main, dict) else bool(main)


def snapshot(path: str) -> dict:
    """再生成の前に、既存の comments / room_comments を cid で控える(空は控えない)。"""
    keep = {}
    if not os.path.exists(path):
        return keep
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except Exception as e:
        print(f"  [退避] 現ファイルを読めず(引継ぎ無しで続行): {e}", file=sys.stderr)
        return keep
    for c in doc.get("candidates", []):
        cid = c.get("cid")
        if not cid:
            continue
        entry = {}
        if c.get("comments"):
            entry["comments"] = c["comments"]
        if _rc_ok(c.get("room_comments")):
            entry["room_comments"] = c["room_comments"]
        if entry:
            keep[cid] = entry
    return keep


def carry_over(path: str, keep: dict, dry: bool) -> int:
    """再生成後のファイルへ、退避分を cid で書き戻す。空の候補だけ埋める(再生成が実データを
    載せた場合は壊さない)。書き戻した候補数を返す。"""
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    touched = 0
    for c in doc.get("candidates", []):
        cid = c.get("cid")
        prev = keep.get(cid)
        if not prev:
            continue
        did = False
        if not c.get("comments") and prev.get("comments"):
            c["comments"] = prev["comments"]
            did = True
        if not _rc_ok(c.get("room_comments")) and prev.get("room_comments"):
            c["room_comments"] = prev["room_comments"]
            did = True
        if did:
            touched += 1
    if dry:
        print(f"  [dry] 引継ぎ対象 {touched} 候補(cid一致・空欄のみ復元)")
        return touched
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    return touched


def run(cmd: list, dry: bool, label: str) -> int:
    print(f"── {label}")
    if dry:
        print("  [dry] " + " ".join(cmd))
        return 0
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run(cmd, cwd=ROOT, env=env)
    return r.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD(既定=今日JST)")
    ap.add_argument("--dry-run", action="store_true", help="実行せずコマンドと引継ぎ件数だけ表示")
    ap.add_argument("--skip-generate", action="store_true",
                    help="candidates_json.py を回さず、現ファイルへ vision→配信(復旧向け)")
    ap.add_argument("--no-publish", action="store_true", help="配信の手前で止める")
    ap.add_argument("--vision-limit", type=int, default=0, help="vision が埋める候補数(0=全部・既定)")
    ap.add_argument("--vision", action="store_true",
                    help="④ vision(サンプル画像から3択)を回す。★既定OFF=Chami指示2026-08-23"
                         "(msg 1541180961272889384): 画像なし段階のサンプル生成は投稿画像で作り直すので無駄。"
                         "コメントは今すぐ投稿できる作品の投稿画像から作る=日次のサンプル一括生成は止める。")
    ap.add_argument("--publish-force", action="store_true", help="空配信ガードを無視して配信")
    args = ap.parse_args()

    date = args.date or jst_today()
    src = os.path.join(TEIAN_DIR, f"candidates_{date}.json")
    py = sys.executable or "python"

    # ① 退避(再生成の前に既存の手当を控える)
    keep = snapshot(src)
    print(f"① 退避: {len(keep)} 候補の comments/room_comments を控えた(cidキー)")

    # ② 再生成(product-scout)
    if args.skip_generate:
        print("② 再生成: --skip-generate=スキップ(現ファイルを使う)")
        if not os.path.exists(src):
            sys.stderr.write(f"候補JSONが無い: {src}\n")
            return 1
    else:
        rc = run([py, GEN], args.dry_run, "② 再生成 candidates_json.py(product-scout)")
        if rc != 0:
            sys.stderr.write("再生成が失敗(上の出力を確認)。チェーンを止める。\n")
            return rc

    # ③ 引継ぎ(退避分を書き戻す)
    if args.dry_run and not os.path.exists(src):
        print("③ 引継ぎ: [dry] 現ファイルが無いため件数のみ試算不可(本番では再生成後に実施)")
    else:
        n = carry_over(src, keep, args.dry_run)
        print(f"③ 引継ぎ: {n} 候補へ既存の comments/room_comments を復元(空欄のみ)")

    # ④ vision(まだ空の④commentsだけ埋める。--force無し=引継ぎ済みは温存)
    # ★既定でスキップ(Chami指示2026-08-23 msg 1541180961272889384)。理由=候補JSONの作品は
    #   ページ側でほぼ pool(紹介にはアツい=動画生成用画像なし)へ落ちる。そこへFANZAサンプルから3択を
    #   一括生成しても、Chamiが投稿画像を貼った時点で投稿画像から作り直す=トークンの無駄。
    #   コメントは「今すぐ投稿できる(=投稿画像あり)」作品の投稿画像から作る方針。--vision で従来動作。
    if args.vision:
        rc = run([py, VISION, "--in", src, "--limit", str(args.vision_limit)],
                 args.dry_run, f"④ vision_comments.py(空の候補のみ・limit={args.vision_limit})")
        if rc != 0:
            sys.stderr.write("vision が失敗。room_comments/引継ぎ分は残っているが④commentsが欠ける可能性。\n")
            # fail-open: 続行はするが publish のガードが空を止める
    else:
        print("④ vision: 既定スキップ(--vision で従来のサンプル一括生成。Chami指示2026-08-23)")

    # ⑤ 配信(空配信ガード付き)
    if args.no_publish:
        print("⑤ 配信: --no-publish=手前で停止。確認後に publish_candidates.py を実行。")
        return 0
    pub = [py, PUBLISH, "--date", date]
    if args.dry_run:
        pub.append("--dry-run")
    if args.publish_force:
        pub.append("--force")
    rc = run(pub, args.dry_run, "⑤ 配信 publish_candidates.py(空配信ガード)")
    if rc == 2:
        sys.stderr.write("→ 未充填の候補があり配信を止めた(上の一覧)。軍議で room_comments を埋めて再実行。\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
