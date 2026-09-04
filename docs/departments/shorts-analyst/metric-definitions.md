# 指標の定義 (shorts-analyst)
> 運用: 結論先頭・1項目=数行・新しい項目を上へ。この部門だけが更新する(他部門はinsight経由で提案)。
> 2026-07-18 指標辞書化(設計書§3.5)。意味未確定の列は「未定義」と正直に書き、確定時に出典(Chami発言のmsg_id等)付きで追記する。

- 実測KPI: クリック数(link-worker実測)・再生数(YT Data API)・販売数(市場全体/PCスクレイパ)。成約は構造的に観測不可=追わない。

## ★系列の分断= 競合"動画"日次の速度は 2026-09-04 の前後を1本の折れ線に乗せない(分析部門+ad研究室の実務規律)

- **何**: 競合_日次の速度(views/measurementDays)は 8/18 medAll=798.5・medMax=189376 → 9/5 medAll=47.0・medMax=10148 と一桁落ちている。これは競合が急落したのではなく、収集経路が変わった段差の可能性が高い。**移設(fc54e09・2026-09-04)を跨ぐ点を折れ線で繋ぐと「9月に競合が失速した」と誤読する。**
- **なぜ(候補・未確定)**: ①計測時刻(旧=GAS 04:00 / 新=PC go5_comp_daily 05:30=measurementDays・初速窓が変わる) ②取得元(旧=YT Data API / 新=yt-dlp=views の母数・丸めが違い得る) ③スナップ齢(欠測 8/19〜9/03 を挟む=分母の日数がずれる)。どれが効いているかは同経路の実測が溜まるまで断定しない(C-041=1度の観測≠状態)。
- **どうする**: 朝ブリーフ/トレンド図は **経路が同じ区間どうしでだけ比較**する。移設後(9/5以降)が数日溜まってから新経路の基準線を引き直し、旧経路値とは別系列(別色・凡例に経路名)で描く。跨ぐ変化率は出さない。段差の切り分け(①②③)は基盤/ad研究室と共同で。

## 指標辞書(ID・出所・更新周期・注意点)

| ID | 指標 | 出所 | 周期 | 注意点 |
|---|---|---|---|---|
| M-01 | 再生数増分 tv/yv/wv(今日/昨日/週) | GAS action=deltas(computeDeltas_) | 毎時 | **全ch混在**=videoIdのacc1-/acc2-接頭辞で自力分離 |
| M-02 | 短縮URLクリック増分 tc/yc/wc | 同上 | 毎時 | 同上 |
| M-03 | 作品クリック増分 twc/ywc/wwc | 同上 | 毎時 | 同上 |
| M-04 | 最大瞬間風速 peaks | GAS(computePeaks_) | 毎時 | — |
| M-05 | 短縮URLクリック実数 clicks | link-worker /api/stats?code= | 即時 | code=historyのshortUrl末尾。secretは実値を書かない(gas/コード.gs shortSecret_()参照) |
| M-06 | Blueskyエンゲージメント like/repost/reply/quote | public.api.bsky.app getPosts | 即時 | 未認証・25件/回。**postUri空行=YouTube主体投稿で正常**(欠損ではない) |
| M-07 | 市場販売数 works.sales_n | D1 go5_fanza(PCスクレイパ) | スクレイパ更新時 | 市場全体の販売数=うちの成約ではない |
| M-08 | 視聴履歴スナップショット | GAS action=stats_tail(+totalRows) | 毎時 | n≤20ハードキャップ。全量は現状引けない |

## シート・ID規約

- **シート実タブ名=「月詠み」「宵桜艶帖」**(記録_ch1/ch2という名前のタブは無い。gas/コード.gs sheetName_)。
- **投稿日時列=YouTube実投稿時刻**(Chami明示2026-07-13。Blueskyの投稿時刻は意図的にズラしてあり分析に使わない→知見.md)。
- **ID体系は2系統ある[実測 2026-07-18訂正]**: historyのvideoId(post_id)=内部ID(acc1-/acc2-接頭辞つき)。**deltasのキー=生のYouTube videoId(接頭辞なし)**。突合はhistoryの**youtubeUrl**末尾で行う(deltas単独ではチャンネル分離不可)。リビルドはrebuildBaseClicksを考慮。

## 観測不可(確定・目的変数にしない)

- 成約数/成約率(コンサル経由で構造的に検証不可)・視聴継続率・スワイプ率(Analytics API未実装)。出典=.claude/agents/shorts-analyst.md。
