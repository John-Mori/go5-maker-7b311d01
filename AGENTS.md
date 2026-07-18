# AGENTS.md — AIエージェント共通の起動ポインタ

> このファイルは **どのAIコーディングエージェント(OpenAI Codex・Claude Code・その他)から開かれても同じ正本に辿り着く**ための薄いポインタ。
> **中身をここに書かない**(二重管理はドリフトする)。正本だけを指す。

## 正本の場所(読む順)

1. `CLAUDE.md` — プロジェクト全体のコンテキスト(現状・座標系規約・ビルド/テスト/公開手順・禁止事項)。名前はClaude由来だが**内容はツール非依存**。まずこれを読む。
2. `引き継ぎ_Vol7.md`(現行巻) — 直近の到達点。旧巻は `docs/引き継ぎ/`。
3. `インシデント.md` — 過去の失敗の台帳。**設計・実装・デプロイ前に該当カテゴリを必読**。
4. `docs/departments/00_common/orchestration.md` — マルチセッション運用の規約正本(部門制・受信箱・進捗印・コミット作法)。
5. `docs/設計・調査/` — 機能別の設計書。

## 全エージェント共通の絶対規則(正本からの抜粋ではなく所在の案内)

- 座標系(1080×1920比率ベース)を崩さない → `CLAUDE.md` §3
- アセット変更時は `?v=` バンプ → `CLAUDE.md` §3
- コミットは必ずパス限定 `git commit -m "..." -- <paths>`(INC-91) → orchestration.md
- 秘密(トークン・キー)を出力・コミットしない。`local/` はgit管理外の運用データ置き場
- UI文言の括弧は半角()

## テスト

```
node tests/test_affiliate.js
node tests/test_bluesky.js
python scripts/lib/test_jsonl_store.py
```
