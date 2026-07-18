#!/usr/bin/env python3
"""ペルソナ台帳の整合チェッカー(読み取り専用・人事の点検を機械化)。

なぜ要るか:
  2026-07-16、Chamiの「デブライネ表記に統一して」の一言で、人事は手作業grepで9ファイルを追った。
  同日、全キャラのアイコン34件が一斉に署名失効していたのにChamiの指摘まで誰も気づかなかった。
  どちらも「人間が気づけるか」に依存していた=次も落とす。今日の手作業をそのまま機械にする。

  設計= docs/departments/hr-room/設計書_人事部門改善_2026-07-17.md §4.2

チェック内容:
  1. 退役した旧表記の混入(例 デ・ブライネ→デブライネ)
  2. 禁止句(例「刻んだ」=Chami指示2026-07-16で全キャラ廃止)
  3. 台帳のキャラにアバターキーが無い(=その名前で投稿すると顔なしになる)
  4. アバターURLの失効(refresh_avatars.py --check へ委譲)

対象外(意図的に触らない・§設計書の「意図的に残した3箇所」と同じ理由):
  - Chamiの過去発言ログ(local/*.jsonl等) = 書き換えは記録の改竄。旧表記が出て当然
  - 引き継ぎ書/過去の設計書 = 当時の記録。当時の呼称のまま据え置くのが組織の原則
  - .claude/worktrees/ = 別セッションの隔離作業コピー
  - persona_avatars.json の旧キー = 名前ゆれ吸収の保険(alias)。あって正しい

使い方:
  python scripts/kaizen/check_persona_consistency.py           # 全チェック
  python scripts/kaizen/check_persona_consistency.py --no-net  # URL到達性を省く(オフライン/高速)
終了コード: 0=問題なし / 1=要対応あり
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))

# 1. 退役表記: (旧, 正, 理由)
RETIRED = [
    ("デ・ブライネ", "デブライネ", "Chami指示2026-07-16「・を抜いてデブライネ表記に」"),
]
# 2. 禁止句: (語, 理由)
BANNED = [
    ("刻んだ", "Chami指示2026-07-16・全キャラ廃止(締めの定型句)"),
]

# 走査対象=現行の規約・運用文書のみ
SCAN_DIRS = ["docs/departments"]
SCAN_FILES = ["local/llm/knowledge.md", "CLAUDE.md"]
SCAN_EXT = (".md", ".yml", ".yaml")

# 除外(記録・履歴・別セッションの作業場)
EXCLUDE_PARTS = (
    os.sep + ".claude" + os.sep,
    os.sep + "__pycache__" + os.sep,
    os.sep + "設計・調査" + os.sep,   # 過去の設計書=当時の記録
)
EXCLUDE_NAME_PAT = re.compile(r"(引き継ぎ|handoff|司令塔ログ|インシデント)", re.I)


def rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


def scan_targets():
    out = []
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        for dirpath, _dirnames, filenames in os.walk(base):
            if any(part in dirpath + os.sep for part in EXCLUDE_PARTS):
                continue
            for fn in filenames:
                if not fn.endswith(SCAN_EXT):
                    continue
                if EXCLUDE_NAME_PAT.search(fn):
                    continue
                out.append(os.path.join(dirpath, fn))
    for f in SCAN_FILES:
        p = os.path.join(ROOT, f)
        if os.path.isfile(p):
            out.append(p)
    return out


def read(p):
    try:
        return io.open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


# 誤検知よけ: 旧語を「語るために」書いている行は正しい。実測で必要になった除外(2026-07-17)
#   ①Chamiの発言引用ログ(knowledge.mdは会話ログから生成される。Chami原文の旧表記は改竄しない)
#   ②ルール定義文(「旧『デ・ブライネ』」「デ・ブライネ→デブライネ」「退役語リスト」等)
QUOTED_LOG_PAT = re.compile(r"^\s*[-*]?\s*\[\d{4}-\d{2}-\d{2}")


def _is_rule_talk(line, old, new):
    """この行は旧語を『規則として説明している』か(=正しい行)。"""
    if QUOTED_LOG_PAT.match(line):
        return True                      # Chamiの発言引用ログ
    if new in line:
        return True                      # 新旧を併記=対比・移行の説明
    return any(w in line for w in ("退役", "旧表記", "旧「", "禁止", "廃止", "誤り"))


def check_retired_and_banned(problems, notes):
    files = scan_targets()
    notes.append(f"走査対象: {len(files)}ファイル(現行の規約・運用文書のみ。ログ/引き継ぎ/worktreeは対象外)")
    for p in files:
        for i, line in enumerate(read(p).splitlines(), 1):
            for old, new, why in RETIRED:
                if old in line and not _is_rule_talk(line, old, new):
                    problems.append(f"[旧表記] {rel(p)}:{i} 「{old}」→「{new}」 ({why})")
            for word, why in BANNED:
                if word in line and not any(w in line for w in ("禁止", "廃止", "使わない")):
                    problems.append(f"[禁止句] {rel(p)}:{i} 「{word}」 ({why})")


def index_personas():
    """personas/INDEX.md の**名簿表だけ**からキャラ名を取る。

    INDEX.mdには名簿表のほかに呼称マトリクス・改修3部屋の表もあるため、
    ヘッダ「| キャラ名 |」で始まる表に入ってから空行までを名簿とみなす
    (全ての表を読むと「部屋」等を人名と誤認する=2026-07-17実測)。
    """
    p = os.path.join(ROOT, "docs", "departments", "personas", "INDEX.md")
    names, in_roster = [], False
    for line in read(p).splitlines():
        if line.startswith("|") and "キャラ名" in line:
            in_roster = True
            continue
        if in_roster:
            if not line.startswith("|"):
                break                                  # 表の終わり=名簿はここまで
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            name = cells[0] if cells else ""
            if not name or set(name) <= set("-: "):
                continue
            names.append(re.sub(r"\(.*?\)", "", name).strip())
    return names


def check_avatar_keys(problems, notes):
    p = os.path.join(ROOT, "local", "persona_avatars.json")
    if not os.path.isfile(p):
        notes.append("persona_avatars.json が無い(スキップ)")
        return
    try:
        keys = set(json.load(io.open(p, encoding="utf-8")).keys())
    except (OSError, ValueError) as e:
        problems.append(f"[台帳] persona_avatars.json を読めない: {type(e).__name__}")
        return
    # ★判定は完全一致。persona_send.py は json.get(persona) で引くため、
    #   部分一致では引けない(甘く判定すると顔なし投稿を見逃す=2026-07-17に判定を厳格化)。
    missing, drift = [], []
    for name in index_personas():
        if not name:
            continue
        if name in keys:
            continue
        near = [k for k in keys if name in k or k in name]
        (drift if near else missing).append((name, near))
    for m, near in drift:
        problems.append(f"[表記ゆれ] 台帳の「{m}」に完全一致キーが無い(近いキー={near})。"
                        "persona_sendは完全一致でしか引かないので、この名前で投稿すると顔なしになる")
    for m, _ in missing:
        problems.append(f"[アイコン欠落] 台帳のキャラ「{m}」の画像が未登録"
                        "(この名前で投稿すると顔なし。Chamiに画像を依頼する)")
    notes.append(f"アバターキー: {len(keys)}件 / 完全一致で引けない台帳キャラ: "
                 f"{len(missing)+len(drift)}件(未登録{len(missing)}・表記ゆれ{len(drift)})"
                 " ※余ったキー=名前ゆれ吸収の保険(alias)なので正常")


def check_avatar_urls(problems, notes):
    script = os.path.join(ROOT, "scripts", "discord", "refresh_avatars.py")
    if not os.path.isfile(script):
        notes.append("refresh_avatars.py が無い(URL点検スキップ)")
        return
    try:
        r = subprocess.run([sys.executable, script, "--check"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=180)
    except (OSError, subprocess.TimeoutExpired) as e:
        notes.append(f"URL点検を実行できず: {type(e).__name__}")
        return
    tail = (r.stdout or "").strip().splitlines()
    last = tail[-1] if tail else ""
    m = re.search(r"到達不可\s*(\d+)\s*件", last)
    if m and int(m.group(1)) > 0:
        problems.append(f"[アイコン失効] {last} → `python scripts/discord/refresh_avatars.py --all` で再署名する"
                        "(2026-07-16に全34件が一斉失効した実績あり)")
    else:
        notes.append(f"URL点検: {last or 'OK'}")


def main():
    ap = argparse.ArgumentParser(description="ペルソナ台帳の整合チェック(読み取り専用)")
    ap.add_argument("--no-net", action="store_true", help="URL到達性チェックを省く")
    args = ap.parse_args()

    problems, notes = [], []
    check_retired_and_banned(problems, notes)
    check_avatar_keys(problems, notes)
    if not args.no_net:
        check_avatar_urls(problems, notes)

    print("=== ペルソナ整合チェック ===")
    for n in notes:
        print(f"  - {n}")
    if problems:
        print(f"\n★要対応 {len(problems)}件:")
        for x in problems:
            print(f"  ✗ {x}")
        return 1
    print("\n問題なし。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
