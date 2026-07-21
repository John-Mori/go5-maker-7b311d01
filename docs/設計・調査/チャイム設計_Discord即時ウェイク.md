# チャイム設計 — Discord発言でAIセッションを即座に叩き起こす仕組み

> 起票: 2026-07-15 / Chami×司令塔（エージェント群から独立した設計セッション）
> 目的: Chamiの「Discordで何度話しても応答しない」を根治する。
> 制約: 待機中はClaudeトークンを消費しない・無料・裏で静かに動く（＝家の前のチャイム）。

---

## 0. 問題の正体（診断結果）

**受信は壊れていない。起床が壊れている。**

| 段 | 現状 | 状態 |
|---|---|---|
| 受信 | `inbox_poller.py` が15秒毎にDiscordを巡回→部門箱/main箱へ配達（純Python・トークン0） | ✅稼働中 |
| 起床（部門） | heartbeatのTTL満了通知（**最大10分後**）でしか起きない。さらに「アイドル時は脈を切らす」裁定で待機部門は脈なし→main箱行き | ❌ベルが無い |
| 起床（main） | ScheduleWakeup約90秒の自己巡回。**再スケジュール忘れ・セッション終了・長考で鎖が切れる**と誰も箱を読まない | ❌鎖が脆い |

エージェントの「会話を拾えていなかった」＝箱は満杯なのにベルが鳴らなかった、が真因。

## 1. 核心のアイデア: バックグラウンドタスクの終了通知＝チャイム線

Claude Codeは「セッションが起動したバックグラウンドプロセスが**終了**すると、
そのセッションに task-notification が届き**自動で1ターン起きる**」。
→ 「箱を見張り、メッセージが入った瞬間に終了するプロセス」を各セッションが飼えば、
**メッセージ到着＝即ウェイク**になる。待機中はただのPythonのファイル監視＝トークン0・無料。

これは分析部門の検討メモ（`docs/departments/shorts-analyst/handoff_イベント駆動ウェイク検討.md`）
の waiter 案と同一。本設計はそれを採用し、§4の未解決トレードオフ（TTL）に解を与える。

## 2. 構成（3部品）

```
Chami発言 → [inbox_poller](既存・15s) → local/inbox/<dept>.jsonl
                                              │ (ファイルに行が増える)
                                              ▼
              [inbox_waiter.py](新規) ← 各セッションが飼う番犬
                 ・2秒毎に自分の箱をstat（純Python・タダ）
                 ・脈ファイル(claude_active_<dept>.txt)もtouch（配達先維持）
                 ・箱が非空になった瞬間 exit 0 (marker=message)
                                              │ (プロセス終了)
                                              ▼
              task-notification → Claudeセッションが即1ターン起床 → 箱を処理 → waiter再武装
```

### 部品A: `scripts/llm/inbox_waiter.py`（新規・チャイム線）

```
python scripts/llm/inbox_waiter.py --name <dept|main> [--minutes 45] [--interval 2]

for i in range(TTL/interval):          # INC-091: 必ず有限ループ
    touch claude_active_<name>.txt     # 脈=配達先の維持（20秒毎で十分・毎回でも害なし）
    if 箱が非空: exit(print "WAITER:MESSAGE")   # ←チャイム鳴動
    sleep 2秒
exit(print "WAITER:TTL")               # 満了=静かな定期点検ターン
```

- 監視対象: `--name main` → `local/discord_inbox.jsonl` / 部門 → `local/inbox/<dept>.jsonl`
- 「非空」の判定は**行数がウェイク時点の基準行数を超えた**とき（処理側が消費して空にする現運用ならサイズ>0でよい。堅くするなら起動時サイズを基準に増分検知）
- heartbeat.py の touch 関数を流用。**heartbeatの置き換え**であり併用しない（二重脈の混乱防止）
- 終了messageは1行だけ（起床ターンのノイズ最小化）

### 部品B: 運用ルール変更（BOOT/orchestration.md）

- 各セッションは起動時と各作業完了時に `inbox_waiter.py` を **run_in_background で再武装**
  （heartbeat再武装と同じ習慣。コマンドが変わるだけ）
- **mainも同じwaiterを飼う**: ScheduleWakeup約90秒巡回は廃止し、
  「waiterが鳴ったら起きる」＋「ScheduleWakeupは30〜60分の長い保険」へ。
  → main のアイドルトークンが 40ターン/時 → ほぼ0 に激減（副次効果）
- **7/15裁定「アイドル時は脈を切らす」の更新が必要**:
  旧世界では脈維持=10分毎のトークン浪費だった。waiter世界では待機=無料、
  費用はTTL満了ターン（45分に1回程度）のみ。**「待機中もwaiterは飼っておく」が新しい正**。
  ※裁定の変更なのでChami承認事項（§5）

### 部品C: 見張りの強化（自己修復・既存の延長）

waiter が保証するのは「セッションが生きていれば即起きる」まで。残りの穴は既存機構が塞ぐ:

1. **セッションがフリーズ**: waiterは鳴って終了済み→誰も再武装しない→90秒で脈が死ぬ→
   `sweep_stale_dept_boxes()`（既存）が箱をmainへ回収→mainのwaiterが鳴る。**自動フェイルオーバー成立**。
   ※handoff§4が恐れた「偽生存」は**無限waiter**の問題。exit-on-message型は鳴った時点で脈の供給が止まるため、構造的に偽生存しない。
2. **mainも死んでいる**: `absence_watchdog.py`（既存・60秒巡回）がmain箱の15分滞留を検知して
   incident chへ通知。→ **部門箱の滞留監視も追加**（脈が新鮮なのに箱がN分減らない=フリーズ検知→incident通知）。
3. **ポーラー自体が死ぬ/PC再起動**: タスクスケジューラでログオン時自動起動
   （inbox_poller / absence_watchdog）。watchdogにポーラー死活確認を1行追加。

## 3. 応答レイテンシ（設計値）

| 経路 | 現状 | 本設計 |
|---|---|---|
| 部門セッション稼働中 | 最大10分（heartbeat TTL） | **最大17秒**（poll15s+watch2s） |
| 部門不在→main受け | main巡回90秒（鎖が無事なら） | **最大17秒** |
| セッションフリーズ | 検知なし（無反応のまま） | 90秒で脈死→mainへ回収→mainが即応 |
| main含め全滅 | absence_watchdogの15分通知のみ | 同左（通知でChamiが把握） |

さらに縮めたい場合の**Phase 2（任意）**: Discord Gateway(WebSocket)常駐ボット
（discord.py・無料）が on_message で `local/bell/poke` をtouch→pollerが即時1巡回。
レイテンシ15秒→約3秒。ただし常駐+1・依存ライブラリ+1なので、まず15秒運用で困ってから。

## 4. トークン経済（待機コストの変化）

| | 現状 | 本設計 |
|---|---|---|
| main待機 | ScheduleWakeup 90秒 ≒ 40ターン/時 | TTL満了 1〜2ターン/時 |
| 部門待機(脈あり時) | heartbeat満了 6ターン/時 | TTL満了 1〜2ターン/時 |
| メッセージ応答 | （起きたついでに処理） | 1件=1起床ターン（純イベント駆動） |

## 5. Chami承認が要る判断点

1. **waiterのTTL値**: 推奨45分（idle約1.3ターン/時。フリーズ回復は§2-Cで担保済なのでTTLは回復速度に影響しない→長くてよい）
2. **「アイドル時は脈を切らす」裁定の更新**: 待機中もwaiterを飼う（=脈が立ち続ける）ことの承認
3. **mainのScheduleWakeup 90秒巡回の廃止**（30〜60分の保険化）
4. Phase 2（Gateway即時化）を今やるか、15秒運用で様子見か → 推奨は様子見

## 6. 実装タスク（2026-07-15 実施状況）

- [x] `scripts/llm/inbox_waiter.py` 新規（レベル駆動=非空で鳴る・有限TTL45分・`--once`点検・脈touch兼任）。サンドボックス試験4種PASS（新着/既存滞留/TTL満了/once）
- [x] `absence_watchdog.py` 拡張: **ポーラー死活監視**（`poller_active.txt`鮮度>120秒でincidentへ・受付箱滞留と独立・30分クールダウン）。試験4種PASS（脈なし/新鮮/古い/クールダウン）
- [x] `inbox_poller.py`: 巡回毎に`local/llm/poller_active.txt`を更新（死活脈）
- [x] `scripts/llm/start_inbox_waiter.bat` 新規（手動/常駐確認用・name引数対応）
- [x] `orchestration.md`/`BOOT_main.md`/`BOOT_TEMPLATE.md`: heartbeat再武装→waiter再武装へ書き換え。メモリ3件更新（chime-inbox-waiter新規/idle反転/auto-poll置換）
- [ ] **残**: 各部門の個別`BOOT.md`（system-engineer/hr-room等）への一斉展開（テンプレは更新済・個別展開は次段）
- [ ] **残**: 部門箱の「フリーズ滞留」監視（脈は新鮮なのに箱がN分減らない検知）。sweep失敗時の保険。sweep＋TTLで基本は足りるため優先度中
- [ ] **残**: タスクスケジューラ登録（poller/watchdogのログオン時自動起動）.bat と手順md
- [ ] **残**: main運用でScheduleWakeup 90秒巡回を実際に停止し長い保険へ（司令塔セッション側の運用切替）
- [ ] **残**: 実セッションでの一気通貫試験（部門窓→実Discord発言→起床→返信、フリーズ模擬→main回収）
- [ ] **任意**: Phase 2（Discord Gateway常駐で15秒→3秒）

## 7. やらないこと

- BGM…ではなく: waiterの無限ループ化（INC-091厳守・有限TTL）
- 脈touchをClaude外の常駐に出すこと（偽生存の再導入）
- `claude -p` 等でセッションを外から新規起動すること（トークン消費・別論点。閉じている部門はmainが受ける現設計で足りる）
