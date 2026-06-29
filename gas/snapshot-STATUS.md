# YouTubeショート 再生数スナップショット — STATUS

最終更新: 2026-06-28

## 現在のステータス

| 項目 | 状態 |
|---|---|
| `gas/snapshot.gs` | ✅ コード完成 |
| GAS へのペースト | ⬜ `snapshot-setup.md` の手順3を実施 |
| `YOUTUBE_API_KEY` Script Property | ⬜ `snapshot-setup.md` の手順1〜2を実施 |
| `setupSnapshotTrigger()` 初回実行 | ⬜ `snapshot-setup.md` の手順4を実施 |
| `再生数_管理` シート | ⬜ `snapshotViews()` 初回実行時に自動作成 |
| `再生数_スナップショット` シート | ⬜ `snapshotViews()` 初回実行時に自動作成 |

## セットアップ手順書

→ `gas/snapshot-setup.md` を参照

---

## 設計概要

### データの流れ

```
月詠み / 宵桜艶帖
  └─ YouTube動画URL 列
       └─ youtubeIdFromUrl_() で 11文字ID を抽出
            └─ 再生数_管理 (active) に登録
                 └─ 30分ごと snapshotViews()
                      ├─ 経過時間ティアでフィルタ
                      ├─ YouTube Data API v3 (videos.list)
                      │     part=snippet,statistics（1ユニット/50件）
                      ├─ 再生数_スナップショット に追記
                      └─ 再生数_管理 を更新
                           └─ 28日経過 → status='done'
```

### 認証・秘匿情報

| 情報 | 保存場所 | コードへの記載 |
|---|---|---|
| YouTube API キー（GAS用） | GAS Script Properties `YOUTUBE_API_KEY` | **不可** |
| SHEET_ID | GAS Script Properties（コード.gs と共用） | **不可** |

---

## クォータ消費見積もり（参考）

| 追跡動画数 | バッチ数/回 | ユニット/日 | 月換算 |
|---|---|---|---|
| 10本 | 1 | 約 48 | 約 1,440 |
| 50本 | 1 | 約 48 | 約 1,440 |
| 100本 | 2 | 約 96 | 約 2,880 |

YouTube Data API v3 無料枠 = **10,000ユニット/日**。通常運用では問題なし。

---

## 追加された GAS 関数一覧

| 関数 | 用途 |
|---|---|
| `snapshotViews()` | メイン（30分トリガー） |
| `seedNewVideos_()` | 新動画を管理シートへ登録 |
| `fetchYtVideos_(ids, key)` | YouTube Data API 呼び出し |
| `setupSnapshotTrigger()` | 初回のみ実行・トリガー登録 |
| `deleteSnapshotTrigger()` | 追跡停止・トリガー削除 |

コード.gs の関数（`openSS_` / `prop_` / `headerMap_` / `CH_SHEETS`）は同一プロジェクト内で共用。
