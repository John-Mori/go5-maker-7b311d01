#!/usr/bin/env python3
"""インシデント台帳の採番を検査する (2026-07-17 Chami承認・改修β)。

なぜ要るか(INC-88の番号衝突で判明):
  インシデント.mdの採番は「台帳を開いた時の最大値+1を各セッションが自分で取る」
  =**早い者勝ちの共有カウンタ**だった。並行セッションが増えた結果、改修βと別セッションが
  2分違い(02:45:43 / 02:47:47)で同じINC-88を書き、台帳に同一番号が2件並んだ。
  人の注意では防げない(相手が今まさに書いていることは見えない)ので機械に見張らせる。

できること:
  (既定)   重複した番号・欠番を検出して報告する。重複があれば exit 1
  --next   次に空いている番号を印字する(採番前にこれを引く)
  --quiet  問題がなければ何も言わない(フック向け)

使い方:
  python scripts/kaizen/check_incident_ids.py            # 検査
  python scripts/kaizen/check_incident_ids.py --next     # 次の番号を取得
  python scripts/kaizen/check_incident_ids.py --quiet    # commit前フック向け

★限界(正直に書く・過大報告をしない=INC-84の教訓):
  これは**衝突を防ぐ道具ではなく、衝突に気づく道具**。各セッションは自分の作業コピーを
  持つため、2人が同時刻に同じ番号でcommitする競合そのものは消せない。ただし
  「静かに重複したまま残る」状態は消える——pullして次にこれを走らせた瞬間に落ちる。
  構造的に殺すなら採番自体をやめる(INC-日付-部門 等の衝突しないIDへ規約変更)しかないが、
  それは規約(研究室の所有)の話なので、ここでは提案に留める。
"""
import os
import re
import sys

try:                                   # cp932環境で絵文字・日本語を印字して落ちるのを防ぐ
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                      # (別セッションがtriage_inbox.pyで踏んだ穴。定型として写す)
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LEDGER = os.path.join(ROOT, "インシデント.md")
HEADING = re.compile(r"^##\s*INC-(\d+)\b\s*(.*)$")


def scan(path=LEDGER):
    """台帳を読み [(番号, 行番号, 見出し)] を返す。"""
    found = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            m = HEADING.match(line.rstrip("\n"))
            if m:
                found.append((int(m.group(1)), lineno, m.group(2).strip()))
    return found


def duplicates(entries):
    """番号 -> [(行番号, 見出し)] を、2件以上あるものだけ返す。"""
    by_no = {}
    for no, lineno, title in entries:
        by_no.setdefault(no, []).append((lineno, title))
    return {no: rows for no, rows in by_no.items() if len(rows) > 1}


def gaps(entries):
    """連番の欠番(記録の消失を疑う手がかり)。"""
    nos = sorted({no for no, _, _ in entries})
    if not nos:
        return []
    return [n for n in range(nos[0], nos[-1] + 1) if n not in set(nos)]


def next_no(entries):
    return (max((no for no, _, _ in entries), default=0)) + 1


def main():
    args = sys.argv[1:]
    quiet = "--quiet" in args

    if not os.path.exists(LEDGER):
        print(f"NG: 台帳が見つからない: {LEDGER}")
        return 2

    entries = scan()
    if "--next" in args:
        print(f"INC-{next_no(entries)}")
        return 0

    dups = duplicates(entries)
    if dups:
        print(f"NG: 番号が重複している ({len(dups)}件) — 台帳: {LEDGER}")
        for no in sorted(dups):
            print(f"  INC-{no}:")
            for lineno, title in dups[no]:
                print(f"    行{lineno}: {title}")
        print(f"  → 後から書いた側を INC-{next_no(entries)} 以降へ振り直す")
        print("  → 採番の前に `--next` を引けば次から避けられる")
        return 1

    missing = gaps(entries)
    if not quiet:
        print(f"OK: INC番号に重複なし ({len(entries)}件・次は INC-{next_no(entries)})")
        if missing:
            print(f"  参考: 欠番 {', '.join('INC-' + str(n) for n in missing)}"
                  " (意図的な欠番なら無視してよい)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
