# 引き継ぎ：家のPCの Claude Code で続ける

> このファイルはリポジトリに入っているので、家のPCで `git clone` すれば一緒に手に入ります。
> 開発の全体文脈は **CLAUDE.md**、結合の設計は **統合設計書_動画メーカー×スケジュール.md** を参照。

---

## これは何
**5秒動画メーカー（統合アプリ）**。写真＋文字で5秒動画を作り、Bluesky に投稿。投稿スケジュール（カレンダー）・検証ダッシュボード・記録（Googleスプレッドシート）まで1ページ・5タブで完結する純クライアントサイドWebアプリ。

- 公開URL：https://john-mori.github.io/go5-maker-7b311d01/
- リポジトリ：https://github.com/John-Mori/go5-maker-7b311d01

---

## 家のPCでの始め方（Claude Code）
1. **必要なもの**：git ／（公開したい人は）GitHub CLI `gh` ／ ブラウザ。任意で Node（テスト用）・Python3（ローカル確認用）。
2. **取得**：
   ```bash
   git clone https://github.com/John-Mori/go5-maker-7b311d01.git
   cd go5-maker-7b311d01
   ```
3. **Claude Code をこのフォルダ（cwd）で開く** → `CLAUDE.md` が自動で読み込まれ、これまでの文脈が引き継がれます。
4. **ローカル確認**：
   ```bash
   python3 -m http.server 8765   # → http://localhost:8765/
   ```
   （または `index.html` を直接ブラウザで開く）
5. **テスト**：`node tests/test_bluesky.js` など（各 test_*.js は全PASS想定）。

## 公開（編集を反映）
```bash
git add -A && git commit -m "変更内容" && git push
# 1〜2分で公開URLに自動反映（GitHub Pages）
```
- push には GitHub 認証が必要。**家のPCでは初回だけ**：
  - `gh auth login`（ブラウザ認証）でOK／または push 時に Username=`John-Mori`・Password=**Personal Access Token**。
- 中身を変えたら `index.html` の `?v=N` を1つ上げる（スマホで確実に最新が読まれる。現行 **v=20**）。

---

## 現状（到達点・2026-06-18）
- **全フェーズ実装・公開済み（v=20）**。5タブ＝🎬動画作成／📅カレンダー／🦋投稿／🔗アフィリンク／🧪検証。
- **投稿手段**：①動画作成後の自動投稿（編集できる確認）②今すぐ投稿 ③予約（タブを開いてる間）④無人予約（GAS・タブ閉じてもOK）。
- **本文**＝固定文のみ。アフィリンクは作品URLから自動付与、画像は自動添付。プレビューは実アカウントのアイコンを表示。
- **カレンダー**＝各枠に優先度1〜5（その日の本命＝優先度1のみ強調）。ジャンル/検マークは廃止。
- **記録**＝GAS経由でGoogleスプレッドシートに自動記録（**セットアップ済み・動作確認済み**）。

## あなただけが持つ設定（リポジトリには入れていない＝新PCで再入力）
セキュリティのため、以下は公開リポジトリに含めていません。新PCの**ブラウザ（アプリの⚙）で再入力**してください：
- Bluesky **ハンドル**＋**アプリパスワード**（🦋投稿→⚙。端末ごとに保存）
- **記録用GASのURL（…/exec）**（🦋投稿→⚙「記録用URL（GAS）」）。前PCの控えにあります。
- 記録先**スプレッドシート**（Googleドライブの自分のシート）。
> これらは端末内（localStorage）にだけ保存。クラウド共有はしていません。

## 任意の未設定（使うときに）
- **クリック数集計**：GASスクリプトプロパティに `BITLY_TOKEN` 追加 → 関数 `setupTrigger` を1回実行。
- **無人予約**：GASに `BSKY_HANDLE`／`BSKY_APP_PW` 追加 → `setupReservationTrigger` を1回実行。
- 手順詳細：`gas/セットアップ手順.md`。

## 次の候補（やり残し）
- 実運用テスト → 文言・配色・優先度の微調整。
- （将来）Supabase で端末横断のスケジュール共有（設計書 §10.5/Phase5 のSupabase版）。
- カレンダーの並び・凡例などの追加調整。

## どこを触るか
`CLAUDE.md` の「ファイル別ガイド」を参照。要点：
- UIロジックは素の `*.js`（ESモジュール不使用）。データ正本は `schedule/`（カレンダー）と各 `*-core.js`。
- 変更後は `?v=` を上げる。投稿コア＝`bluesky-core.js`、検証＝`verify-core.js`、予約＝`scheduler.js`、橋渡し＝`integration.js`、GAS＝`gas/コード.gs`。
