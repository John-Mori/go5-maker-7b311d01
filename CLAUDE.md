# AI運営ランタイム互換ホスト

このフォルダ名は旧事業名の名残です。5秒動画Webアプリは新規開発を終了し、現在の最優先事業ではありません。
ただし、Discord/Claudeの部門運営、キュー、監査ログ、認証、定期処理がこの絶対パスを実行ルートとして使っているため、移行完了までフォルダ自体を移動・改名・削除しません。

## 現在の優先順位

1. `D:\SougouStartFolder\5chShortMovie` — 約1分50秒のYouTube ShortsをYMM4で制作するための、台本・素材割当・音声・字幕・吹き出し・`.ymmp`生成システム。
2. `D:\SougouStartFolder\AnimeGameGoodsAFI` — VTuberを含むオタクグッズアフィリエイト。
3. 旧5秒動画Webアプリ — 凍結・退避対象。明示的な復旧依頼がない限り機能追加しない。

## 新しい基盤入口

- 基盤の正本・パス設定・機能別skill: `D:\SougouStartFolder\AI-Organization`
- 非公開データ境界: `D:\SougouStartFolder\AI-Organization-Private`
- 人格・部門記憶・組織台帳の正本: `D:\SougouStartFolder\00_AI-HQ`
- この場所の `.claude/agents` と `.claude/skills` は、移行中のClaude起動互換mirror

総合スタートフォルダのClaude/Codex hookは `AI-Organization/scripts/run_legacy_hook.py` を安定入口にし、現在はこの旧runtimeへ委譲しています。新しい絶対パスを各設定へ増やしません。

## この場所で暫定維持する運営runtime

- `scripts/llm`, `scripts/queue`, `scripts/discord`, `scripts/_daemons`, `scripts/hooks`, `scripts/_common`, `scripts/codex`, `scripts/office`
- `local/queue`, `local/llm`, `local/discord_*`, `local/attachments`, `local/codex_home`, `local/codex_cli` と秘密情報
- `.claude/agents`, `.claude/rules`, `.claude/skills`, `.claude/settings.json` (互換mirror/設定)
- `docs/departments`, `persona-hub` (参照切替前のruntime依存)
- siblingの `D:\SougouStartFolder\00_AI-HQ`

上記は旧Webアプリの資産ではなく、稼働中の組織runtimeです。依存先を設定化し、カナリア移行が完了するまで `産業廃棄物` へ動かしません。

## 旧5秒動画Webアプリ

HTML/JS/GAS/Worker等の旧仕様が必要な場合だけ、次の退避原本を読みます。

`産業廃棄物/2026-09-05/旧自動読込コンテキスト/5SecMovieMaker_CLAUDE_legacy_20260905.md`

旧アプリのファイルは、依存監査済みのallowlist単位で退避します。`git`、worktree、`local`、定期タスク、常駐プロセスを一括で整理しません。

## 作業上の不変条件

- 既存の大量変更は他作業の所有物として保持し、対象ファイルだけを扱う。
- 本番と同じ場面で成果物を確認するまで、commitだけを根拠に「直った」と断定しない。
- 秘密・token・credentialを表示またはcommitしない。本文を読まず、`AI-Organization-Private` のmetadata-only規則に従う。
- 削除より復元可能な退避を優先し、退避前後の一覧と対応表を残す。
- 新しいYMM4資産をこの旧ホストへ増やさない。正本は `5chShortMovie` に置く。
- 新しいグッズアフィ資産をこの旧ホストへ増やさない。正本は `AnimeGameGoodsAFI` に置く。
