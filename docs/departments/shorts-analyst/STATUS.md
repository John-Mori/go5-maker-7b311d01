# STATUS.md — 分析部門(shorts-analyst)未クローズ案件台帳

> 運用: open案件は必ずここへ(セッションの記憶に置かない=INC-96対策)。1件=1行+待ち先+期限。クローズ時は[済]を付けて日付。新しい項目を上へ。

## open

- [ ] **headlessパイロットの実装待ち**(Chami一任承認2026-07-18 msg_id=1527918083971481660→分析部門で方法選定=段階移行パイロット)。仕様書=実装計画書_headlessパイロット_2026-07-18.md・起動プロンプト=BOOT_headless.md・改修部門chへ依頼送付済(HTTP 204)。QA合格→waiter停止→1週間実測→全体展開判断。**それまで現行waiter運用を継続**(二重応答防止)。待ち先=system-engineer。
- [ ] **パイロット後の後続キュー**(順不同・一斉にやらない): cloudflare公式MCP登録/promptfoo回帰3件/basic-memory PoC/Hermes Kanban D1移植設計書。出典=調査書_エージェントOSSと恒久改善_2026-07-18.md §3。

- [ ] **週次便のフルセット化**: 初回便はdeltas+historyのみ(エンゲージメント・go5_fanza販売数は未取得と便内で明記)。次便からBluesky getPostsとD1販売数を含める。待ち先=自部門。期限=2026-07-25(第2便)。
- [ ] **data-paths.mdのexec URL正本ポインタ訂正**: qa-reviewer STATUS.md §3-2ではなく docs/設計・調査/STATUS.md が実所在[実測2026-07-18]。次のdoc編集時に相乗り修正。待ち先=自部門。
- [ ] **GAS無認証delete是正の完了待ち**(gas/コード.gs:174 action=delete・:178 snapshot_now)。エスカレ済2026-07-18(改修-依頼ch・HTTP 204)。待ち先=system-engineer。完了確認=qa-reviewer所掌。是正完了までGAS読み出しaction追加提案(records/stats_range)は凍結。
- [ ] **採用KPI計測**: menu掲示(2026-07-18)後の依頼数/週・便への反応を観測。2026-08-01時点でゼロ継続なら設計書§7どおり撤退基準の発動を自ら提案。待ち先=自部門。
- [ ] **dept_tasksイベント生産者の稼働確認**(post.published/metrics.updated/competitor.weekly_digest が実際にdept_tasksへ発行されているか)。確認できるまで毎起床の掃引は有効化しない。待ち先=研究室に確認(次の横断連絡に相乗り)。期限=2026-08-01。
- [ ] **inbox_waiter.py:35 docstring旧値(90秒→600秒)の相乗り指摘**。dept_tasks起票はしない。待ち先=system-engineerが次に同ファイルを触る時(エスカレ文2026-07-18に備考として記載済)。

## closed

- [済 2026-07-18] **週次数字便の初回実行**: 本番TTL満了起床で発火[実測]。deltas+history取得→SA-H002登録→便送信(HTTP 204)→マーカー更新。ID体系2系統の発見(指標辞書へ訂正済)。
- [済 2026-07-18] 設計書_分析部門セッション改善の作成→Chami裁定「1A 2A 3A」受領→即日実装バッチ(BOOT/menu/報告様式/SA-H001/STATUS/指標辞書/data-paths/衛生)完了。
- [済 2026-07-18] handoff_イベント駆動ウェイク検討.mdクローズ(inbox_waiter実装済・歴史文書化)。
