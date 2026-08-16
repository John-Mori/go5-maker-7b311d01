# -*- coding: utf-8 -*-
"""
persona_changelog.py  —  人格設定「そのキャラだけ参照」の変更台帳(hrツール・C-019)

Chami依頼(2026-08-16 msg 1538503151663976588 / 元 1538499998671568906)の
トークン節約機構:「変更したらそのキャラについてここで言う→そのキャラだけ参照する。
全部参照するのを防ぐ」を、心がけでなく機械に載せる(共通規律§3)。

- add : 1キャラ・1面(呼称/口調/アイコン/原典/文脈)の変更を1行だけ追記(追記のみ・既存行は書き換えない)。
- show: 指定キャラの変更履歴だけを返す(全キャラを読み直さない=参照範囲がキャラ1体に閉じる)。

台帳= local/persona_changelog.jsonl(1行=1変更)。
これは正本ではなく派生の索引=設定の正本(呼称ルール.json/口調ルール.json/persona_avatars.json)は増やさない。

使い方:
  python scripts/hr/persona_changelog.py add --char 花海咲季 --面 口調 --what "手ぇをforbiddenに追加" --by ククール
  python scripts/hr/persona_changelog.py show --char 花海咲季
"""
import argparse, json, os, sys
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
LOG = os.path.join("local", "persona_changelog.jsonl")
FACES = ("呼称", "口調", "アイコン", "原典", "文脈")


def _now_jst():
    return datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def add(args):
    if args.face not in FACES:
        print(f"[error] --面 は {FACES} のどれか。受け取った: {args.face}", file=sys.stderr)
        return 2
    row = {
        "ts": _now_jst(),
        "キャラ": args.char,
        "面": args.face,
        "何を": args.what,
        "誰が": args.by,
    }
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    # 追記のみ。json.dumps でエスケープを機械に任せる(生JSONを手打ちしない)。
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("appended:", json.dumps(row, ensure_ascii=False))
    return 0


def show(args):
    if not os.path.isfile(LOG):
        print(f"(まだ変更履歴なし: {LOG})")
        return 0
    hits = []
    with open(LOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("キャラ") == args.char:
                hits.append(r)
    if not hits:
        print(f"({args.char} の変更履歴は無し=このキャラは既定のまま)")
        return 0
    print(f"# {args.char} の変更履歴 ({len(hits)}件・新しい順)")
    for r in reversed(hits):
        print(f"- {r.get('ts')}  [{r.get('面')}] {r.get('何を')}  (by {r.get('誰が')})")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="1キャラの変更を1行追記")
    a.add_argument("--char", required=True, help="キャラ名(persona名)")
    a.add_argument("--面", dest="face", required=True, help=f"変更した面 {FACES}")
    a.add_argument("--what", required=True, help="何を変えたか(日本語1文)")
    a.add_argument("--by", required=True, help="誰が")
    a.set_defaults(func=add)

    s = sub.add_parser("show", help="指定キャラの変更履歴だけを返す")
    s.add_argument("--char", required=True)
    s.set_defaults(func=show)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
