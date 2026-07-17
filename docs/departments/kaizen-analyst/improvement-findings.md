# 改善の発見・提案台帳 (kaizen-analyst)

> 運用: 結論先頭・1項目=数行・新しい項目を上へ。この部門だけが更新する(他部門はinsight経由で提案)。
> **台帳規約**: 提案は PRO-NNN(部門横断の集約提案)/ KZ-NNN(この部門の能動提案)で採番。状態語彙 = `proposed → presented → approved / rejected / deferred → implemented → measured`。正本はD1 `improvement_insights`(status列)、ここは人が読む1行索引。番号だけでChamiが返事できる形で提示する。

## 提案台帳(新しい順)

| 番号 | 状態 | タイトル | コスト/金銭 | 出典 |
|---|---|---|---|---|
| KZ-006 | approved | インシデント記録Skill(記録漏れ防止・INC-83の抜けを塞ぐ) | 小/なし | Chami承認2026-07-18「全部」 |
| KZ-005 | approved | 投稿前チェックSkill(規約防衛=露出/2ch重複/煽り/2段リンク)★先行 | 小/なし | Chami承認2026-07-18「全部」 |
| KZ-004 | approved | デプロイ反映Skill(?v=バンプ→commit→pull rebase→push→検証) | 小/なし | Chami承認2026-07-18「全部」 |
| KZ-003 | implemented | 各LLM/部門の「できるようになったこと」定型報告(週次便に組込) | 小/なし | Chami承認2026-07-18「両方go」 |
| KZ-002 | deferred | 投稿の相関ビュー(時刻×曜日×作品×再生数) | 中/なし | Chami要望 se 2026-07-17。競合サーチ設計(a0e4ab7)と要整合 |
| KZ-001 | implemented | 承認疲れの解消(settings.local.jsonへ安全コマンド13件を事前許可) | 小/なし | Chami承認2026-07-18「両方go」 |
| P-1〜P-7 | implemented | 改善提案部門の再設計(週次便・台帳・趣向DB他) | 小〜中/なし | Chami承認 2026-07-17「全て実装よろしく」 |

## 発見メモ
- 2026-07-17: この部門は発足(07-15)前に全入口が停止していた(部門提案insightは07-12が最後・自部門docs3枚は空)。真因=提案を運ぶ仕組みが紙上のみ・能動起動トリガー無し・台帳無し・最濃データ(Chami発言575件/git/INC)が分析対象外。→ 再設計(設計書_改善提案部門の再設計.md)で是正。
- 2026-07-17: 分析ツール summarize_chami_chats.py 初版が機微部屋(past-room/dream-care)を無フィルタで拾う欠陥。SENSITIVE_DEPTS除外で即是正(記録前に発見・機微は未記録)。
- 2026-07-18: 本設計書がuntrackedのまま並列セッションのgit操作で消失(=[[parallel-git-clobbers-worktree]]の実例)。再作成しcommitでtracked化。教訓=**部門成果物は生成後すぐcommitし、untrackedで放置しない**。
- 2026-07-18: 改善便#1のKZ-001/KZ-003をChami承認(「両方go」)。KZ-001=settings.local.jsonへ読み取り専用/定型コマンド13件を事前許可(破壊的・金銭・D1書込は除外)。KZ-003=週次便に成長ダイジェストを組込。効果測定は次便で。
- 2026-07-18: 機微部屋の扱いをChami指示で「完全除外」→「集計に含めるが生記述は伏せる・公開docsは要約のみ・生はlocal」へ調整。安全弁として公開repoの不可逆性を提示しChamiが要約方針を選択。
- 2026-07-18: Skill提案3件(KZ-004/005/006)をChami承認(「全部。廃止/更新も状況次第で任せる」)。KZ-005(投稿前チェック=規約防衛)から着手。以後、Skillの新設・廃止・更新の継続裁量を得た。
