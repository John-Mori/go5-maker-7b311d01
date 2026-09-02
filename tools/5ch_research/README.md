# 5ch ネタリサーチ・スクレイパ v1

5ch動画(5ch風スレ形式ショート)のタネになる「伸びてるスレ」を機械で拾う。
軍議(三笘)経由・Chami直依頼 (msg 1544620528407420958) / 担当=platform-se(一ノ瀬怜)。

## できること(v1)
1つの板について:
- `subject.txt` からスレ一覧を取得(スレタイ/レス数)
- **勢い**(= レス数 × 86400 ÷ スレ経過秒。スレIDが立て時刻)を計算して降順ソート
- 勢い上位N件のスレ本文を `dat` で落とす
- 1スレ1行の **jsonl** に出力(`local/5ch_research/<板>_<日時>.jsonl`)

## 使い方
```
# 1板
python tools/5ch_research/scrape_5ch.py --board newsplus --top 5 --max-posts 30

# 設定の板一覧(boards.json の enabled:true)をまとめて
python tools/5ch_research/scrape_5ch.py
```
主な引数: `--top`(本文を落とす上位スレ数) / `--max-posts`(1スレ最大レス数) /
`--sleep`(取得間隔秒・相手に優しく) / `--out-dir`。

## 対象板の足し方
`boards.json` に `{"slug","name","enabled","genre"}` を追加。
slug未検証なら先に `--board <slug>` で解決を確認してから `enabled:true` に。
どの板が5ch動画向きかはリサーチで決める(仮置き=生活/修羅場/ニュース系)。

## 取得可否の実測(2026-09-02)
- `subject.txt` / `dat` / `read.cgi` いずれも **ブラウザUAで200・応答0.5〜0.7秒**。
  現状 dat/read.cgi は生きている(まとめサイト経由の代替は今は不要)。
- 板→サーバは移設する(実測: livejupiter の旧サーバは404)。→ `bbsmenu` で
  現在サーバを解決し、.net/.io のうち subject.txt が豊富な方を実測で選ぶ。
- 文字コードは **Shift-JIS**。出力jsonlは UTF-8(`ensure_ascii=False`)。
  ★Windowsコンソールは化けて見えるがファイル自体は正しい。

## 制約
- 成人向け(bbspink 等)は対象外(`fetch` がドメインで弾く)。秘密は扱わない。
- 出力は `local/` 配下のみ(gitに上げない)。

## 設計(触る時に読む)
- 外へ出る手は `fetch()` 1本。テストはこれだけ偽物に差し替え、パース/勢い/並べ替えは
  本物のまま回す(`test_scrape_5ch.py` 9件・test-must-fail の線)。
- 取得はスレ単位で失敗を握る(1スレ404でも全体は完走・`fetch_error` に記録)。
