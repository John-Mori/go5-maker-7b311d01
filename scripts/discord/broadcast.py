#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全部門への一斉告知(**人間向け限定**。部門への周知にこれを使ってはいけない)。

★★ 重要(2026-07-20 に判明) ★★
  このスクリプトの送信は **デーモンには一切届かない**。
  `scripts/queue/discord_gateway.py:603` が `if m.author.bot or m.webhook_id:` で bot/webhook
  投稿を取り込み対象から除外しており、persona_send は webhook 送信だから。
  ★出典のパスに注意(2026-08-23 HQ実測)= gateway は **`scripts/queue/`** に居る。
    `scripts/discord/` を見て「無い」と結論した実例がある。同じ弾き方の行は
    `scripts/discord/inbox_poller.py:445` にもあるが、**そちらは2026-07-20に退役済み**
    (プロセス無し・タスク登録無し)。生きている実体は上の1行だけだ。
  実際に全20部門へ長文を配ったが、受信したデーモンは0体だった(人間がスクロールするだけの演出)。

  **部門にルールを効かせる正しい経路** = `00_AI-HQ/周知メモ.md` を編集して
  `python 00_AI-HQ/scripts/sync_broadcast.py --apply`。
  dept_daemon は毎回 characterfile を読み直すので、転記すれば次の発話から効く(艦隊再起動も不要)。

  このスクリプトを使ってよいのは「**Chamiに読ませたい人間向けの告知**」だけ。
  その場合も全部屋へ配らず `--dept hq` か `--dept report-notify` へ1通で足りることが多い。


使い方:
    python scripts/discord/broadcast.py --body-file <path> --dry-run   # 宛先だけ確認
    python scripts/discord/broadcast.py --body-file <path>             # 実送信

配送者=**オタコン**(report-notify の Head of Communications=報告責任者)。
組織設計上、横断告知の配送はreport-notifyの職務なので、各部屋の常駐キャラを騙らずオタコンが届ける
(RULES §7 部門アクセス境界=各人格は自分の部門にのみ入室。横断配送はcomms役の正規職務)。

★宛先から外すもの(意図的):
  - 機微・個人の部屋(dream-care=PROTOCOL管轄 / health-log=健康記録 / past-room / future-room)
  - 純ユーティリティ(router=通知受付 / meeting-a,b=会議室 / imagegen)
  業務部門にだけ配る。全チャンネルへ撒くと機微室が業務通知で汚れる。
"""
import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PERSONA_SEND = os.path.join(ROOT, "scripts", "discord", "persona_send.py")

# 業務部門(=告知の宛先)。dept キーで指定する。
DEPTS = [
    "hq",                # 研究室HQ
    "research-room",     # G5事業部の研究室
    "system-engineer",   # バックエンド部門α
    "system-engineer-b",  # バックエンド部門β
    "ai-office",         # バックエンド部門γ
    "frontend",          # フロントエンドデザイン
    "data-org",          # データ整理
    "qa-reviewer",       # 品質管理
    "product-scout",     # 商品候補選定
    "copy-director",     # タイトル文相談及び創造
    "shorts-analyst",    # 分析
    "hr-room",           # 人事-補強
    "hr-context",        # 人事-コンテキスト
    "kaizen-analyst",    # 改善提案
    "incident",          # システム事故対・復旧
    "report-notify",     # 報告通知
    "learning-coach",    # 学習ルーム
    "llm-edu",           # ローカルllm教育
    "llm-growth",        # ローカルllm成長進捗
    "consult-intel",     # コンサル情報
]

SENDER = "オタコン"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--persona", default=SENDER)
    a = ap.parse_args()
    if not os.path.exists(a.body_file):
        sys.exit(f"本文が見つからない: {a.body_file}")
    print(f"配送者={a.persona} / 宛先={len(DEPTS)}部門")
    if a.dry_run:
        for d in DEPTS:
            print("  (dry-run)", d)
        return
    ok, ng = [], []
    for d in DEPTS:
        r = subprocess.run(
            [sys.executable, PERSONA_SEND, "--dept", d, "--persona", a.persona,
             "--body-file", a.body_file],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        line = (r.stdout or r.stderr or "").strip().splitlines()
        tail = line[-1] if line else ""
        if r.returncode == 0 and "204" in tail:
            ok.append(d)
            print(f"  [OK] {d}")
        else:
            ng.append(d)
            print(f"  [NG] {d}: {tail[:120]}")
        time.sleep(1.2)  # Discordのレート制限を踏まない
    print(f"\n送信成功 {len(ok)} / 失敗 {len(ng)}")
    if ng:
        print("失敗:", "、".join(ng))
    sys.exit(0 if not ng else 1)


if __name__ == "__main__":
    main()
