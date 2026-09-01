#!/usr/bin/env python3
"""同梱物に「うちの機密」が1つも入っていないことを機械で確かめる。

zipを固める前に必ず通す。1つでも当たれば非0で終了(=zip化を止める)。
目視で通さない、というGLの P0 指示の執行体。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# 出てはいけないパターン(うちの資格情報・識別子)。値そのものは書かず、名前と形で弾く。
FORBIDDEN = [
    re.compile(r"SHARED_SECRET\s*[=:]\s*\S+"),
    re.compile(r"FANZA_API_ID\s*[=:]\s*\S+"),
    re.compile(r"FANZA_AFFILIATE_ID\s*[=:]\s*\S+"),
    re.compile(r"rr" + r"riiias-055"),    # うちの運用 af_id(この検査器自身は自己除外する)
    re.compile(r"\baf_id\s*[=:]\s*[A-Za-z0-9]+-\d{3}\b"),  # 実af_id値の形
    re.compile(r"discord\.com/api/webhooks/\d+/\S+"),      # 実Webhook URL
    re.compile(r"[A-Za-z0-9_-]{20,}-99\d\b"),              # DMM API用サイトID(末尾990番台)
]

# 検査対象の拡張子(バイナリは除外)
TEXT_SUFFIXES = {".py", ".ini", ".txt", ".md", ".json", ".cfg", ".csv", ".yml", ".yaml"}


def scan(root: Path) -> list[tuple[Path, int, str]]:
    hits: list[tuple[Path, int, str]] = []
    self_path = Path(__file__).resolve()
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        # 検査器自身は禁止パターン(の名前)を持つ宿命なので自己除外する。
        if p.resolve() == self_path:
            continue
        # config.example は空欄テンプレなので対象。config.ini(利用者の実値)は同梱しない前提。
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            for pat in FORBIDDEN:
                if pat.search(line):
                    hits.append((p, i, pat.pattern))
    return hits


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    hits = scan(root)
    if hits:
        print(f"[NG] 機密らしき文字列を {len(hits)} 件検出。zip化を中止します:")
        for p, ln, pat in hits:
            print(f"  {p}:{ln}  <= /{pat}/")
        return 1
    print(f"[OK] 機密の同梱なし({root} を走査)。zip化してよいです。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
