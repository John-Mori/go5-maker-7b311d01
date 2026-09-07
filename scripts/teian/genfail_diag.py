#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""genfail_diag.py — teianの配信が genfail(exit=2)で止まった時、
   直近の実ランで「何が候補を溶かしたか」を課金台帳から1コマンドで診断する読み取り専用ツール。

なぜ在るか(2026-09-06 / 2026-09-07 の同型往復の再発防止):
  毎朝7時の自動チェーンが genfail で落ちた時、ディスパッチは
  「生成器の故障」「使い切った最後のエラー=(不明)」と framing してくるが、
  真因は gemini_usage.jsonl の err 欄を読めば分かる:
    - HTTP 429 = 枠切れ(quota)。★Chamiにしか開けられない
    - HTTP 400「Unable to process input image」= 壊れた画像。★改修αの fail-open で通す
    - それ以外(403/404/503 等)= 別根
  「答える前に(framingを鵜呑みにせず)実物を読む」を1コマンドに落とす。
  台帳は gemini_usage.read_all() を再利用する(読み取りだけ・第二の読み手を作らない)。

使い方:
  python scripts/teian/genfail_diag.py                 # 直近の teian 失敗クラスタを診断
  python scripts/teian/genfail_diag.py --minutes 30    # 直近ランの窓を狭める(既定=最終行から遡って同一ランを束ねる)
  python scripts/teian/genfail_diag.py --tag room_comments   # tag を絞る(既定= room_comments / vision_comments 両方)
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "llm"))
import gemini_usage  # noqa: E402  読み取り専用で再利用

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TEIAN_TAGS = {"room_comments", "vision_comments"}


def _code(row) -> str:
    """その行の HTTP コードを返す('429'/'400'/'404'... / '' = 不明)。"""
    err = str(row.get("err") or "")
    m = re.search(r"(\d{3})", err)
    if m:
        return m.group(1)
    m = re.search(r'"code"\s*:\s*(\d{3})', str(row.get("err_detail") or ""))
    return m.group(1) if m else ""


def _is_image_400(row) -> bool:
    return _code(row) == "400" and "input image" in str(row.get("err_detail") or "").lower()


def main() -> int:
    tag_filter = None
    minutes = None
    args = sys.argv[1:]
    if "--tag" in args:
        i = args.index("--tag")
        if i + 1 < len(args):
            tag_filter = {args[i + 1]}
    if "--minutes" in args:
        i = args.index("--minutes")
        if i + 1 < len(args):
            minutes = float(args[i + 1])

    tags = tag_filter or TEIAN_TAGS
    rows = [r for r in gemini_usage.read_all() if (r.get("tag") in tags)]
    if not rows:
        print(f"teian の使用行が台帳に無い(tags={sorted(tags)} / {gemini_usage.USAGE_FILE})")
        return 0

    # 直近ランのクラスタを束ねる: 最終行の時刻から minutes 遡る(既定=90分=1ランは数分なので十分に収まる)
    def epoch(r):
        try:
            import time
            return time.mktime(time.strptime(str(r.get("ts", ""))[:19], "%Y-%m-%dT%H:%M:%S"))
        except Exception:
            return 0.0

    rows.sort(key=epoch)
    last_t = epoch(rows[-1])
    win = (minutes if minutes is not None else 90) * 60
    cluster = [r for r in rows if last_t - epoch(r) <= win]

    fails = [r for r in cluster if str(r.get("ok")).lower() != "true"]
    oks = [r for r in cluster if str(r.get("ok")).lower() == "true"]

    print(f"■ 直近 teian ラン(tags={sorted(tags)}) 窓 {cluster[0]['ts']} 〜 {cluster[-1]['ts']}")
    print(f"  試行 {len(cluster)}件 / 成功 {len(oks)}件 / 失敗 {len(fails)}件")

    if not fails:
        print("  → 失敗ゼロ。この窓では genfail の材料は無い(配信が止まったなら別段=②再生成/④comments/⑤配信ガードを見る)")
        return 0

    # コード別・モデル別
    by_code = {}
    for r in fails:
        by_code.setdefault(_code(r) or "不明", []).append(r)
    print("  失敗の内訳(HTTPコード別):")
    for code in sorted(by_code, key=lambda c: -len(by_code[c])):
        models = sorted({r.get("model", "?") for r in by_code[code]})
        img = " ・画像400(処理不能な画像)" if code == "400" and any(_is_image_400(r) for r in by_code[code]) else ""
        print(f"    HTTP {code}: {len(by_code[code])}件  models={models}{img}")

    last_fail = fails[-1]
    print(f"  最後のエラー= HTTP {_code(last_fail) or '不明'} / model={last_fail.get('model','?')} / {str(last_fail.get('err') or last_fail.get('err_detail') or '')[:60]}")

    # 判定(誰が直せるか)
    has_429 = any(_code(r) == "429" for r in fails)
    all_image_400 = fails and all(_is_image_400(r) for r in fails)
    print("  ── 判定 ──")
    if all_image_400:
        print("  → 全滅が画像400。★改修αの fail-open(画像を外してテキストのみ再試行)で通る案件。枠は無関係。")
    elif has_429:
        print("  → 429(枠切れ=quota)を含む。★枠はChamiにしか開けられない。ただし全モデルが画像400で溶けている候補は fail-open で救える。")
    else:
        print("  → 429でも画像400でもない別根(403/404/503等)。ラダー並べ替えでは直らない=個別に見る。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
