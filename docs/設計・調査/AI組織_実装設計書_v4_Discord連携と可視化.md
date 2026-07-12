# AI組織 実装設計書 v4 — Discord連携・HTML教材・デザイン嗜好・可視化

作成: 2026-07-12 ／ ステータス: 設計+受け皿実装(Phase DA)
原典: `AFI_Project_Discord・HTML教材・AIオフィス可視化_追加設計.md`(Chami+ChatGPT・Downloads)
前提: v1〜v3(S0-S2構築済・稼働中)。Chami指示「原典に100%従わなくてよい・現行システムに合わせ柔軟に」に基づき、実行モデルの現実に適合させた再設計。

---

## 1. 原典からの主な適合変更(理由付き)

| # | 原典 | 本書の設計 | 理由 |
|---|---|---|---|
| 1 | Discordで即応チャット(質問→即回答) | **非同期Q&A**(質問はD1キューへ→次のClaudeセッション/定期実行が回答をスレッドへ返す) | Claude Codeは常駐デーモンではない。即応を装うより正直な遅延設計(原典自身の「偽表示禁止」と同思想)。将来Local LLM/API常駐で短縮可 |
| 2 | HTML教材のPublish先を新設 | **Artifactツールを主方式**(claude.ai・既定非公開・スマホ最適・URL共有可) | 新インフラ0で今日から使える。リポジトリ(Pages公開)に教材を置かない=戦略非公開ルールとも整合。副方式=Discordへファイル添付 |
| 3 | agent_registry/agent_status/heartbeats等の6表 | **作らない**(dept_tasks/dept_events/system_changes/user_events=既存4表から状態を導出) | 部門はスポーン型(エフェメラル)でハートビートは構造的に嘘になる。原典の最重要原則「見た目だけの演出にしない・偽Status禁止」に従うと、既存タスク/イベントが唯一の正直なSource of Truth |
| 4 | design_references等のD1 4表を先行作成 | **local/design-refs/(非公開フォルダ)で開始**、D1化は利用実績が出てから | 記録粒度規約と同思想(使われないテーブルを作らない)。デザイン参考資料は画像/HTML実物なのでファイルが自然 |
| 5 | 部屋型AIオフィスUI | **段階後置**(まずテキスト/簡易HTMLのstatus要約→部屋型はキャラ(S7)と同時期) | 現部門はスポーン型で「今働いている」瞬間が短い。常時表示に耐える絵はタスク・イベント履歴ベースで十分。キャラ完成後にまとめて作る方が二度手間がない |
| 6 | Discord Channel構成(4カテゴリ) | 採用(そのまま)。ただし既存ニュース配信とは完全分離 | 原典どおり |

## 2. 全体構造(適合版)

```
Chami ⇄ Discord(入口/出口) ⇄ 受け渡し層 ⇄ AI組織本体(既存: 司令塔+7部門+D1 go5_kaizen)
        └ スマホ閲覧: Artifact URL(教材) / Discord通知

受け渡し層(新規・軽量):
  OUT: scripts/kaizen/discord_notify.py … Webhook POST(通知/レポート/教材URL)
  IN : Discord質問 → D1 learning_questionsへキュー(Phase DBで常駐bot) → セッションが回答
```
- Discordにロジックを置かない(原典どおり)。状態・記録は全てD1+docs(既存)が正
- 秘密: Webhook URL/BotトークンはD:配下`local/`(gitignore済)に保存。リポジトリ・D1に書かない

## 3. 段階導入(Phase DA〜DF)

| Phase | 内容 | 必要なChami作業 | 状態 |
|---|---|---|---|
| **DA 通知(OUT)** | discord_notify.py(汎用Webhook送信)+手順書。用途: デプロイ/Incident/朝レポート/改善提案/教材URL | ★DiscordサーバーでWebhook作成→URLを`local/discord_webhook.txt`に保存(手順=`local/discord_setup.md`) | **受け皿実装済**(URL待ち) |
| **DB 質問(IN)** | PC常駐ポーラー(Python stdlib・`scripts/discord/inbox_poller.py`)が**全部門ch**を監視→`local/discord_inbox.jsonl`へキュー→司令塔がセッション開始時/依頼時に振り分け処理→`bot_send.py`で発言元chへ返信。※原典のNode+discord.js(Gateway常駐)から**ポーリング方式へ適合変更**(依存ゼロ・低トラフィックな個人利用では単純で壊れにくい。送信もBotに統一しWebhook 9本を不要化) | ★Discord DeveloperでBot作成→トークンを`local/discord_bot_token.txt`+チャンネルIDを`local/discord_channels.json`(手順=`local/discord_bot_setup.md`・10分) | **受信基盤実装済**(トークン待ち) |
| **DC HTML教材** | 「HTMLで」「図解で」と言われたらArtifactで教材生成(構成=原典§7.2の11項目)→URLをDiscordへ。Visual/Educational QAチェックリスト適用 | なし(今日から使える) | **利用可能** |
| **DD デザイン嗜好** | local/design-refs/に好き嫌い実例+理由を蓄積→教材生成時に司令塔が参照。A/B比較メモ。D1化は実績後 | 良い/悪い例を投げるだけ | 受け皿=フォルダ+README |
| **DE 状態可視化** | scripts/kaizen/status_report.py(D1から部門別open/doneタスク・直近イベント・件数を要約)→Discord/コンソール。簡易HTML版はArtifactで随時 | なし | 設計のみ(次の軽作業) |
| **DF 部屋型AI Office** | キャラ(S7)完成後: local生成のHTML(部屋・アバター・吹き出し=dept_tasks/eventsから導出・偽Status禁止) | S7のキャラ共同作成 | S7と同時期 |

v3ロードマップとの関係: DA/DCは軽量なので**S1観測期間と並走可**。DB/DE以降は「基盤最優先」原則によりS3(初回分析)後を推奨。

## 4. HTML教材(Visual Learning Studio・DC詳細)

- トリガー: Chamiの明示要求(「HTMLで」「教科書のように」)/learning-coachが複雑と判定(概念数・関係数・階層で判断)
- 構成(原典採用): 30秒要約/分野/全体図/重要概念/AFIでの具体例/比較表/処理フロー/よくある誤解/理解チェック/次に学ぶ概念/関連書籍
- スマホ要件: レスポンシブ・横スクロール禁止・折り畳み・軽量(Artifactの制約=外部CDN不可がむしろ軽量化に効く)
- QA: Visual(文字サイズ/コントラスト/overflow/ありきたりAIデザイン化の抑制=design-refs参照)+Educational(正確性/前提/誤解しやすさ/AFI整合)
- 記録: 生成したらlearning_resourcesへ1行(topic/title/resource_type='html'/URL)=学習ログと紐づく

## 5. AI Office(DE/DF詳細・偽Status禁止)

- Source of Truth: dept_tasks(open/in_progress/blocked/done)+dept_events(時系列)+system_changes(デプロイ)+user_events(アプリ操作)。**これ以外の状態表示はしない**
- 表示できる正直な状態: 各部門の「未処理タスクn件/直近の完了/最終活動時刻(イベントの最新時刻)」+タイムライン(原典§17形式)
- 表示しないもの: リアルタイム「働いている」演出(スポーン型では嘘になる)・秘密・生プロンプト
- DF(部屋型)はキャラのavatar/persona_id差し替え構造(既にpersonas/で確保済)を使う

## 5.5 Discordチャンネル構成(確定版・2026-07-12 Chamiと合意)
カテゴリ=プロジェクト、チャンネル=部門。学習と報告は全プロジェクト共通。

| チャンネル | 部門 | Chamiが書く | 届く通知 |
|---|---|---|---|
| #総合-受付 | 司令塔 | 迷ったら何でも(司令塔が振り分け) | 振り分け結果 |
| #改修-依頼 | system-engineer | バグ・機能追加・インフラ | 実装完了 |
| #商品-候補 | product-scout | 候補評価・セール相談 | 推薦レポート |
| #コピー-相談 | copy-director | 訴求文・タイトル案 | コピー案 |
| #分析-数字 | shorts-analyst | 数字・検証の相談 | 分析レポート |
| **#品質-QA** | **qa-reviewer** | **投稿前チェック依頼・「これ確認して」** | **qa.passed/failed・回帰確認結果** |
| #学習-質問(共通) | learning-coach | 「○○って何?」 | 回答・HTML教材URL |
| **#研究室-コーチングルーム(共通)** | **司令塔(アメス+シャビ・アロンソ)** | **疑問・構想・違和感・仮説なんでも(完成した依頼文でなくてよい)** | **整理結果(Request Packet)・研究方針・部門への橋渡し報告** |
| #報告-通知(共通) | 自動出力専用 | (書かない) | デプロイ完了・Incident・改善提案・朝レポート |

計9チャンネル(2026-07-12: 研究室を追加=Chami設計 `docs/departments/research-room/運用説明書.md`)。#学習-質問と研究室は重なる領域があるが、「単発の用語質問=学習」「構想・仮説の対話=研究室」で使い分け(統合したくなったら学習を研究室へ吸収可)。Webhookは `local/discord_webhook_<名前>.txt`(例: _qa/_総合/_報告)で複数管理し、discord_notify.pyの`--channel`で出し分ける。

## 6. Chami主導の作業チェックリスト(いま必要なのは1つだけ)

1. **[DA・いま]** Discordサーバー→対象チャンネル→⚙→連携サービス→Webhook作成→URLコピー→`D:\SougouStartFolder\go5-maker\local\discord_webhook.txt` に貼り付けて保存(1行)。手順詳細=`local/discord_setup.md`
2. [DB・後日] Bot作成(Developer Portal)→トークンをlocal/へ(手順は Phase DB着手時に用意)
3. [DD・随時] 美しい/嫌いなWebやHTMLを見つけたら投げる(URL/スクショ/理由)→local/design-refs/へ私が整理

## 7. 未確認事項
1. Discordの既存ニュース配信の実装(どこで動いているか)=DBフェーズで干渉しないことを確認してから着手
2. 教材のArtifact URL共有範囲の運用(既定非公開→Chamiのみ閲覧。チーム共有は不要の想定)
3. DEの朝レポート頻度(毎朝9時のニュースと同時刻でよいか)
