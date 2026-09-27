# VtomoAnalyze

非公開ローカル専用の「ぶいとも分析ツール」。自社投稿と、リサーチ用アカウントの登録チャンネル動画を2タブで表示する。

## 更新と閲覧

- PC: `update_and_open.bat`。自社動画を取得し、集計後に `index.html` を `file://` で開く。
- スマホ: `serve_lan.bat`。同じLAN上の端末から `http://<PCのLAN-IP>:8765/` を開く。Windows Firewallの許可が必要な場合はプライベートネットワークだけを許可する。
- 自社API取得を増やさず再集計だけする場合: `python build_data.py`。

生成物は `data/`、検証画像は `_verify/` に置かれ、どちらもGit管理外になる。登録チャンネル一覧、動画ログ、OAuth token、client secretを公開場所へコピーしない。

## 入力

- 登録一覧: `paths_5ch.subs_dir()` の最新 `subs_yoizakura_t_YYYY-MM-DD.json`
- 登録チャンネル動画: `D:\SougouStartFolder\5SecMovieMaker\local\consult_intel\subs_shorts_YYYY-MM-DD.jsonl`
- 自社初動: `E:\5chShortMovie\リサーチ\自社48h\own_48h.jsonl`
- 自社動画: `fetch_own_videos.py` が生成する `data/own_videos_YYYY-MM-DD.json`

タブ2は既存日次ログを読むだけで、追加APIコールはない。タブ1は1回の更新につき `channels.list` 1回、`playlistItems.list` は動画50本ごと、`videos.list` も動画50本ごとに1回。各listリクエストを1 quota unitとして、55チャンネルを走査する既存の日次便より軽量だ。
