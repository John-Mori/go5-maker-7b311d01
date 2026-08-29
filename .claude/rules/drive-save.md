---
paths:
  - "drive-worker/**"
  - "drive-upload.js"
  - "stock.js"
---

> ★この章は `CLAUDE.md` から移した。**内容は変えていない**(2026-08-29・研究室HQ)。
> 毎便の固定費(床)を下げるため、上の `paths` に当たるファイルを触る時だけ読み込まれる。

# Google Drive 自動保存(★破壊面の不変条件つき)

18. **Google Drive 自動保存**：★**保存タイミングは動画作成タブの「ドラフトで作成」押下後、生成動画が手元IDBまたはR2へ着地しドラフト台帳が確定した直後に一本化**(Chami指示2026-08-25)。投稿完了はDrive保存を起動しない。`stock.js`の`saveStock_.onCommitted`→`autoDriveSaveDraft_`→`driveSaveDataset_`が、生成動画＋元画像＋仕上がりプレビューを **Cloudflare Worker 経由**で `マイドライブ/AFI5秒動画/[チャンネル]/[動画名]/` へ保存する。非同期通信より先に`go5_drive_savejob_<id>`を同期記録し、直後の画面移動/iOS Safari破棄でも次回起動sweepが再送。手元/雲の二系統が同時成功してもID単位1回、Worker側も冪等。フロント＝`drive-upload.js`(失敗してもドラフト本体は成功のまま・永続再送/手動再試行可)。Worker＝`drive-worker/`(**破壊面の不変条件：フォルダ新規作成・ファイル新規アップロード・参照＋"フォルダのゴミ箱送り(trashed=true PATCH)ただ1種"のみ。完全削除/改名/移動APIは不在＝grep検証は"trashed"1語**)。★**同題名は上書き**(Chami指示2026-08-13)＝`overwrite=1`(フロント明示)かつ`env.ALLOW_OVERWRITE='1'`(サーバ側キルスイッチ)の二重ロック時だけ、窓内(作成30日以内・DriveのcreatedTimeが正)の同名フォルダを **新規保存の"後"に**ゴミ箱送り(先に上げてから消す=喪失ゼロ/30日復元可/trash直前に親直下・フォルダ・題名一致・窓内を再検証)。窓外/同名なし/フラグ無しは従来どおり `_2,_3…` 連番で非破壊。認証は本人OAuth refresh_token(個人Gmailのため Service Account 不可)を **Worker Secrets** に保管。スコープは `drive`(既存フォルダへ書くため／作成専用コードで運用。承認済)。Origin制限＋共有シークレット＋KV日次レート制限の多層防御。フォルダIDは env 固定(取り違え防止)。手順＝`drive-worker/SETUP.md`。秘密はフロント/repo/ログに出さない(SHARED_SECRETのみフロント可＝ソフト鍵)。
