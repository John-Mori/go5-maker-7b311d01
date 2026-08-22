/**
 * コード.gs — 5秒動画メーカー：投稿記録＆クリック/反応集計(Google Apps Script Web App)
 *
 * 役割：
 *   1) クライアント(bluesky.js)から {op,videoId,channel,title,postUrl,affiliateUrl,workUrl,hashtags,postUri,shortUrl,testMode} を受け取る(doPost)
 *   2) videoId(背骨ID)をキーに「記録_ch1 / 記録_ch2」へ upsert。(重複行を作らない・列名マッピング)
 *      短縮URLはフロントの独自link-worker生成だけを採用。無い時は投稿URLをそのまま共有URLとして記録。
 *   3) refreshEngagement()(毎時)で Bluesky反応(いいね/リポスト)を更新
 *   4) Phase5：無人予約投稿(runReservations / 5分トリガー)
 *   ※ Bitly は全廃。(無料枠オーバーの主因かつ冗長＝共有されず計測不能)クリック計測は link-worker(KV) に一本化する方針。
 *      テンプレの 'Bitly_ID'/'Bitlyクリック' 列は当面温存。(未使用。将来 link-worker クリックへ転用可)
 *
 * 前提：記録先スプレッドシートは「動画記録分析テンプレート.xlsx」を取り込んだもの
 *   。(記録_ch1 / 記録_ch2 / 集計 / 設定、名前付き範囲 Holidays を含む)
 * スクリプトプロパティ：
 *   SHEET_ID(記録先スプレッドシートID・必須)／ BSKY_HANDLE / BSKY_APP_PW(無人予約に使用)
 *   ※ BITLY_TOKEN は不要。(Bitly全廃)設定が残っていても未使用。
 *   ※ SHARED_SECRET は設定しないこと(現クライアントは送らないため、設定すると弾かれる)
 */

// 記録シートの列ヘッダー。(新規シート作成時のヘッダーにも使う)
// ※不要な手動ラベル列(特別期間(手動)/サムネ・フック種別/CTA・リンク提示方法/Blueskyラベル)は削除済み。
var HEADERS40 = [
  'post_id','投稿日時','曜日','day-type','時間帯スロット','ジャンル','題名(コメント)',
  '作品cid','YouTube動画URL','短縮URL',
  'インプレッション','インプCTR%','視聴回数','平均視聴維持率%','いいね','リポスト','短縮URLクリック数',
  'リンククリック率%','post_uri','クリック更新日時','反応更新日時'
];
// ?action=cleanup_columns で既存シートから削除する列。(コードが唯一の正・ClaudeCodeから増減)
//
// ★FANZA成約・報酬系とその派生指標を削除(Chami依頼 2026-07-23「検証不可のデータ列を削除」)。
//   実測(action=column_fill)の根拠:
//     ・FANZA発生成約/FANZA確定成約/発生報酬¥/確定報酬¥ … 両シートとも **0件**(手入力列・一度も入らず)
//     ・承認率% … 0件
//     ・CVR発生%/CVR確定%/EPC発生¥/EPC確定¥/RPM … 分子(成約・報酬)が空のため **常に0**が並ぶだけ
//   FANZAは投稿単位の成約を返さない(管理画面が正)ため、これらは埋めようがない＝分析を汚すだけ。
//   ★'リンククリック率%' は削除しない。クリック数÷視聴回数＝**両方とも実データがある**(検証可能)。
//     FANZA由来ではないので今回の「検証不可」に当たらない。
// ※'Bluesky投稿URL'/'Bitly_ID' は宵桜艶帖にだけ在った余分列。月詠みへ揃えるため削除。
//   Bluesky投稿URLは'共有URL'と重複、Bitly_IDはBitly廃止済みで死んだ列。
// ★'返信'(Q列)・'フォロー増'(R列)を削除(Chami依頼 2026-07-31 ⑦⑤)。
//   返信＝Blueskyの返信数。Chami「返信はない・不要」。refreshEngagement の書き込みも停止済。
//   フォロー増＝手動入力の想定だったが一度も運用されず「わからないので削除」(Chami)。
var CLEANUP_COLUMNS = [
  '特別期間(手動)', 'サムネ/フック種別(A/B)', 'CTA・リンク提示方法', 'Blueskyラベル',
  'FANZA発生成約', 'FANZA確定成約', '発生報酬¥', '確定報酬¥',
  '承認率%', 'CVR発生%', 'CVR確定%', 'EPC発生¥', 'EPC確定¥', 'RPM(¥/1000再生)',
  'Bluesky投稿URL', 'Bitly_ID',
  '返信', 'フォロー増'
];
// FANZA投稿時スナップショット列。(記録シート末尾追加。既存40列は不変)
// レビュー件数は販売部数の代理指標。(実際の売上本数は取得不可)
var FANZA_HEADERS = [
  '元値list_price','割引後price','割引率pct','FANZA取得日時',
  'レビュー件数(代理指標)','レビュー平均'
];
// 追加属性列。(記録シート末尾追加・移行で付与)
// カテゴリ＝作品属性を名前で明記。(キャラ/JK/ギャル/異世界・複数可・カンマ区切り。キャラ無し＝オリジナルで空欄)
// ※旧「キャラ○」方式は廃止。migrate_headers で既存「キャラ」列は「カテゴリ」へ改名。
// ※YouTube題名は廃止：題名(コメント)列に集約する。(consolidate_title で既存分も移行・列削除)
var EXTRA_HEADERS = ['カテゴリ', '作品状態', '共有URL', '作り直し', 'ハッシュタグ', 'リビルド元ID', 'タイトル文字数', '目的', 'コメント型', 'YT補正累計', '作品短縮URL', '作品URL', '投稿先'];
// 作品属性の定義。(順序＝カテゴリ列での並び)フラグ名→表示名。
var ATTR_DEFS = [
  { key: 'chara', label: 'キャラ' },
  { key: 'jk', label: 'JK' },
  { key: 'gyaru', label: 'ギャル' },
  { key: 'isekai', label: '異世界' },
  { key: 'harem', label: 'ハーレム' },
  { key: 'ai', label: 'AI' },
  { key: 'ol', label: 'OL' },
  { key: 'soshu', label: '総集編' }
];
function attrTrue_(v) { return v === true || v === 'true' || v === '○' || v === 1 || v === '1'; }
function attrProvided_(f) {
  for (var i = 0; i < ATTR_DEFS.length; i++) { if (f[ATTR_DEFS[i].key] !== undefined) return true; }
  return false;
}
function categoryOf_(f) {
  var cats = [];
  ATTR_DEFS.forEach(function (a) { if (attrTrue_(f[a.key])) cats.push(a.label); });
  return cats.join(', ');
}
// FANZA サービス種別を作品URLまたはアフィリンクから判定。(books/同人/データ)
function fanzaType_(url) {
  if (!url) return '';
  var s = String(url);
  var lm = s.match(/[?&]lurl=([^&]+)/);
  if (lm) { try { s = decodeURIComponent(lm[1]); } catch (e) {} }
  if (/book\.dmm\.(com|co\.jp)/.test(s)) return 'books';
  if (/\/doujin\/|\/dc\/doujin/.test(s)) return '同人';
  if (/\.dmm\.(co\.jp|com)/.test(s)) return 'データ';
  return '';
}
// F列「ジャンル」= FANZA種別を 同人/Books/データ で表記。(fanzaType_ の 'books' のみ 'Books' へ正規化。Chami依頼 2026-07-31③)
function fanzaGenre_(url) {
  var t = fanzaType_(url);
  return t === 'books' ? 'Books' : t; // '同人' / 'データ' はそのまま。判定不可は '' (既存値を潰さない)
}
//
// ── 列の自動取得マップ(保守用メモ：ClaudeCodeはここを基準に列を増減する)──
//   【自動で埋まる】post_id / 投稿日時 / 曜日 / day-type / 時間帯スロット / 題名(コメント) /
//     ジャンル(同人/Books/データ＝作品URLから判定) / 作品cid / YouTube動画URL / 短縮URL /
//     視聴回数 / いいね / リポスト /
//     短縮URLクリック数 / post_uri / クリック更新日時 / 反応更新日時 / カテゴリ /
//     元値list_price / 割引後price / 割引率pct / FANZA取得日時 / レビュー件数(代理指標) / レビュー平均 /
//     リンククリック率%(←数式・クリック数÷視聴回数。両辺とも実データがあるので有効)
//   【手動入力のみ＝APIで自動取得不可】インプレッション / インプCTR% / 平均視聴維持率%
//   ※'返信'(Bluesky返信数)・'フォロー増' は 2026-07-31 に削除(Chami依頼⑦⑤)。CLEANUP_COLUMNS で既存シートからも除去。復活させないこと。
//   ※FANZA成約・報酬系(FANZA発生成約/FANZA確定成約/発生報酬¥/確定報酬¥)と、その派生数式
//     (承認率%/CVR発生%/CVR確定%/EPC発生¥/EPC確定¥/RPM)は **2026-07-23に削除**(Chami依頼)。
//     FANZAは投稿単位の成約を返さない=手入力するしかなく、実測で両シートとも0件だった。
//     派生数式は分子が空のため常に0を並べるだけで、分析を汚していた。**復活させないこと。**
//   ※特別期間(手動)/サムネ・フック種別/CTA・リンク提示方法/Blueskyラベル は CLEANUP_COLUMNS で削除済み。
//   ※Bluesky投稿URL/Bitly_ID は宵桜艶帖にのみ在った余分列。月詠みへ揃えるため削除(同日)。
var CH_SHEETS = ['月詠み','宵桜艶帖'];
// 再デプロイ確認用バージョン。(中身を変えたら上げる)<exec URL>?ping=1 で確認できる。
var GAS_VERSION = '2026-08-23C(データ整合修正の口 action=fix_records_0823 を新設(軍議REQ-gunji-5213170ea8 #3・読み取り既定/&apply=1でだけ書込み)。task=untest=記録シートのpost_idに漏れた"test-"接頭辞を剥がす(剥がした先が既存と衝突する行は触らずcollisionで報告・post_id以外は不変)。task=merge_dup=同一ytid&同一cidで2行に割れた記録を「統合」(keep=題名有る方へdropの非空セルだけを埋め=keepの既存値は上書きせず、そのうえでdrop行を1本だけ削除。ytid不一致 or cid不一致ならapplyを弾くfail-safe)。列/ヘッダ/既存挙動は不変・破壊面はmerge_dropのdrop行1本のみ。以下は前版=2026-08-23B(時点記録(30分〜72h初速)の欠測を恒久是正=captureTimepoints_の記録窓が固定9分([min,min+9])でしか埋まらず、その9分にsnapshotStats(5分毎)が回らない/6分上限で殺される/YouTube URL結線が遅れると当該バケットが永久欠測していた(実測=Chami手動投稿の水木金4本がb720だけ残りb30〜b360全欠)。対策=窓を「次バケット境界の直前まで」へ拡張し、そのバケット区間に1回でもデータの揃ったスナップが走れば記録=取りこぼしに強くする。実経過分は列5に保存済でage正規化は下流で保たれる。列/ヘッダ/既存挙動不変。以下は前版=2026-08-23A(競合日次の凍結を根治=runCompetitorDailyがGASの6分実行上限を超え毎回タイムアウト[実測comp_daily_now=361sでGoogleのタイムアウトHTML]→日次append[競合_日次シート]へ到達できず2026-08-18で凍結していた[PC側集計は同じ8/18を再集計しつつ緑を返すsilent green]。対策=最優先の"既存窓動画の統計スナップ→日次append"を関数先頭へ移し必ず先に済ませ、チャンネル統計更新・新着discoveryは時間予算[4分]内のbest-effortへ後置。snapped==0[YT統計が空=urlfetch日次上限/APIキー/quota]は握り潰さずok:falseで返す[C-041/AD研究室モドリッチ依頼2026-08-23]。以下は前版=2026-08-18C(wcode_probe に実click着地テスト live[] を追加=同じworkerClicks_で導線1(code)/導線2(wcode)を両方叩き、col7埋まる/col8空の非対称がworker応答差かwriter差かを切り分け。以下は前版=2026-08-18B(action=wcode_probe を新設(読み取り専用・書き込み無し)=視聴履歴.作品クリック数が0/1204で未着地の枝判定。snapshotStatsのwrite-set(recs=vid必須＋vidで先頭dedup)を厳密再現し、導線2(作品短縮URL=wcode)がvid有り行で起きるか(枝A=writer取りこぼし)/vid無し行中心か(枝B=構造的に載らない)を実データで返す。決め手=recs_dedup_with_wcode(dedup生存行のうちwcode保持数)/vids_wcode_dropped_by_dedup(同一vidの他行にwcode有りだが先頭行が空=dedupが落とした数)/wcodes_only_novid。列追加無し・既存挙動不変。以下は前版=2026-08-18A(action=backfill_probe を新設=「後埋まり列」(ピーク値/クリック数/いいね/リポスト等、改修後N時間で毎時トリガーが実データで初めて埋める列)の実データ着地プローブ(読み取り専用)。各列の非空行数と最終更新時刻を返し、改善提案部門の Z2運用ツール(b面)が「直したと言った後、実データが本当に埋まったか」を外から突き合わせられる口=型《実物着地》の読取口。書き込み無し・列追加無し・既存挙動不変。作成時プリフライトは scripts/check_backfill_assert.mjs(CI門)が登録簿 backfill_columns.json と照合。以下は前版=2026-08-16D(ピーク記録が埋まらない核心の一因を根治=ytViews_のバッチに不正ID(SALE擬似vid"SALE"/"SALE:code"のコロン混入・壊れURL由来)が1つ混ざるとvideos.listがバッチ全体を400で弾き、同バッチの実在vidの再生数まで丸ごと欠落していた(実測DIAG viewsKeys=0=views全滅→ピーク算出の材料ゼロ)。対策=各バッチをYouTube動画IDの形/^[A-Za-z0-9_-]{11}$/に一致する物だけへ絞ってから叩く(不正IDは1つも渡さない)。注:診断中に当プロジェクトのUrlFetchApp日次クォータを消費したため反映直後は一時的にfetchが例外になり得る(回復後にトリガーが自動で埋める)。C2〜C5の一時診断(DIAG/yt_probe)は確認後に除去予定。以下は前版=2026-08-16C5(一時診断=yt_probeがytViews_のバッチ経路を実物で通す[実vid+SALE:コロンid]。以下は前版=2026-08-16C4(一時診断=ytViews_の各バッチのHTTP応答をDIAG.ytに記録(viewsが全nullの真因=どのバッチが400かの特定)。以下は前版=2026-08-16C3(一時診断=yt_probe追加。YT_API_KEYの有無とYouTube Data APIの実HTTP応答を返す(viewsが全nullの切り分け)。以下は前版=2026-08-16C2(一時診断=snapshot_nowがpeakUpdatesの内訳counts[recs/views非null/prev/hrs範囲内/consider呼数]を返す。ピークが0のままの切り分け用・確認後に除去。以下は前版=2026-08-16C(ピーク永続化が実行終端に間に合っていなかった=16Bの時間予算(日時2分+クリック4分)だと本体upsertループの後にあるピーク書き込みへ6分内に到達できず、スナップ行は書けてもピークは0のままだった(実測23:25の便)。配分を前詰め(日時90秒+クリック通算3分)+本体upsert/ピーク算出ループ自体も通算5分で頭打ち=打ち切っても溜めたピークは必ず永続化へ抜ける。以下は前版=2026-08-16B(ピーク記録が埋まらない"現"真因=snapshotStatsがGASの6分実行制限を超えて毎回時間切れ→Googleがトリガーを自動停止し2026-08-15 19:51Zを最後にスナップ完全停止していた[実測]。膨張源は①投稿日時のYouTube公開時刻バックフィル(dateFix・08-15Aで追加=全履歴行をsetValue)②全コードのクリック取得(1コードずつ+80ms待機)。恒久対策=重い2ループを時間予算で頭打ち[dateFix2分/クリック通算4分]にし必ず書込み・ピーク算出へ到達=機構で6分を超えさせない。打ち切り分は冪等で次回続行・数回で定常。反映後 admin_setup でトリガー再設定要。以下は前版=2026-08-16A(ピーク記録の全滅を根治[Chami再発指摘=ランキングのピーク窓が常に空]。真因=snapshotStatsのprevByVid構築が記録日時セルを生文字列前提でDate.parse[String(Date)は"Sat Aug 16 2026…"形式のため先頭空白のT置換で常にNaN]→tms=0→considerPeak_が一度も呼ばれずピーク記録シートが0行のまま[deltasはymd_正規化済みで生存=ピークだけ全滅]。2026-08-06/08-11の下限調整では直らなかった理由もこれ[rateの手前で死んでいた]。対策①=記録日時をDate/文字列両対応で正規化[instanceof Date→getTime/formatDate]。対策②恒久=増加ゼロ区間でも未記録の作品へ0(件/時)を種まき[SALE擬似行除く]=低速動画も必ず行が付き、シート0行=即異常と構造で判別可能に。列順/PEAK_HEADERS/冪等移行/v・c・w3系統は不変。以下は前版=2026-08-15B(外部短縮の新規発番を完全撤去。フロントで独自link-worker URLが無い時はpostUrlを共有URLへ保存し、da.gd APIを呼ばない。再発防止テストで外部短縮API文字列の復活を禁止。以下は前版=2026-08-15A(投稿日時をYouTube公開時刻へ自動収束[Chami依頼REQ-2f4520e4d7=投稿日は投稿完了ボタンを押した時刻でなくYouTubeの実公開時刻を参照する]。真因=投稿完了と同時のupsert(pushItemToGas_)がpostedAtを送らずwriteRecord_の新規行フォールバックが投稿日時列にnow[押下時刻]を確定していた。対策=5分毎snapshotStatsに相乗り。ytViews_に第2引数pubOutを追加しpart=statistics,snippetでpublishedAtも回収[追加クォータ0=既存videos.list呼び出しのpart拡張のみ]、snapshotStatsが各CH行の投稿日時列を走査しpublishedAtと±60秒超ズレ or 空欄の行だけsetValue[new Date]で修正、修正シートをsortByDate_で1回整列[冪等=一致行は無操作]。新規投稿は公開後最大5分で自動修正・既存の誤記録もYouTube URL持ち全行を自動バックフィル・列追加なし・フロント無改修。以下は前版=2026-08-11B(全部のピークが要る[Chami2026-08-11]=導線2(作品クリック=ピンク矢印 w)の最大瞬間風速ピークをGASが記録するよう追加。従来ピーク記録シートは再生(v)と導線1(c)の2種だけで作品クリックのピークは未対応=ランキングのピーク窓でピンクを選ぶと「GAS側の対応待ち」の注記で空だった。PEAK_HEADERSへ「作品クリックピーク(件/時)」「作品クリックピーク時間帯」を末尾追加(既存のv/c/更新日時の列位置は不変=timepointSheet_と同じ冪等ヘッダ移行で旧シートも無停止で拡張・旧行のw列は空欄)、snapshotStatsのconsiderPeak_をw対応(prevByVidに作品クリック累計wclicksを持たせ区間伸び率を採用・下限0.06h上限6hはv/cと共通)、computePeaks_がwRate/wWinを返す→フロントyt-clicks.jsがr.peakW/peakWWinで描画・c2PeakUnsupportedの分岐と注記を撤去。過去分は遡及不可(サーバーに作品クリックの区間履歴が無いため)・以後のsnapshotから積む。以下は前版=2026-08-11A(ピークを早く記録=snapshotStatsを10分毎→5分毎に短縮し、最大瞬間風速の採用下限も0.12h[7.2分]→0.06h[3.6分]を対で更新[間隔だけ縮めて下限を残すと5分区間が常に下限割れでピークが1件も記録されない=2026-08-06と同型の事故になるため必ず対で変える]。公開直後からピークが早く埋まる・時点記録も5分毎で「バケット+0〜5分」に確定=旧10分毎より早い[Chami「ピークを早く記録できるように」2026-08-11]。★反映後は ?action=admin_setup でトリガー再設定が要る[間隔変更をGASへ効かせるため]。以下は前版=2026-08-08A(⑤時点記録シートに導線2[作品クリック=ピンク矢印 w]を追加。従来は再生数[v]と導線1[c]だけをスナップし導線2はGAS未記録=端末を公開1時間などの時点に開いていない投稿はピンク矢印バケットが永久に空だった[Chami「ピンクのクリックがちゃんと集計されてない」2026-08-08]。captureTimepoints_がwcodeの開封数をw列[TIMEPOINT_HEADERS末尾に追加・timepointSheet_で冪等移行=旧行は空欄]へ記録、computeTimepoints_がwを返す→ランキングの各時間窓でピンクもサーバー記録から埋まる[端末未起動でも]。過去分は遡及不可[サーバーに履歴が無いため]・以後の投稿から有効。以下は前版=2026-08-06A: ランキング全窓の記録漏れを修理。①ピーク=snapshotStatsを10分毎(0.167h)に変えた際、最大瞬間風速の採用下限が旧0.2h(12分)のまま=区間が常に下限割れで1件も記録されず「ピークが何も表示されない」だった→下限を0.12h(7.2分)へ。②時点記録の窓に12時間/48時間を追加(TIME_BUCKETS/LAB)=旧実装はこの2窓をGAS未記録にして端末スナップ頼み=常態的に空だった。8窓(30分/1h/2h/6h/12h/24h/48h/72h)すべてサーバー記録に統一。Chami依頼2026-08-06。以下は前版=2026-08-02A: action=deltas の応答に timepoints を追加＝時点記録シート[公開起点の30分/1h/2h/6h/24h/72h・再生数と導線1クリック]をvideoId単位で返す。ランキングの窓表示が過去動画のサーバー記録も出せるようにする[端末未起動でも記録済みの分]。Chami依頼2026-08-02。以下は前版=2026-07-31F: ②action=fix_date_from_yt[指定post_idのYouTube動画URL→Data APIのpublishedAtを投稿日時へ・dry-run既定/&apply=1/&pids=,区切り]。／①action=restore_from_bk[バックアップシートに在って本シートに無いpost_id行を列名マッピングで復元・dry-run既定/&apply=1・&pid=で1行限定・post_id重複スキップ・投稿日時で整列]。／③F列ジャンルを投稿時に作品URLから自動記載[同人/Books/データ・fanzaGenre_]＋既存行の一括補完 action=genre_fill[dry-run既定/&apply=1/&force=1]。⑦Q列返信と⑤R列フォロー増を廃止=HEADERS40から除去・refreshEngagementの返信書き込み停止・新規行の返信0初期化停止・CLEANUP_COLUMNSへ追加[?action=cleanup_columnsで既存シートから削除]。Chami依頼2026-07-31①〜⑦のうち③⑤⑦。／B=action=click_agg/rebuild_click_agg を新設＝作品別クリック合算。X凍結→Bluesky退避で同一作品でも投稿ごとに導線1短縮URLが変わりクリックが複数行に割れる問題を、作品cid[=作品URL正規化]でまとめ直し1作品=1行の合計クリックにする。専用タブ「作品別クリック合算」へ非破壊出力・毎時refreshClicks末尾で積み直し[手番ゼロ]。分析部門依頼2026-07-31。／A=action=posted_cids を新設＝候補タブ✔pillの権威索引。記録_ch1/ch2の全行を{c:作品cid,w:作品URL,v:post_id,t:投稿日}へ4列射影し、c/w両空行は除外、post_idのacc-prefixがそのシートのchと矛盾する行は除外[fail-open]。読み取り専用。フロントがローカル短縮URL履歴でなくシートで投稿済み判定→端末分断の偽陰性/誤バケットの偽陽性を構造的に解消。J(computeDeltas_のクリック実数積み直し)を継続。設計書_投稿済み判定の権威ソース化_2026-07-31 S1・Chami依頼2026-07-31))))';

// 統一列順の正。(2026-07-12・⑥)両chシートの列の左右順をこの並びに固定する。(?action=reorder_headers / admin_setupが適用)
//   ここに無い列(手動追加など)は自然に末尾へ寄る。GASは列名で書くため機能は列順に依存しないが、
//   集計シートの位置参照数式やmove_row(列名不一致でサイレント欠落)の事故を防ぐため順序も固定する。
var CANONICAL_HEADERS = HEADERS40.concat(FANZA_HEADERS).concat(EXTRA_HEADERS);

function prop_(k) { return PropertiesService.getScriptProperties().getProperty(k); }
function jsonOut_(obj) { return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON); }
function openSS_() {
  var id = prop_('SHEET_ID');
  var ss = id ? SpreadsheetApp.openById(id) : SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) throw new Error('スプレッドシートが見つかりません(SHEET_ID を設定してください)');
  return ss;
}
function sheetName_(channel) { return (channel === 'acc2') ? '宵桜艶帖' : '月詠み'; }
function getChannelSheet_(channel) {
  var ss = openSS_(); var name = sheetName_(channel);
  var sh = ss.getSheetByName(name);
  if (!sh) { sh = ss.insertSheet(name); sh.appendRow(HEADERS40); }
  else if (sh.getLastRow() === 0) { sh.appendRow(HEADERS40); }
  return sh;
}
function headerMap_(sh) {
  var h = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0], m = {};
  for (var i = 0; i < h.length; i++) { if (h[i] !== '' && h[i] != null) m[h[i]] = i + 1; }
  return m;
}
// 短縮URLクリック数の列見出しを解決。(新名→旧名「開封数」→さらに旧名「Bitlyクリック」。どれも無ければ新名)
function clickColName_(map) {
  return map['短縮URLクリック数'] ? '短縮URLクリック数' : (map['開封数'] ? '開封数' : (map['Bitlyクリック'] ? 'Bitlyクリック' : '短縮URLクリック数'));
}

function doGet(e) {
  var p = (e && e.parameter) || {};
  // ★再デプロイ確認用：<exec URL>?ping=1 を開くと、今“動いている”コードのバージョンが見える。
  //   再デプロイが成功していれば下の GAS_VERSION が返る。古い値や別物なら未反映。
  if (p.ping) {
    return jsonOut_({ ok: true, version: GAS_VERSION, now: new Date().toISOString(),
      bitly: 'removed', features: ['upsert', 'testMode', 'managed-short-only', 'link-worker-clicks', 'fanza-snapshot'] });
  }
  // 一回限りのヘッダ移行: <exec URL>?action=migrate_headers で既存シートに FANZA 列を追加する。
  if (p.action === 'migrate_headers') {
    return jsonOut_(migrateHeaders_());
  }
  // 診断: 全列のヘッダ書式を両シートで比較する。(読み取り専用)
  //   ★col1_format(1列目だけ)では不十分だった(Chami指摘・スクショで他列の色違いを提示された
  //   2026-07-23)。ヘッダ行全体を列ごとに比較し、どこが違うかを機械的に洗い出す。
  if (p.action === 'header_format') {
    try {
      var hfOut = {};
      CH_SHEETS.forEach(function (nm) {
        var hfsh = openSS_().getSheetByName(nm); if (!hfsh) { hfOut[nm] = null; return; }
        var hfCols = hfsh.getLastColumn();
        var hfHdrVals = hfsh.getRange(1, 1, 1, hfCols).getValues()[0].map(String);
        var hfBg = hfsh.getRange(1, 1, 1, hfCols).getBackgrounds()[0];
        var hfColor = hfsh.getRange(1, 1, 1, hfCols).getFontColors()[0];
        var hfWeight = hfsh.getRange(1, 1, 1, hfCols).getFontWeights()[0];
        var hfFamily = hfsh.getRange(1, 1, 1, hfCols).getFontFamilies()[0];
        var hfSize = hfsh.getRange(1, 1, 1, hfCols).getFontSizes()[0];
        var hfAlign = hfsh.getRange(1, 1, 1, hfCols).getHorizontalAlignments()[0];
        var cols = [];
        for (var hi = 0; hi < hfCols; hi++) {
          cols.push({
            col: hi + 1, header: hfHdrVals[hi], background: hfBg[hi], fontColor: hfColor[hi],
            fontWeight: hfWeight[hi], fontFamily: hfFamily[hi], fontSize: hfSize[hi], align: hfAlign[hi],
            width: hfsh.getColumnWidth(hi + 1)
          });
        }
        hfOut[nm] = { colCount: hfCols, cols: cols };
      });
      // 月詠みを正として、列名一致するもの同士で差分を出す。
      var diff = [];
      if (hfOut['月詠み'] && hfOut['宵桜艶帖']) {
        var byName = {}; hfOut['月詠み'].cols.forEach(function (c) { byName[c.header] = c; });
        hfOut['宵桜艶帖'].cols.forEach(function (c) {
          var ref = byName[c.header]; if (!ref) { diff.push({ header: c.header, status: 'not_in_月詠み' }); return; }
          var keys = ['background', 'fontColor', 'fontWeight', 'fontFamily', 'fontSize', 'align', 'width'];
          var d = {};
          keys.forEach(function (k) { if (ref[k] !== c[k]) d[k] = { 月詠み: ref[k], 宵桜艶帖: c[k] }; });
          if (Object.keys(d).length) diff.push({ header: c.header, col月詠み: ref.col, col宵桜艶帖: c.col, diff: d });
        });
      }
      return jsonOut_({ ok: true, format: hfOut, mismatches: diff });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 実行: 全列のヘッダ書式(背景/文字色/太さ/フォント/サイズ/揃え/幅)を月詠みへ揃える。
  //   (&apply=1 で実行・既定はdry-runで差分だけ返す)列名で対応付けるため列の並びがズレていても正しく揃う。
  if (p.action === 'header_align') {
    try {
      var haApply = String(p.apply || '') === '1';
      var haSrc = openSS_().getSheetByName('月詠み'), haDst = openSS_().getSheetByName('宵桜艶帖');
      if (!haSrc || !haDst) return jsonOut_({ ok: false, error: 'sheet not found' });
      var haSrcMap = headerMap_(haSrc), haDstMap = headerMap_(haDst);
      var haResult = [];
      Object.keys(haDstMap).forEach(function (name) {
        var sCol = haSrcMap[name], dCol = haDstMap[name];
        if (!sCol) { haResult.push({ header: name, status: 'skip_no_月詠み_match' }); return; }
        var sCell = haSrc.getRange(1, sCol), dCell = haDst.getRange(1, dCol);
        var before = { background: dCell.getBackground(), fontColor: dCell.getFontColor(), width: haDst.getColumnWidth(dCol) };
        var after = { background: sCell.getBackground(), fontColor: sCell.getFontColor(), width: haSrc.getColumnWidth(sCol) };
        if (haApply) {
          sCell.copyTo(dCell, SpreadsheetApp.CopyPasteType.PASTE_FORMAT, false); // 値は変えない・書式のみ
          haDst.setColumnWidth(dCol, haSrc.getColumnWidth(sCol));
        }
        haResult.push({ header: name, colSrc: sCol, colDst: dCol, before: before, after: after, changed: before.background !== after.background || before.fontColor !== after.fontColor || before.width !== after.width });
      });
      return jsonOut_({ ok: true, applied: haApply, result: haResult });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 診断: 1列目(post_id)のヘッダ・データセルの書式を両シートで比較する。(読み取り専用)
  //   ★「1列目の表示や色が変わっていない」報告(2026-07-23)の実態確認用。
  if (p.action === 'col1_format') {
    try {
      var fOut = {};
      CH_SHEETS.forEach(function (nm) {
        var fsh = openSS_().getSheetByName(nm); if (!fsh) { fOut[nm] = null; return; }
        var hdrCell = fsh.getRange(1, 1);
        var dataCell = fsh.getLastRow() >= 2 ? fsh.getRange(2, 1) : null;
        function snap(rng) {
          if (!rng) return null;
          return {
            background: rng.getBackground(), fontColor: rng.getFontColor(),
            fontWeight: rng.getFontWeight(), fontFamily: rng.getFontFamily(),
            fontSize: rng.getFontSize(), numberFormat: rng.getNumberFormat(),
            horizontalAlignment: rng.getHorizontalAlignment()
          };
        }
        fOut[nm] = { header: snap(hdrCell), data: snap(dataCell), colWidth: fsh.getColumnWidth(1) };
      });
      return jsonOut_({ ok: true, format: fOut });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 実行: 月詠み(正)の1列目の書式を宵桜艶帖へ揃える。(&apply=1 で実行・既定はdry-runで差分だけ返す)
  if (p.action === 'col1_align') {
    try {
      var faApply = String(p.apply || '') === '1';
      var srcSh = openSS_().getSheetByName('月詠み'), dstSh = openSS_().getSheetByName('宵桜艶帖');
      if (!srcSh || !dstSh) return jsonOut_({ ok: false, error: 'sheet not found' });
      var srcHdr = srcSh.getRange(1, 1), dstHdr = dstSh.getRange(1, 1);
      var srcW = srcSh.getColumnWidth(1);
      var before = { headerBg: dstHdr.getBackground(), headerColor: dstHdr.getFontColor(), width: dstSh.getColumnWidth(1) };
      var after = { headerBg: srcHdr.getBackground(), headerColor: srcHdr.getFontColor(), width: srcW };
      if (!faApply) return jsonOut_({ ok: true, applied: false, before: before, after: after });
      // ヘッダ行の書式一式をコピー(値は上書きしない=setValuesではなくcopyTo書式のみ)
      srcHdr.copyTo(dstHdr, SpreadsheetApp.CopyPasteType.PASTE_FORMAT, false);
      dstSh.setColumnWidth(1, srcW);
      // データ行があれば2行目以降の書式も列全体で揃える(値は変えない)
      var dstLast = dstSh.getLastRow();
      if (dstLast >= 2) {
        var srcDataFmt = srcSh.getLastRow() >= 2 ? srcSh.getRange(2, 1) : srcHdr;
        var dstRange = dstSh.getRange(2, 1, dstLast - 1, 1);
        srcDataFmt.copyTo(dstRange, SpreadsheetApp.CopyPasteType.PASTE_FORMAT, false);
      }
      return jsonOut_({ ok: true, applied: true, before: before, after: after });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 診断: 題名(コメント)列の生値を調べる。(読み取り専用)
  //   ★「記録の題名が2行モードで2行になっている/改行やスペースが入る」報告(2026-07-23)の実態確認用。
  //   JSON化前の生文字列を返すので、改行・前後空白・連続空白の有無が正確に分かる。
  if (p.action === 'title_scan') {
    try {
      var tsOut = {};
      CH_SHEETS.forEach(function (nm) {
        var tsh2 = openSS_().getSheetByName(nm); if (!tsh2) { tsOut[nm] = null; return; }
        var tmap = headerMap_(tsh2), tCol2 = tmap['題名(コメント)'];
        var tlast = tsh2.getLastRow();
        if (!tCol2 || tlast < 2) { tsOut[nm] = { rows: [] }; return; }
        var n = Math.min(tlast - 1, 1000); // 実運用は数十行なので全件走査で問題ない
        var start = Math.max(2, tlast - n + 1);
        var tvals = tsh2.getRange(start, tCol2, tlast - start + 1, 1).getValues();
        var rows = [];
        for (var ti = 0; ti < tvals.length; ti++) {
          var raw = String(tvals[ti][0] || '');
          if (!raw) continue;
          rows.push({
            row: start + ti, raw: raw,
            hasNewline: /\r|\n/.test(raw),
            hasLeadTrailSpace: raw !== raw.trim(),
            hasDoubleSpace: /[ 　]{2,}/.test(raw)
          });
        }
        tsOut[nm] = { rows: rows };
      });
      return jsonOut_({ ok: true, scan: tsOut });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 実行: 題名(コメント)列の改行・行境の余分な空白を正規化する。(&apply=1 で実行・既定はdry-run)
  //   ★フロント側(app.js titleForBurn)は2026-07-23に「行ごとtrimしてから結合」へ修正済み(新規は再発しない)。
  //   これは修正前に記録された既存2行(月詠み row2/3)を一度だけ正す後始末。
  //   正規化＝改行で分割→各行trim→空区切りで結合→連続空白を1つに圧縮→全体trim。
  if (p.action === 'title_fix') {
    try {
      var tfApply = String(p.apply || '') === '1';
      var tfOut = [];
      CH_SHEETS.forEach(function (nm) {
        var tfsh = openSS_().getSheetByName(nm); if (!tfsh) { tfOut.push({ sheet: nm, status: 'not_found' }); return; }
        var tfmap = headerMap_(tfsh), tfCol = tfmap['題名(コメント)'];
        var tfLast = tfsh.getLastRow();
        if (!tfCol || tfLast < 2) { tfOut.push({ sheet: nm, status: 'no_title_col_or_empty' }); return; }
        var tfVals = tfsh.getRange(2, tfCol, tfLast - 1, 1).getValues();
        var changes = [];
        for (var fi = 0; fi < tfVals.length; fi++) {
          var raw = String(tfVals[fi][0] || ''); if (!raw) continue;
          var fixed = raw.split(/\r?\n/).map(function (l) { return l.trim(); }).join('').replace(/[ \t　]{2,}/g, ' ').trim();
          if (fixed !== raw) changes.push({ row: fi + 2, before: raw, after: fixed });
        }
        if (tfApply && changes.length) {
          changes.forEach(function (c) { tfsh.getRange(c.row, tfCol).setValue(c.after); });
        }
        tfOut.push({ sheet: nm, status: tfApply ? 'fixed' : 'dry_run', changeCount: changes.length, changes: changes });
      });
      return jsonOut_({ ok: true, applied: tfApply, result: tfOut });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 診断: 全列の「実データが入っている行数」を返す。(読み取り専用)
  //   ★列を消す前に「何が失われるか」を数える。0件なら消しても失うものは無い、と機械的に言える。
  //   数えずに消すのは取り返しがつかない(スプレッドシートはコードと違って戻せない)。
  if (p.action === 'column_fill') {
    try {
      var cfOut = {};
      CH_SHEETS.forEach(function (nm) {
        var csh = openSS_().getSheetByName(nm); if (!csh) { cfOut[nm] = null; return; }
        var clast = csh.getLastRow(), ccols = csh.getLastColumn();
        var chdr = csh.getRange(1, 1, 1, ccols).getValues()[0].map(String);
        var counts = {};
        if (clast >= 2) {
          var vals = csh.getRange(2, 1, clast - 1, ccols).getValues();
          for (var ci = 0; ci < ccols; ci++) {
            var n = 0;
            for (var ri = 0; ri < vals.length; ri++) {
              var v = vals[ri][ci];
              if (v !== '' && v !== null && v !== undefined) n++;
            }
            counts[chdr[ci]] = n;
          }
        } else { chdr.forEach(function (h) { counts[h] = 0; }); }
        cfOut[nm] = { dataRows: Math.max(0, clast - 1), counts: counts };
      });
      return jsonOut_({ ok: true, fill: cfOut });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // F列ジャンルの一括補完(③): <exec URL>?action=genre_fill で 作品URL から 同人/Books/データ を判定して ジャンル 列へ。
  //   既定は dry-run(何行が対象かを返すだけ)。&apply=1 で実際に書き込む。&force=1 で既存値も上書き(既定は空セルのみ)。
  if (p.action === 'genre_fill') {
    try {
      var gApply = String(p.apply || '') === '1', gForce = String(p.force || '') === '1';
      var gOut = [];
      CH_SHEETS.forEach(function (nm) {
        var gsh = openSS_().getSheetByName(nm);
        if (!gsh) { gOut.push({ sheet: nm, status: 'not_found' }); return; }
        var gmap = headerMap_(gsh), glast = gsh.getLastRow();
        var jc = gmap['ジャンル'], wc = gmap['作品URL'];
        if (!jc) { gOut.push({ sheet: nm, status: 'no_genre_col' }); return; }
        if (glast < 2) { gOut.push({ sheet: nm, status: 'no_rows' }); return; }
        var vals = gsh.getRange(2, 1, glast - 1, gsh.getLastColumn()).getValues();
        var filled = 0, skippedNoUrl = 0, sample = [];
        for (var r = 0; r < vals.length; r++) {
          var cur = vals[r][jc - 1];
          if (cur !== '' && cur !== null && cur !== undefined && !gForce) continue;
          var g = fanzaGenre_(wc ? vals[r][wc - 1] : '');
          if (!g) { if (!(cur !== '' && cur !== null)) skippedNoUrl++; continue; }
          if (String(cur) === g) continue;
          if (gApply) gsh.getRange(r + 2, jc).setValue(g);
          filled++;
          if (sample.length < 5) sample.push({ row: r + 2, genre: g });
        }
        gOut.push({ sheet: nm, dataRows: glast - 1, wouldFill: filled, skippedNoUrl: skippedNoUrl, applied: gApply, sample: sample });
      });
      return jsonOut_({ ok: true, mode: gApply ? 'apply' : 'dry-run', force: gForce, genre: gOut });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // ①バックアップ復元: <exec URL>?action=restore_from_bk&sheet=月詠み&bk=月詠み_bk_20260722_0834
  //   バックアップに在って本シートに無い post_id の行を、列名マッピングで本シートへ挿入し投稿日時で整列。
  //   既定 dry-run(挿入候補を返すだけ)。&apply=1 で実挿入。post_id一致は重複扱いでスキップ(冪等)。
  if (p.action === 'restore_from_bk') {
    try {
      var rbApply = String(p.apply || '') === '1';
      var rbOnlyPid = String(p.pid || ''); // 指定時はこのpost_idの1行だけ復元(Chami「2行目だけ」等の限定用)
      var liveNm = p.sheet || '月詠み', bkNm = p.bk || '';
      var rbss = openSS_();
      var live = rbss.getSheetByName(liveNm), bk = rbss.getSheetByName(bkNm);
      if (!live || !bk) return jsonOut_({ ok: false, error: 'sheet_not_found', liveExists: !!live, bkExists: !!bk });
      var lmap = headerMap_(live), bmap = headerMap_(bk);
      var lpid = lmap['post_id'], bpid = bmap['post_id'];
      if (!lpid || !bpid) return jsonOut_({ ok: false, error: 'no_postid_col' });
      var llast = live.getLastRow(), blast = bk.getLastRow(), lcols = live.getLastColumn();
      var lpids = {};
      if (llast >= 2) live.getRange(2, lpid, llast - 1, 1).getValues().forEach(function (r) { if (r[0] !== '' && r[0] !== null) lpids[String(r[0])] = 1; });
      var bhdr = bk.getRange(1, 1, 1, bk.getLastColumn()).getValues()[0];
      var brows = blast >= 2 ? bk.getRange(2, 1, blast - 1, bk.getLastColumn()).getValues() : [];
      var candidates = [], inserted = 0;
      for (var i = 0; i < brows.length; i++) {
        var pid = String(brows[i][bpid - 1] || '');
        if (!pid) continue;
        if (rbOnlyPid && pid !== rbOnlyPid) continue; // pid限定時は対象外をスキップ
        if (lpids[pid]) continue; // 既に本シートにある=重複挿入しない
        var newRow = [];
        for (var z = 0; z < lcols; z++) newRow.push('');
        for (var c = 0; c < bhdr.length; c++) { var lc = lmap[bhdr[c]]; if (lc) newRow[lc - 1] = brows[i][c]; }
        candidates.push({
          bkRow: i + 2, post_id: pid,
          投稿日時: String(bmap['投稿日時'] ? brows[i][bmap['投稿日時'] - 1] : ''),
          題名: String(bmap['題名(コメント)'] ? brows[i][bmap['題名(コメント)'] - 1] : '')
        });
        if (rbApply) { live.appendRow(newRow); inserted++; }
      }
      if (rbApply && inserted) sortByDate_(live, lmap['投稿日時'] || 2);
      return jsonOut_({ ok: true, mode: rbApply ? 'apply' : 'dry-run', live: liveNm, bk: bkNm, missingCount: candidates.length, inserted: inserted, candidates: candidates.slice(0, 20) });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // ②YouTube公開日時で投稿日時を修正: <exec URL>?action=fix_date_from_yt&channel=acc1&pids=pid1,pid2
  //   指定post_idの行のYouTube動画URLから動画IDを取り、YouTube Data APIのpublishedAtを投稿日時に設定。
  //   既定 dry-run(現状before→新値afterを返すだけ)。&apply=1 で書き込み。YT_API_KEY(スクリプトプロパティ)必須。
  //   pids未指定時はYouTube動画URLを持つ全行が対象(dry-runで差分を確認してから絞る想定)。
  if (p.action === 'fix_date_from_yt') {
    try {
      var fdApply = String(p.apply || '') === '1';
      var fdCh = p.channel || 'acc1';
      var fdPids = String(p.pids || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
      var ytKey = prop_('YT_API_KEY');
      if (!ytKey) return jsonOut_({ ok: false, error: 'no_YT_API_KEY' });
      var fsh = getChannelSheet_(fdCh), fmap = headerMap_(fsh);
      var fpidc = fmap['post_id'], fytc = fmap['YouTube動画URL'], fdc = fmap['投稿日時'];
      if (!fpidc || !fytc || !fdc) return jsonOut_({ ok: false, error: 'missing_col' });
      var fflast = fsh.getLastRow();
      if (fflast < 2) return jsonOut_({ ok: true, rows: [] });
      var fvals = fsh.getRange(2, 1, fflast - 1, fsh.getLastColumn()).getValues();
      var ftargets = [];
      for (var fi = 0; fi < fvals.length; fi++) {
        var fpid = String(fvals[fi][fpidc - 1] || '');
        if (fdPids.length && fdPids.indexOf(fpid) < 0) continue;
        var fyurl = String(fvals[fi][fytc - 1] || '');
        var fm = fyurl.match(/(?:shorts\/|watch\?v=|youtu\.be\/|embed\/|live\/)([A-Za-z0-9_-]{11})/);
        if (!fm) continue;
        ftargets.push({ row: fi + 2, pid: fpid, vid: fm[1], cur: String(fvals[fi][fdc - 1] || '') });
      }
      var fout = [];
      for (var fb = 0; fb < ftargets.length; fb += 50) {
        var fslice = ftargets.slice(fb, fb + 50);
        var fids = fslice.map(function (x) { return x.vid; }).join(',');
        var fres = UrlFetchApp.fetch('https://www.googleapis.com/youtube/v3/videos?part=snippet&id=' + fids + '&key=' + ytKey, { muteHttpExceptions: true });
        var fdata = JSON.parse(fres.getContentText() || '{}');
        var fById = {};
        (fdata.items || []).forEach(function (it) { fById[it.id] = it.snippet && it.snippet.publishedAt; });
        fslice.forEach(function (x) {
          var pub = fById[x.vid];
          if (!pub) { fout.push({ row: x.row, pid: x.pid, vid: x.vid, status: 'no_yt_data' }); return; }
          if (fdApply) fsh.getRange(x.row, fdc).setValue(new Date(pub));
          fout.push({ row: x.row, pid: x.pid, vid: x.vid, before: x.cur, after: pub, applied: fdApply });
        });
      }
      if (fdApply && fout.length) sortByDate_(fsh, fdc);
      return jsonOut_({ ok: true, mode: fdApply ? 'apply' : 'dry-run', channel: fdCh, rows: fout });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // ③データ整合修正(軍議REQ-gunji-5213170ea8 #3): <exec URL>?action=fix_records_0823&task=untest|merge_dup
  //   ★既定 dry-run(何をするか返すだけ)。&apply=1 の時だけ実書き込み。破壊(行削除)は merge_dup の drop 行1本のみ。
  //   task=untest  : 記録シートの post_id に混入した 'test-' 接頭辞を剥がす(テストIDがprodへ漏れた行)。
  //                  channel(既定acc1=月詠み)/pid(限定・省略時は 'test-' で始まる全行)。剥がした先が既存と衝突する行は
  //                  触らない(collision=true で報告)。post_id 以外の列は一切変えない。
  //   task=merge_dup: 同一ytid&同一cidで2行に割れた記録を「統合」する(削除ではない)。keep(残す=題名が入っている方)へ
  //                  drop(消す)の非空セルだけを埋め(keepが空の列のみ・keepの既存値は上書きしない)、そのうえで drop 行を1本削除。
  //                  keep/drop(post_id)必須。両行の ytid が一致し、かつ cid が一致(または一方が空)でない限り apply しない(fail-safe)。
  if (p.action === 'fix_records_0823') {
    try {
      var frApply = String(p.apply || '') === '1';
      var frTask = String(p.task || '');
      var frCh = p.channel || 'acc1';
      var frSh = getChannelSheet_(frTask === 'merge_dup' ? (p.channel || 'acc2') : frCh);
      var frMap = headerMap_(frSh);
      var frPidC = frMap['post_id'], frYtC = frMap['YouTube動画URL'], frCidC = frMap['作品cid'], frTitC = frMap['題名(コメント)'];
      if (!frPidC) return jsonOut_({ ok: false, error: 'no_postid_col' });
      var frLast = frSh.getLastRow();
      if (frLast < 2) return jsonOut_({ ok: true, mode: 'dry-run', rows: [], note: 'empty_sheet' });
      var frCols = frSh.getLastColumn();
      var frVals = frSh.getRange(2, 1, frLast - 1, frCols).getValues();
      var isBlank_ = function (x) { return x === '' || x === null || (typeof x === 'string' && x.trim() === ''); };

      if (frTask === 'untest') {
        var utLimitPid = String(p.pid || '');
        var frExist = {}; frVals.forEach(function (r) { frExist[String(r[frPidC - 1] || '')] = 1; });
        var utOut = [], utApplied = 0;
        for (var ui = 0; ui < frVals.length; ui++) {
          var utPid = String(frVals[ui][frPidC - 1] || '');
          if (utPid.indexOf('test-') !== 0) continue;
          if (utLimitPid && utPid !== utLimitPid) continue;
          var utNew = utPid.replace(/^test-/, '');
          var utCollide = !!frExist[utNew];
          var utDo = frApply && !utCollide;
          if (utDo) { frSh.getRange(ui + 2, frPidC).setValue(utNew); utApplied++; }
          utOut.push({ row: ui + 2, before: utPid, after: utNew, collision: utCollide, applied: utDo,
                       title: frTitC ? String(frVals[ui][frTitC - 1] || '') : '' });
        }
        return jsonOut_({ ok: true, mode: frApply ? 'apply' : 'dry-run', task: 'untest', channel: frCh, count: utOut.length, applied: utApplied, rows: utOut });
      }

      if (frTask === 'merge_dup') {
        var mdKeep = String(p.keep || 'acc2-20260821-1954-z0f3');
        var mdDrop = String(p.drop || 'acc2-20260821-2023-ri4e');
        var keepIdx = -1, dropIdx = -1;
        for (var mi = 0; mi < frVals.length; mi++) {
          var mpid = String(frVals[mi][frPidC - 1] || '');
          if (mpid === mdKeep) keepIdx = mi;
          if (mpid === mdDrop) dropIdx = mi;
        }
        if (keepIdx < 0 || dropIdx < 0) return jsonOut_({ ok: false, error: 'row_not_found', keepFound: keepIdx >= 0, dropFound: dropIdx >= 0 });
        var keepRow = frVals[keepIdx], dropRow = frVals[dropIdx];
        var kYt = frYtC ? ytIdFromUrl_(keepRow[frYtC - 1]) : '', dYt = frYtC ? ytIdFromUrl_(dropRow[frYtC - 1]) : '';
        var kCid = frCidC ? String(keepRow[frCidC - 1] || '') : '', dCid = frCidC ? String(dropRow[frCidC - 1] || '') : '';
        var ytOk = (kYt && dYt && kYt === dYt);
        var cidOk = (kCid === dCid) || isBlank_(kCid) || isBlank_(dCid);
        var fills = [];
        for (var mc = 0; mc < frCols; mc++) {
          if (mc === frPidC - 1) continue; // post_id は統合しない
          if (isBlank_(keepRow[mc]) && !isBlank_(dropRow[mc])) fills.push({ col: mc + 1, header: frSh.getRange(1, mc + 1).getValue(), value: dropRow[mc] });
        }
        var mdApplied = false, mdDeleted = false;
        if (frApply && ytOk && cidOk) {
          fills.forEach(function (f) { frSh.getRange(keepIdx + 2, f.col).setValue(f.value); });
          frSh.deleteRow(dropIdx + 2); // 統合後に drop 行を1本削除
          mdApplied = true; mdDeleted = true;
        }
        return jsonOut_({ ok: true, mode: frApply ? 'apply' : 'dry-run', task: 'merge_dup', channel: p.channel || 'acc2',
          keep: mdKeep, drop: mdDrop, keepRow: keepIdx + 2, dropRow: dropIdx + 2,
          ytid: { keep: kYt, drop: dYt, match: ytOk }, cid: { keep: kCid, drop: dCid, ok: cidOk },
          wouldFill: fills.map(function (f) { return { header: String(f.header), value: String(f.value).slice(0, 60) }; }),
          applied: mdApplied, deletedDropRow: mdDeleted,
          guard: (ytOk && cidOk) ? 'ok' : 'BLOCKED(ytid/cid不一致=applyしない)' });
      }

      return jsonOut_({ ok: false, error: 'unknown_task', task: frTask, hint: 'task=untest|merge_dup' });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 末尾の空行を詰める: <exec URL>?action=trim_empty_rows
  //   ★既定は dry-run(数えるだけ・消さない)。実際に消すのは &apply=1 を付けた時だけ。
  //     行削除は列と違って「1行ズレただけで別の行が消える」ので、まず何が消えるかを見る。
  //   ★安全条件を満たさない限り消さない:
  //     ・削除するのは「最後の実データ行より下」だけ(データの間に挟まった空行には触らない)
  //     ・その範囲の全セルが空であることを実際に確認してから消す
  //   ・数式だけが入っている行も「空」とみなさない(getValuesは数式の結果を返すため、
  //     結果が空文字なら空と判定される=意図せず消えるのを防ぐためgetFormulasも見る)
  if (p.action === 'trim_empty_rows') {
    try {
      var apply = String(p.apply || '') === '1';
      var trOut = [];
      CH_SHEETS.forEach(function (nm) {
        var tsh = openSS_().getSheetByName(nm);
        if (!tsh) { trOut.push({ sheet: nm, status: 'not_found' }); return; }
        var maxRow = tsh.getMaxRows(), cols = tsh.getLastColumn();
        if (maxRow < 2 || cols < 1) { trOut.push({ sheet: nm, status: 'empty_sheet' }); return; }
        var vals = tsh.getRange(2, 1, maxRow - 1, cols).getValues();
        var frms = tsh.getRange(2, 1, maxRow - 1, cols).getFormulas();
        // ★境界は「表示される値がある最後の行」。数式が残っているだけの行は空とみなす。
        //   実測(宵桜艶帖)で分かったこと: 行を1000まで占有していたのは空行ではなく、
        //   曜日/day-type/時間帯スロット/リンククリック率% の**数式の残骸**だった(974行分)。
        //   これらは参照先が空なので表示は空。見た目は空行なのに「中身あり」と判定され消せなかった。
        //   値が無い＝表示上なにも失われないので、数式ごと行を消してよい。
        //   (逆に値がある行より上は絶対に触らない。データの間に挟まった空行も残す)
        var lastUsed = 1; // シート行番号(1=ヘッダ)
        for (var i = 0; i < vals.length; i++) {
          for (var c = 0; c < cols; c++) {
            if (vals[i][c] !== '' && vals[i][c] !== null) { lastUsed = i + 2; break; }
          }
        }
        var firstTrim = lastUsed + 1, count = maxRow - lastUsed;
        // 「値は無いが数式だけ残っている行」がどこから始まり、どの列が原因かを併せて返す。
        //   これが分かると「空に見えるのに消せない行」の正体が特定できる。
        var lastValue = 1, hdr = tsh.getRange(1, 1, 1, cols).getValues()[0].map(String);
        for (var vi = 0; vi < vals.length; vi++) {
          for (var vc = 0; vc < cols; vc++) {
            if (vals[vi][vc] !== '' && vals[vi][vc] !== null) { lastValue = vi + 2; break; }
          }
        }
        var ghostCols = {};
        for (var gi = lastValue - 1; gi < frms.length; gi++) {          // 最終“値”行より下
          for (var gc = 0; gc < cols; gc++) { if (frms[gi][gc] !== '') ghostCols[hdr[gc]] = (ghostCols[hdr[gc]] || 0) + 1; }
        }
        var info = { sheet: nm, maxRows: maxRow, lastUsedRow: lastUsed, lastValueRow: lastValue,
                     trimFrom: firstTrim, trimCount: count, formulaOnlyBelowValue: ghostCols };
        if (count <= 0) { info.status = 'already_tight'; trOut.push(info); return; }
        if (!apply) { info.status = 'dry_run'; trOut.push(info); return; }
        tsh.deleteRows(firstTrim, count);
        info.status = 'trimmed';
        info.maxRowsAfter = tsh.getMaxRows();
        trOut.push(info);
      });
      return jsonOut_({ ok: true, applied: apply, result: trOut });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 不要列の削除: <exec URL>?action=cleanup_columns で CLEANUP_COLUMNS の列を各シートから削除。(冪等)
  if (p.action === 'cleanup_columns') {
    return jsonOut_(cleanupColumns_());
  }
  // 列順統一(⑥): <exec URL>?action=reorder_headers で両chシートの列をCANONICAL_HEADERS順へ固定。(冪等)
  if (p.action === 'reorder_headers') {
    return jsonOut_(reorderHeaders_());
  }
  // 診断: <exec URL>?action=diagnose でスプレッドシート名・全タブ名・各記録タブの中身を返す。(読み取りのみ)
  if (p.action === 'diagnose') {
    return jsonOut_(diagnose_());
  }
  // 後埋まり列の実データ着地プローブ: <exec URL>?action=backfill_probe で、ピーク値/クリック数/いいね等
  //   「N時間後に埋まる列」の非空行数と最終更新時刻を返す。(読み取りのみ)型《実物着地》の読取口。
  if (p.action === 'backfill_probe') {
    try { return jsonOut_(backfillProbe_()); } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 視聴履歴.作品クリック数 が 0/1204 で未着地の枝判定用プローブ(読み取り専用・書き込み無し)。
  //   snapshotStats の recs(vid必須＋vidで先頭dedup)を再現し、導線2(作品短縮URL=wcode)を持つ行が
  //   「vidを持つ行」で起きているか(枝A=writer取りこぼし)/「vid無し行中心」か(枝B=構造的に載らない)を実データで返す。
  if (p.action === 'wcode_probe') {
    try { return jsonOut_(wcodeVidProbe_()); } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 行分類と件数: <exec URL>?action=sheet_audit で各記録シートの行を分類して返す。(読み取りのみ)
  //   complete=postUri+YT両方あり / no_yt=postUriのみ / no_uri=YTのみ / minimal=どちらも無 / empty=post_id空
  //   ヘッダー一覧とCANONICALとの差分(missing/extra)も同時に返す。
  if (p.action === 'sheet_audit') {
    try { return jsonOut_(sheetAudit_()); } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // バックアップ: <exec URL>?action=backup_sheets で両記録シートを同スプレッドシート内にコピーする。(読み取りのみ)
  //   コピー先タブ名: <シート名>_bk_<YYYYMMdd_HHmm>。削除・上書きはしない。
  if (p.action === 'backup_sheets') {
    try { return jsonOut_(backupSheets_()); } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 診断: 視聴履歴(スナップショット)の末尾N行を返す。(読み取りのみ)
  //   YT_API_KEY が効いて views が記録できているか等、サーバー自動記録の生存確認用。
  if (p.action === 'stats_tail') {
    try {
      var ssh = statsSheet_(); var slast = ssh.getLastRow();
      var n = Math.min(Math.max(parseInt(p.n || '5', 10) || 5, 1), 20);
      var rows = slast >= 2 ? ssh.getRange(Math.max(2, slast - n + 1), 1, Math.min(n, slast - 1), STATS_HEADERS.length).getValues() : [];
      return jsonOut_({ ok: true, headers: STATS_HEADERS, totalRows: Math.max(0, slast - 1), tail: rows });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 診断: 無人予約投稿の待機状況を返す。(読み取りのみ・投稿はしない)
  //   ★2026-07-21追加: Bluesky凍結多発を受け「予約が自動発射し続けていないか」を外から確認するため。
  //   端末側(localStorage)の予約は見えないが、GAS側の無人予約はここで把握できる。
  //   本文は出さない(先頭20字のみ)=秘匿情報を診断URLに載せない。
  if (p.action === 'reservations_status') {
    try {
      var rsh = getResSheet_(), rlast = rsh.getLastRow();
      var counts = { pending: 0, posting: 0, posted: 0, error: 0, other: 0 }, upcoming = [];
      if (rlast >= 2) {
        var rrows = rsh.getRange(2, 1, rlast - 1, RES_HEADERS.length).getValues();
        for (var ri = 0; ri < rrows.length; ri++) {
          var st = String(rrows[ri][RCOL.status - 1] || '');
          if (counts[st] == null) counts.other++; else counts[st]++;
          if (st === 'pending' || st === 'posting') {
            var w = rrows[ri][RCOL.when - 1];
            upcoming.push({
              row: ri + 2, status: st, when: w ? String(w) : '',
              channel: String(rrows[ri][RCOL.channel - 1] || ''),
              textHead: String(rrows[ri][RCOL.text - 1] || '').slice(0, 20)
            });
          }
        }
      }
      // 5分トリガー(runReservations)が生きているか＝自動発射の有無を判断する材料
      var trg = [];
      try { trg = ScriptApp.getProjectTriggers().map(function (t) { return t.getHandlerFunction(); }); } catch (e) {}
      return jsonOut_({
        ok: true, totalRows: Math.max(0, rlast - 1), counts: counts,
        upcoming: upcoming.slice(0, 20),
        runReservationsTriggerAlive: trg.indexOf('runReservations') >= 0,
        triggers: trg, now: new Date().toISOString()
      });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 題名集約: <exec URL>?action=consolidate_title で「YouTube題名」を「題名(コメント)」へ移し、列を削除。
  if (p.action === 'consolidate_title') {
    return jsonOut_(consolidateTitle_());
  }
  // 競合サーチ(gas/競合.gs)。部門はWebFetchでJSONを読む。設計書=docs/設計・調査/設計書_YouTube競合サーチ.md
  if (p.action === 'comp_digest' && !p.callback) { return jsonOut_(compDigest_()); }                       // 分析部: 週次サマリ(callback時は下のJSONP分岐へ)
  if (p.action === 'comp_titles' && !p.callback) { return jsonOut_(compTitles_(p.days, p.top)); }           // コピー部: 速度順タイトルコーパス(同上)
  if (p.action === 'comp_daily_now') { try { return jsonOut_(runCompetitorDaily()); } catch (err) { return jsonOut_({ ok: false, error: String(err) }); } }
  if (p.action === 'comp_discovery_now') { try { return jsonOut_(runCompetitorDiscovery()); } catch (err) { return jsonOut_({ ok: false, error: String(err) }); } }
  if (p.action === 'comp_add_seed' && !p.callback) { try { return jsonOut_(compAddSeed_(p.url, p.name, p.bluesky, p.x, p.note)); } catch (err) { return jsonOut_({ ok: false, error: String(err) }); } }  // シード登録(callback時は下のJSONP分岐へ)
  if (p.action === 'comp_ensure_tabs') { try { return jsonOut_(compEnsureTabs_()); } catch (err) { return jsonOut_({ ok: false, error: String(err) }); } }  // 全タブ確保(手動記録タブ含む)
  if (p.action === 'comp_frame_pending') { try { return jsonOut_(compFramePending_(p.limit)); } catch (err) { return jsonOut_({ ok: false, error: String(err) }); } }  // 代表フレーム未取得のShort一覧(PC側スクレイパが引く)
  // ★一時診断(2026-08-16): snapshotStatsのviewsが全null(DIAG viewsKeys=0)の切り分け=キー有無とYT APIの実HTTP応答を返す。読み取りのみ。確認後に除去。
  if (p.action === 'yt_probe') {
    var _yk = ytApiKey_(); var _pi = { keyLen: _yk.length, vid: p.vid || '1uag-mo-kGQ' };
    if (_yk) { try {
      var _pu = 'https://www.googleapis.com/youtube/v3/videos?part=statistics&id=' + _pi.vid + '&key=' + encodeURIComponent(_yk);
      var _pr = UrlFetchApp.fetch(_pu, { muteHttpExceptions: true });
      _pi.http = _pr.getResponseCode(); _pi.body = String(_pr.getContentText() || '').slice(0, 300);
    } catch (e) { _pi.err = String(e); } }
    // ★バッチ経路を実物で通す=ytViews_に[実vid, 'SALE:xxxx']を渡し、コロン混入バッチが400で全滅するか確認。
    var _tb = (p.ids ? String(p.ids).split(',') : [_pi.vid, 'SALE:krQsP']);
    var _bd = []; var _bv = ytViews_(_tb, null, _bd);
    _pi.batchIds = _tb; _pi.batchDiag = _bd; _pi.batchViewsKeys = Object.keys(_bv).length; _pi.batchViews = _bv;
    return jsonOut_(_pi);
  }
  // デプロイ後の自動後処理: トリガー再設定＋ヘッダ移行を一括冪等実行。(scripts/deploy_gas.mjs が反映確認後に呼ぶ)
  //   secret はスクリプトプロパティ ADMIN_SECRET(未設定なら固定のソフト鍵にフォールバック)と照合。
  //   ※ソフト鍵は deploy_gas.mjs の SOFT_ADMIN_SECRET と一致させる。(短縮URL用 shortSecret_ とは独立)
  if (p.action === 'admin_setup') {
    var adminWant = prop_('ADMIN_SECRET') || 'daremogamewoubawareteikukimihakanpekidekyukyokunoidol';
    if (String(p.secret || '') !== adminWant) return jsonOut_({ ok: false, error: 'bad_secret' });
    var mig = migrateHeaders_();
    var reo = reorderHeaders_(); // ⑥列順統一もデプロイ毎に冪等適用(以後ズレない)
    setupTrigger();
    var handlers = ScriptApp.getProjectTriggers().map(function (t) { return t.getHandlerFunction(); });
    return jsonOut_({ ok: true, version: GAS_VERSION, migrated: mig, reordered: reo, triggers: handlers });
  }
  // JSONP：ブラウザはGASのPOST応答をCORSで読めないため、callback 付きGETで取得する。
  if (p.callback) {
    var out;
    try {
      var ch = p.channel || 'acc1';
      if (p.action === 'history') out = { ok: true, items: historyItems_(ch, parseInt(p.limit || '40', 10)) };
      else if (p.action === 'posted_cids') out = postedCids_(p.channel || 'both'); // 投稿済み判定の権威索引(読み取り専用・c/w両空行は除外・prefixガード)

      else if (p.action === 'delete') out = { ok: true, deleted: deleteRecord_(ch, p.videoId || '', p.postUri || '', p.short || '') };
      else if (p.action === 'settings_pull') out = settingsPull_();   // 端末間同期：非秘密設定の取得
      else if (p.action === 'settings_meta') out = settingsMeta_();   // 端末間同期：最終保存メタのみ(状態表示)
      else if (p.action === 'deltas') out = { ok: true, deltas: computeDeltas_(), peaks: computePeaks_(), timepoints: computeTimepoints_() }; // 今日/昨日/週の増加＋最大瞬間風速＋公開起点の時点記録(過去分・アプリ未起動でも記録)
      else if (p.action === 'comp_digest') out = compDigest_();                          // 競合: 週次サマリ(分析タブ表示用)
      else if (p.action === 'comp_titles') out = compTitles_(p.days, p.top);             // 競合: 題名コーパス(分析タブ表示用)
      else if (p.action === 'comp_add_seed') out = compAddSeed_(p.url, p.name, p.bluesky, p.x, p.note); // 競合: フロント登録→GASへ同期
      else if (p.action === 'sale_reg') out = saleReg_(p.acc, p.sale);                 // 名前付きセールURLの短縮コードを登録(snapshotStatsが各コードを日次スナップ)
      else if (p.action === 'snapshot_now') { var _diag = snapshotStats(); out = { ok: true, snapped: true, diag: _diag }; } // 手動で即スナップ
      else if (p.action === 'click_agg') out = { ok: true, version: GAS_VERSION, at: new Date().toISOString(), works: clicksByWork_(p.channel || 'both') }; // 作品別クリック合算(読み取り)
      else if (p.action === 'rebuild_click_agg') out = { ok: true, works: rebuildClickAggSheet_() };  // 合算シートを即再構築
      else out = { ok: true, shortUrl: p.postUri ? lookupShortByUri_(ch, p.postUri) : '' }; // 既定＝action=short
    } catch (err) { out = { ok: false, error: String(err) }; }
    return ContentService.createTextOutput(p.callback + '(' + JSON.stringify(out) + ')')
      .setMimeType(ContentService.MimeType.JAVASCRIPT);
  }
  // 該当アクション無し。どのバージョンが live か常に分かるよう version と対応アクションを返す。
  return jsonOut_({ ok: true, service: 'go5-maker recorder v2 (2ch)', version: GAS_VERSION,
    actions: ['ping', 'migrate_headers', 'cleanup_columns', 'diagnose', 'admin_setup'],
    note: 'diagnose が service応答になる場合は diagnose 追加版(2026-07-01F以降)が未デプロイ' });
}
// 指定 post_uri の行から短縮URLを返す。(読み取りのみ)
function lookupShortByUri_(channel, postUri) {
  var sh = getChannelSheet_(channel), map = headerMap_(sh);
  var last = sh.getLastRow(); if (last < 2) return '';
  var uc = map['post_uri'], sc = map['短縮URL']; if (!uc || !sc) return '';
  var uris = sh.getRange(2, uc, last - 1, 1).getValues();
  for (var i = uris.length - 1; i >= 0; i--) {  // 新しい順に探す
    if (String(uris[i][0]) === String(postUri)) return String(sh.getRange(i + 2, sc).getValue() || '');
  }
  return '';
}
// チャンネル別の投稿履歴。(新しい順・読み取りのみ)
function historyItems_(channel, limit) {
  var sh = getChannelSheet_(channel), map = headerMap_(sh);
  var last = sh.getLastRow(); if (last < 2) return [];
  var dCol = map['投稿日時'], tCol = map['題名(コメント)'], sCol = map['短縮URL'], uCol = map['post_uri'];
  var yCol = map['YouTube動画URL']; // 端末のverify_yt消失時にここから復元できるよう返す
  var pidCol = map['post_id'], shareCol = map['共有URL'], wsCol = map['作品状態'], cidCol = map['作品cid']; // 端末の投稿履歴復元用
  var lpCol = map['元値list_price'], prCol = map['割引後price'], pctCol = map['割引率pct'], fatCol = map['FANZA取得日時']; // 投稿当時(スナップ)の価格＝シート由来行にも復元して表示する
  var wsuCol = map['作品短縮URL']; // 導線2(作品クリック=ピンク矢印)の計測URL＝シート由来行にも復元して表示する
  var wuCol = map['作品URL'];       // 作品URLそのもの＝cidから復元できない階層でも作品↗を戻すため優先して返す
  var pfCol = map['投稿先'];         // 投稿先(x/bsky)＝短縮URLだけの行はURLから判別できないため手動指定を返す(X↗/Bsky↗表示)
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';
  var vals = sh.getRange(2, 1, last - 1, sh.getLastColumn()).getValues();
  var items = [];
  for (var i = 0; i < vals.length; i++) {
    var row = vals[i];
    var d = dCol ? row[dCol - 1] : '', uri = uCol ? row[uCol - 1] : '', short = sCol ? row[sCol - 1] : '';
    var pid = pidCol ? row[pidCol - 1] : '';
    if (!d && !uri && !short && !pid) continue; // 完全な空行だけスキップ。動画IDだけ残る異常行も削除用に返す
    var ds = '', iso = '';
    try { if (d) { var dd = new Date(d); ds = Utilities.formatDate(dd, tz, 'MM/dd HH:mm'); iso = dd.toISOString(); } } catch (e) {}
    items.push({
      postUri: String(uri || ''), title: String(tCol ? row[tCol - 1] : ''),
      date: ds, postedAt: iso, shortUrl: String(short || ''), shareUrl: String(shareCol ? (row[shareCol - 1] || '') : ''), postUrl: '',
      videoId: String(pid || ''),
      workState: String(wsCol ? (row[wsCol - 1] || '') : ''),
      cid: String(cidCol ? (row[cidCol - 1] || '') : ''), // 作品URL復元用(cid→作品URLをフロントで再構成)
      youtubeUrl: String(yCol ? (row[yCol - 1] || '') : ''),
      // 投稿当時の価格(スナップ)。空欄はそのまま''で返し、フロントが数値のときだけ fanzaSnap を組む。
      fanzaListPrice: lpCol ? row[lpCol - 1] : '',
      fanzaPrice: prCol ? row[prCol - 1] : '',
      fanzaDiscountPct: pctCol ? row[pctCol - 1] : '',
      fanzaFetchedAt: fatCol ? String(row[fatCol - 1] || '') : '',
      workShortUrl: wsuCol ? String(row[wsuCol - 1] || '') : '', // 導線2(作品クリック)の計測URL
      workUrl: wuCol ? String(row[wuCol - 1] || '') : '', // 作品URLそのもの(あれば優先・cid復元のフォールバックに勝つ)
      platform: pfCol ? String(row[pfCol - 1] || '') : '' // 投稿先(x/bsky)＝X↗/Bsky↗表示の手動指定
    });
  }
  items.reverse(); // 新しい順
  return items.slice(0, limit > 0 ? limit : 40);
}
// 投稿済み判定の権威索引(読み取り専用・軽量)。historyItems_ の縮小版=全行を4列だけ射影して返す。
//   フロント候補タブの✔pillを「端末ローカルの短縮URL履歴」でなく「チャンネル別シート」で判定させ、
//   偽陽性(記録_ch2に無ければacc2は未投稿)と偽陰性(全端末が同じシートを読む=端末分断で✔が出ない)を
//   構造的に消す(設計書_投稿済み判定の権威ソース化_2026-07-31 S1)。c/w両空の行は判定に使えないので除外。
function postedCidsOne_(channel) {
  var sh = getChannelSheet_(channel), map = headerMap_(sh);
  var last = sh.getLastRow(); if (last < 2) return [];
  var cidCol = map['作品cid'], wuCol = map['作品URL'], pidCol = map['post_id'], dCol = map['投稿日時'];
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';
  var vals = sh.getRange(2, 1, last - 1, sh.getLastColumn()).getValues();
  var out = [];
  for (var i = 0; i < vals.length; i++) {
    var row = vals[i];
    var c = cidCol ? String(row[cidCol - 1] || '') : '';
    var w = wuCol ? String(row[wuCol - 1] || '') : '';
    if (!c && !w) continue; // c/w両空=投稿済み判定に使えない行は出さない
    var pid = pidCol ? String(row[pidCol - 1] || '') : '';
    // サーバー側prefixガード：背骨ID(post_id)の acc-prefix がこのシートのchと矛盾する行は除外(fail-open：prefix無し行は通す)。
    var pm = pid.match(/^(?:test-)?(acc[12])-/);
    if (pm && pm[1] !== channel) continue;
    var t = '';
    if (dCol) { try { var d = row[dCol - 1]; if (d) t = Utilities.formatDate(new Date(d), tz, 'yyyy-MM-dd'); } catch (e) {} }
    out.push({ c: c, w: w, v: pid, t: t });
  }
  return out;
}
// channel='acc1'|'acc2'|'both'(既定 both)。指定ch以外は空配列で返す。
function postedCids_(channel) {
  var ch = channel || 'both';
  var res = { ok: true, version: GAS_VERSION, at: new Date().toISOString(), acc1: [], acc2: [] };
  if (ch === 'acc1' || ch === 'both') res.acc1 = postedCidsOne_('acc1');
  if (ch === 'acc2' || ch === 'both') res.acc2 = postedCidsOne_('acc2');
  return res;
}
// 1件削除。(行の内容をクリア＝再利用可。行は詰めない＝集計の整合を保つ)
// 安定動画ID(post_id)を最優先し、無ければ post_uri、短縮URLの順。URL欠損の異常行も削除できる。
function deleteRecord_(channel, videoId, postUri, short) {
  var sh = getChannelSheet_(channel), map = headerMap_(sh);
  var last = sh.getLastRow(); if (last < 2) return 0;
  var col = videoId ? map['post_id'] : (postUri ? map['post_uri'] : map['短縮URL']);
  var want = videoId || postUri || short; if (!col || !want) return 0;
  var vals = sh.getRange(2, col, last - 1, 1).getValues(), cleared = 0;
  for (var i = 0; i < vals.length; i++) {
    if (String(vals[i][0]) === String(want)) { sh.getRange(i + 2, 1, 1, sh.getLastColumn()).clearContent(); cleared++; }
  }
  return cleared;
}

// 行をチャンネル間で移動：videoId(post_id)→post_uri→短縮URL の順で元行を特定し、目的チャンネルへ
// 全列コピー(計算式列は式を貼り直し)＋元行をクリア。アカウント誤記録の矯正に使う。
function moveRow_(from, to, videoId, postUri, short) {
  if (!from || !to || from === to) return { ok: false, error: 'bad_channel' };
  var src = getChannelSheet_(from), smap = headerMap_(src); var slast = src.getLastRow(); if (slast < 2) return { ok: false, error: 'empty_src' };
  var keyDefs = [];
  if (videoId && smap['post_id']) keyDefs.push([smap['post_id'], videoId]);
  if (postUri && smap['post_uri']) keyDefs.push([smap['post_uri'], postUri]);
  if (short && smap['短縮URL']) keyDefs.push([smap['短縮URL'], short]);
  if (!keyDefs.length) return { ok: false, error: 'no_key' };
  var srow = 0;
  for (var ki = 0; ki < keyDefs.length && !srow; ki++) {
    var col = keyDefs[ki][0], want = String(keyDefs[ki][1]);
    var kv = src.getRange(2, col, slast - 1, 1).getValues();
    for (var i = 0; i < kv.length; i++) { if (String(kv[i][0]) === want) { srow = i + 2; break; } }
  }
  if (!srow) return { ok: false, error: 'src_not_found' };
  var headers = src.getRange(1, 1, 1, src.getLastColumn()).getValues()[0].map(String);
  var srcVals = src.getRange(srow, 1, 1, src.getLastColumn()).getValues()[0];
  var dst = getChannelSheet_(to), dmap = headerMap_(dst); var dlast = dst.getLastRow();
  var vid2 = videoId || (smap['post_id'] ? srcVals[smap['post_id'] - 1] : '');
  var target = 0;
  if (vid2 && dmap['post_id'] && dlast >= 2) {
    var pv = dst.getRange(2, dmap['post_id'], dlast - 1, 1).getValues();
    for (var j = 0; j < pv.length; j++) { if (String(pv[j][0]) === String(vid2)) { target = j + 2; break; } }
  }
  if (!target) {
    var ddc = dmap['投稿日時'] || 2;
    if (dlast >= 2) { var dv = dst.getRange(2, ddc, dlast - 1, 1).getValues(); for (var k = 0; k < dv.length; k++) { if (dv[k][0] === '' || dv[k][0] === null) { target = k + 2; break; } } }
    if (!target) target = dlast + 1;
  }
  setComputed_(dst, dmap, target); // 計算式列は式を貼る(値上書きしない)
  // 数式で自動計算される列。(手で書き込まない)FANZA成約由来の数式は2026-07-23に撤去済み。
  var COMPUTED = { '曜日': 1, 'day-type': 1, '時間帯スロット': 1, 'リンククリック率%': 1, 'タイトル文字数': 1 };
  headers.forEach(function (h, ci) {
    if (COMPUTED[h]) return;             // 計算式列は上書きしない
    var dc = dmap[h]; if (!dc) return;   // 目的地に無い列はスキップ
    dst.getRange(target, dc).setValue(srcVals[ci]); // 空も含め忠実にコピー
  });
  src.getRange(srow, 1, 1, src.getLastColumn()).clearContent(); // 元行クリア(行は詰めない＝集計整合)
  return { ok: true, moved: 1, from: from, to: to };
}

// 既存シートに FANZA_HEADERS を末尾追加する一回限りの移行関数。
// <exec URL>?action=migrate_headers で呼ぶ。既に存在する列は追加しない。(冪等)
function migrateHeaders_() {
  var result = [];
  var ss = openSS_();
  CH_SHEETS.forEach(function (name) {
    var sh = ss.getSheetByName(name);
    if (!sh) { result.push({ sheet: name, status: 'not_found' }); return; }
    var lastCol = sh.getLastColumn();
    if (lastCol < 1) { result.push({ sheet: name, status: 'empty' }); return; }
    var existing = sh.getRange(1, 1, 1, lastCol).getValues()[0].map(String);
    // クリック数列の見出しを「短縮URLクリック数」に統一。(旧名 開封数/Bitlyクリック はデータ保持のまま改名)
    var renamed = '';
    if (existing.indexOf('短縮URLクリック数') === -1) {
      var ai = existing.indexOf('開封数'); if (ai === -1) ai = existing.indexOf('Bitlyクリック');
      if (ai >= 0) { sh.getRange(1, ai + 1).setValue('短縮URLクリック数'); existing[ai] = '短縮URLクリック数'; renamed = '短縮URLクリック数'; }
    }
    // 「キャラ」列を「カテゴリ」へ改名。(旧○方式→属性名明記方式。データ保持のまま)
    var renamedCat = '';
    if (existing.indexOf('カテゴリ') === -1 && existing.indexOf('キャラ') >= 0) {
      var ci = existing.indexOf('キャラ');
      sh.getRange(1, ci + 1).setValue('カテゴリ'); existing[ci] = 'カテゴリ'; renamedCat = 'カテゴリ';
    }
    // 不足列を末尾に追加。(短縮URLクリック数が旧名も無く欠けていればここで新設)
    var wantHeaders = FANZA_HEADERS.concat(EXTRA_HEADERS).concat(['短縮URLクリック数']);
    var missing = wantHeaders.filter(function (h) { return existing.indexOf(h) === -1; });
    if (missing.length === 0 && !renamed && !renamedCat) { result.push({ sheet: name, added: [], renamedClick: '', renamedCategory: '', status: 'already_up_to_date' }); return; }
    missing.forEach(function (h) {
      sh.getRange(1, sh.getLastColumn() + 1).setValue(h);
    });
    result.push({ sheet: name, added: missing, renamedClick: renamed, renamedCategory: renamedCat, status: 'ok' });
  });
  return { ok: true, result: result };
}

// CLEANUP_COLUMNS の列を各記録シートから削除する。(冪等：存在する列だけ・右から削除して索引ズレ回避)
// 列削除時、Googleスプレッドシートは他セルの数式参照を自動補正するため分析数式は壊れない。
function cleanupColumns_() {
  var result = [];
  var ss = openSS_();
  CH_SHEETS.forEach(function (name) {
    var sh = ss.getSheetByName(name);
    if (!sh) { result.push({ sheet: name, status: 'not_found' }); return; }
    var lastCol = sh.getLastColumn();
    if (lastCol < 1) { result.push({ sheet: name, status: 'empty' }); return; }
    var header = sh.getRange(1, 1, 1, lastCol).getValues()[0].map(String);
    var removed = [], idxs = [];
    CLEANUP_COLUMNS.forEach(function (n) { var i = header.indexOf(n); if (i >= 0) { idxs.push(i + 1); removed.push(n); } });
    idxs.sort(function (a, b) { return b - a; });          // 右の列から削除(索引ズレ防止)
    idxs.forEach(function (c) { sh.deleteColumn(c); });
    result.push({ sheet: name, removed: removed, status: removed.length ? 'ok' : 'already_clean' });
  });
  return { ok: true, result: result };
}

// 「YouTube題名」列の値を「題名(コメント)」列へ移し(値があるものは上書き)、YouTube題名列を削除する。
// 題名を1列(題名(コメント))に集約するための一回限りの移行。(冪等：YouTube題名列が無ければ何もしない)
function consolidateTitle_() {
  var result = [];
  var ss = openSS_();
  CH_SHEETS.forEach(function (name) {
    var sh = ss.getSheetByName(name);
    if (!sh) { result.push({ sheet: name, status: 'not_found' }); return; }
    var map = headerMap_(sh);
    var gCol = map['題名(コメント)'], yCol = map['YouTube題名'];
    if (!yCol) { result.push({ sheet: name, moved: 0, removed: false, status: 'no_youtube_title_col' }); return; }
    var last = sh.getLastRow(), moved = 0;
    if (gCol && last >= 2) {
      var yVals = sh.getRange(2, yCol, last - 1, 1).getValues();
      for (var i = 0; i < yVals.length; i++) {
        var v = yVals[i][0];
        if (v !== '' && v !== null) { sh.getRange(i + 2, gCol).setValue(v); moved++; } // 値があれば題名(コメント)へ上書き
      }
    }
    sh.deleteColumn(yCol); // YouTube題名 列を削除
    result.push({ sheet: name, moved: moved, removed: true, status: 'ok' });
  });
  return { ok: true, result: result };
}

// 診断(読み取りのみ)：どのスプレッドシートのどのタブに、何が入っているかを可視化する。
// 「データがどこに書かれているか分からない」「クリック数/題名が空」の原因切り分けに使う。
function diagnose_() {
  var ss = openSS_();
  var allTabs = ss.getSheets().map(function (s) { return s.getName(); });
  var channels = {};
  CH_SHEETS.forEach(function (name) {
    var sh = ss.getSheetByName(name);
    if (!sh) { channels[name] = { exists: false, note: 'このタブは存在しません(GASは書き込み時に自動作成します)' }; return; }
    var map = headerMap_(sh);
    var headers = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0].map(String);
    var last = sh.getLastRow();
    var info = { exists: true, lastRow: last, clickCol: clickColName_(map), headers: headers };
    function countNonEmpty(col) {
      if (!col || last < 2) return 0;
      var vals = sh.getRange(2, col, last - 1, 1).getValues(), n = 0;
      for (var i = 0; i < vals.length; i++) { if (vals[i][0] !== '' && vals[i][0] !== null) n++; }
      return n;
    }
    info.dataRows = countNonEmpty(map['post_id']);
    info.filled = {
      短縮URL: countNonEmpty(map['短縮URL']),
      短縮URLクリック数: countNonEmpty(map[clickColName_(map)]),
      題名コメント: countNonEmpty(map['題名(コメント)']),
      YouTube題名: countNonEmpty(map['YouTube題名']),
      カテゴリ: countNonEmpty(map['カテゴリ']),
      post_uri: countNonEmpty(map['post_uri'])
    };
    channels[name] = info;
  });
  return { ok: true, version: GAS_VERSION, spreadsheet: ss.getName(), allTabs: allTabs, channels: channels };
}

// 「後埋まり列」の実データ着地プローブ(読み取り専用)。型《実物着地》の読取口。
//   ピーク値・クリック数・いいね/リポスト等、改修後N時間経って毎時トリガーが実データで初めて埋める列が
//   「本当に非空になったか」を外から(改善提案部門アスナのZ2運用ツール=b面)突き合わせるための口。
//   各列の非空行数(nonEmpty)と、対の更新日時列から拾った最終更新時刻(latest)を返す。書き込みはしない。
//   ★列名は scripts/backfill_columns.json の登録簿と一致させる(check_backfill_assert.mjs ③がここを照合する)。
function backfillProbe_() {
  var ss = openSS_();
  function grp(sheetName, cols, tsCol) {
    var sh = ss.getSheetByName(sheetName);
    if (!sh) return { exists: false };
    var map = headerMap_(sh), last = sh.getLastRow();
    function nonEmpty(col) {
      if (!col || last < 2) return 0;
      var vals = sh.getRange(2, col, last - 1, 1).getValues(), n = 0;
      for (var i = 0; i < vals.length; i++) { var v = vals[i][0]; if (v !== '' && v !== null) n++; }
      return n;
    }
    function latest(col) {
      if (!col || last < 2) return '';
      var vals = sh.getRange(2, col, last - 1, 1).getValues(), mx = 0;
      for (var i = 0; i < vals.length; i++) {
        var v = vals[i][0]; if (!v) continue;
        var t = (v instanceof Date) ? v.getTime() : Date.parse(String(v));
        if (isFinite(t) && t > mx) mx = t;
      }
      return mx ? new Date(mx).toISOString() : '';
    }
    var out = { exists: true, lastRow: last, latest: tsCol ? latest(map[tsCol]) : '', cols: {} };
    cols.forEach(function (name) {
      // 記録シートのクリック列は旧名(開封数/Bitlyクリック)互換=clickColName_ で解決してから数える。
      var col = (name === '短縮URLクリック数' && sheetName !== '視聴履歴') ? map[clickColName_(map)] : map[name];
      out.cols[name] = nonEmpty(col);
    });
    return out;
  }
  var res = { ok: true, version: GAS_VERSION, at: new Date().toISOString(), sheets: {} };
  // 記録シート(月詠み/宵桜艶帖)= refreshClicks / refreshEngagement が埋める。
  CH_SHEETS.forEach(function (name) {
    res.sheets[name] = grp(name, ['短縮URLクリック数', 'いいね', 'リポスト'], '反応更新日時');
  });
  // ピーク記録 = snapshotStats が埋める。
  res.sheets['ピーク記録'] = grp('ピーク記録', ['再生ピーク(件/時)', 'クリックピーク(件/時)', '作品クリックピーク(件/時)'], '更新日時');
  // 視聴履歴 = snapshotStats が埋める。
  res.sheets['視聴履歴'] = grp('視聴履歴', ['再生数', '短縮URLクリック数', '作品クリック数'], '記録日時');
  // 時点記録 = captureTimepoints_ が埋める。
  res.sheets['時点記録'] = grp('時点記録', ['再生数', 'クリック数', 'ピンククリック'], '記録日時');
  return res;
}

// 視聴履歴.作品クリック数(col8)未着地の枝判定プローブ。(読み取りのみ・書き込み無し)
//   snapshotStats(コード.gs 1616-1640)の write-set = recs を厳密に再現する:
//     recs は「vid必須(!vid→skip)」＋「vidで先頭行だけにdedup(seenVid)」。
//   視聴履歴 col8 は recs.forEach 内の wc=clickByCode[r.wcode] からのみ埋まるので、
//   recs に wcode を持つ行が1つも残っていなければ col8 は構造的に永久に空(=枝B)。
//   残っているのに空なら書き込み経路の取りこぼし(=枝A)。
//   返す決め手:
//     recs_dedup_with_wcode … dedup生存(=実際に書かれる行)のうち wcode を持つ数。0なら枝B寄り。
//     vids_wcode_dropped_by_dedup … 同一vidの他行に wcode があるのに、先頭行(生存側)は wcode 空=dedupが落とした数。>0なら枝A(dedup順の取りこぼし)。
//     wcodes_only_novid … clicks を持ちうる wcode のうち vid有り行に一度も載らない数(枝Bの母数)。
function wcodeVidProbe_() {
  var out = {
    ok: true, version: GAS_VERSION, at: new Date().toISOString(),
    rows_total: 0, rows_with_wcode: 0, wcode_with_vid: 0, wcode_no_vid: 0,
    recs_vid_rows: 0, recs_dedup_rows: 0, recs_dedup_with_wcode: 0,
    vids_wcode_dropped_by_dedup: 0,
    wcodes_total: 0, wcodes_on_vid: 0, wcodes_only_novid: 0,
    samples_dropped: [], samples_only_novid: [], samples_dedup_with_wcode: []
  };
  var ss = openSS_();
  var seenVid = {};   // vid -> {firstWcode, anyWcode}
  var wcodeSeen = {}; // wcode -> {vid:bool, novid:bool}
  var liveRows = []; // {code, wcode} vid有り行のサンプル(実clickを両方叩く)
  CH_SHEETS.forEach(function (name) {
    var sh = ss.getSheetByName(name); if (!sh) return;
    var map = headerMap_(sh); var last = sh.getLastRow(); if (last < 2) return;
    var ytc = map['YouTube動画URL'], wsc = map['作品短縮URL'], sc = map['短縮URL'];
    var vals = sh.getRange(2, 1, last - 1, sh.getLastColumn()).getValues();
    vals.forEach(function (row) {
      out.rows_total++;
      var vid = ytc ? ytIdFromUrl_(row[ytc - 1]) : '';
      var wcode = wsc ? codeFromShort_(row[wsc - 1]) : '';
      if (vid && wcode && liveRows.length < 12) liveRows.push({ code: sc ? codeFromShort_(row[sc - 1]) : '', wcode: wcode });
      if (wcode) {
        out.rows_with_wcode++;
        if (vid) out.wcode_with_vid++; else out.wcode_no_vid++;
        var ws = wcodeSeen[wcode] || (wcodeSeen[wcode] = { vid: false, novid: false });
        if (vid) ws.vid = true; else ws.novid = true;
      }
      if (!vid) return;                       // ← snapshotStats の recs と同じ vid必須ガード
      out.recs_vid_rows++;
      var vi = seenVid[vid];
      if (!vi) {                              // ← 先頭行だけ dedup生存(recs へ入る行)
        seenVid[vid] = { firstWcode: wcode || '', anyWcode: !!wcode };
        out.recs_dedup_rows++;
        if (wcode) { out.recs_dedup_with_wcode++; if (out.samples_dedup_with_wcode.length < 8) out.samples_dedup_with_wcode.push(wcode); }
      } else {
        if (wcode) vi.anyWcode = true;        // 後続行に wcode があった記録(dedupで落ちる側)
      }
    });
  });
  Object.keys(seenVid).forEach(function (v) {
    var vi = seenVid[v];
    if (vi.anyWcode && !vi.firstWcode) { out.vids_wcode_dropped_by_dedup++; if (out.samples_dropped.length < 8) out.samples_dropped.push(v); }
  });
  Object.keys(wcodeSeen).forEach(function (w) {
    out.wcodes_total++;
    if (wcodeSeen[w].vid) out.wcodes_on_vid++;
    else { out.wcodes_only_novid++; if (out.samples_only_novid.length < 8) out.samples_only_novid.push(w); }
  });
  // ★実click着地テスト: snapshotStatsと同じ workerClicks_ を導線1(code)/導線2(wcode)の両方へ叩き、
  //   col7が埋まりcol8が空という非対称が「worker応答の差」か「writer側の差」かを実データで切り分ける。
  out.live = [];
  liveRows.forEach(function (r) {
    var cc = r.code ? workerClicks_(r.code) : null;
    var wcc = r.wcode ? workerClicks_(r.wcode) : null;
    out.live.push({ code: r.code, wcode: r.wcode, code_clicks: cc, wcode_clicks: wcc });
    Utilities.sleep(60);
  });
  return out;
}

// 行分類と件数。(読み取りのみ・削除しない)
// 各チャンネルシートの全行を post_id / post_uri / YouTube動画URL の3列で分類する。
// CANONICAL_HEADERS との差分(実シートに無い列 / 正本に無い余剰列)も同時に返す。
function sheetAudit_() {
  var ss = openSS_();
  var audit = {};
  CH_SHEETS.forEach(function (name) {
    var sh = ss.getSheetByName(name);
    if (!sh) { audit[name] = { exists: false }; return; }
    var map = headerMap_(sh);
    var headers = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0].map(String).filter(function (h) { return h !== ''; });
    var last = sh.getLastRow();
    var counts = { complete: 0, no_yt: 0, no_uri: 0, minimal: 0, empty: 0 };
    var uriSeen = {};  // postUri -> [{rowNum, hasYt}]
    var noYtRows = [];
    var extraColCounts = {};
    if (last >= 2) {
      var pidCol = map['post_id'], uriCol = map['post_uri'], ytCol = map['YouTube動画URL'];
      var titleCol = map['題名(コメント)'], shortCol = map['短縮URL'];
      var bitlyCol = map['Bitly_ID'], bskyUrlCol = map['Bluesky投稿URL'];
      var rows = sh.getRange(2, 1, last - 1, sh.getLastColumn()).getValues();
      rows.forEach(function (row, i) {
        var pid = pidCol ? String(row[pidCol - 1] || '') : '';
        var uri = uriCol ? String(row[uriCol - 1] || '') : '';
        var yt  = ytCol  ? String(row[ytCol  - 1] || '') : '';
        if (!pid) { counts.empty++; return; }
        if (uri && yt) counts.complete++;
        else if (uri && !yt) {
          counts.no_yt++;
          noYtRows.push({
            rowNum: i + 2,
            title: titleCol ? String(row[titleCol - 1] || '') : '',
            postUri: uri,
            shortUrl: shortCol ? String(row[shortCol - 1] || '') : ''
          });
        }
        else if (!uri && yt) counts.no_uri++;
        else counts.minimal++;
        if (uri) { if (!uriSeen[uri]) uriSeen[uri] = []; uriSeen[uri].push({ rowNum: i + 2, hasYt: !!yt }); }
        if (bitlyCol && row[bitlyCol - 1]) extraColCounts['Bitly_ID'] = (extraColCounts['Bitly_ID'] || 0) + 1;
        if (bskyUrlCol && row[bskyUrlCol - 1]) extraColCounts['Bluesky投稿URL'] = (extraColCounts['Bluesky投稿URL'] || 0) + 1;
      });
    }
    var dups = [];
    Object.keys(uriSeen).forEach(function (uri) { if (uriSeen[uri].length > 1) dups.push({ postUri: uri, rows: uriSeen[uri] }); });
    // CANONICALとの差分
    var missingFromCanonical = CANONICAL_HEADERS.filter(function (h) { return !map[h]; });
    var extraColumns = headers.filter(function (h) { return CANONICAL_HEADERS.indexOf(h) < 0; });
    audit[name] = {
      exists: true, totalDataRows: Math.max(0, last - 1),
      counts: counts, duplicateUris: dups.length, dupDetail: dups.slice(0, 10),
      noYtRows: noYtRows, extraColCounts: extraColCounts,
      headers: headers, headerCount: headers.length,
      missingFromCanonical: missingFromCanonical, extraColumns: extraColumns
    };
  });
  return { ok: true, audit: audit, canonicalTotal: CANONICAL_HEADERS.length };
}

// 両記録シートをバックアップ。(コピーのみ・元シートを削除・変更しない)
// コピー先タブ名: <シート名>_bk_<YYYYMMdd_HHmm>。同スプレッドシート内に作成。冪等ではない(毎回新タブ)。
function backupSheets_() {
  var ss = openSS_();
  var ts = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyyMMdd_HHmm');
  var result = [];
  CH_SHEETS.forEach(function (name) {
    var sh = ss.getSheetByName(name);
    if (!sh) { result.push({ sheet: name, status: 'not_found' }); return; }
    var backupName = name + '_bk_' + ts;
    try {
      sh.copyTo(ss).setName(backupName);
      result.push({ sheet: name, backup: backupName, rows: Math.max(0, sh.getLastRow() - 1), status: 'ok' });
    } catch (err) {
      result.push({ sheet: name, status: 'error', error: String(err) });
    }
  });
  return { ok: true, result: result, timestamp: ts };
}

function doPost(e) {
  // T11: 書き込みは全て直列化。(同一videoIdの近接2リクエストが両方upsertをすり抜けて重複行を作る事故を根絶)
  var lock = LockService.getScriptLock();
  try { lock.waitLock(20000); } catch (le) { return jsonOut_({ ok: false, error: 'busy(同時書き込み中。数秒後に再試行してください)' }); }
  try {
    var body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    var need = prop_('SHARED_SECRET');
    if (need && body.secret !== need) return jsonOut_({ ok: false, error: 'bad_secret' });
    if (body.type === 'reserve') return handleReserve_(body);
    // 投稿履歴の一括同期。(フロントの投稿履歴を正とし、ID・投稿日時・キャラ等をまとめて upsert)
    if (body.op === 'sync_history') return syncHistory_(body.channel || 'acc1', body.items || []);
    // 投稿履歴の掃除。(keepIds に無い post_id の行をクリア＝アプリの履歴を正にシートを揃える)
    if (body.op === 'prune_history') return pruneHistory_(body.channel || 'acc1', body.keepIds || []);
    // 行のアカウント間移動(誤記録の矯正)：videoId/post_uri/短縮URL で元行を特定し正チャンネルへ移す。
    if (body.op === 'move_row') return jsonOut_(moveRow_(body.from || '', body.to || '', body.videoId || '', body.postUri || '', body.short || ''));
    // 端末間 設定同期：非秘密設定の保存。(クラウドへ push)
    if (body.op === 'settings_push') return settingsPush_(body.blob || '', body.updatedAt || '', body.device || '');
    // 競合の代表フレーム結果を書き戻す(PC側スクレイパから。焼き込み文字/コマ要約を既存行へ追記のみ)
    if (body.op === 'comp_frame_write') return jsonOut_(compFrameWriteback_(body.items || []));
    // テストモード：シートには一切書かない。(Bluesky実投稿はフロント側で実施)
    if (body.testMode === true || body.testMode === 'true') return jsonOut_({ ok: true, testMode: true });
    // ウィザード経路はyoutube_url必須。他経路(無人予約/リビルド/矯正等)は素通り。(★writeRecord_中に置くな=裁定C)
    if (body.op === 'wizard_confirm' && !body.youtube_url) return jsonOut_({ ok: false, error: 'youtube_url_required' });
    var r = writeRecord_(body.channel || 'acc1', {
      videoId: body.videoId || '',   // 背骨ID。あれば post_id に採用＋同ID行へ upsert(重複行を作らない)
      postedAt: body.postedAt || '', // 過去データ矯正時に当時の投稿日時を保持(無ければGASがnow)
      title: body.title || '', postUrl: body.postUrl || '', affiliateUrl: body.affiliateUrl || '',
      workUrl: body.workUrl || '', hashtags: body.hashtags || '', postUri: body.postUri || '',
      rebuildOf: body.rebuildOf || '',     // リビルド元の投稿videoId(送っているのに未記録だった取りこぼしを回収・D-1)
      goal: body.goal || '', cmtType: body.cmtType || '', // 狙い(成約/集客)・コメント型(①〜⑧)＝勝ちパターン集計用
      shortUrl: body.shortUrl || '',       // r2計測用短縮URL(短縮URL列)
      shareUrl: body.shareUrl || '',       // 共有URL(独自短縮、無ければwriteRecord_がpostUrlを使用)
      youtubeUrl: body.youtube_url || '',  // ウィザードのYouTube手動ゲートから(同IDの行へ後追いupsert)
      workShortUrl: body.work_short_url || '', // 導線2(作品クリック)の計測URL
      workShortClear: body.work_short_clear === true || body.work_short_clear === 'true', // ★意図的クリア=空でも確定(putIfの空スキップを越えてセルを消す)
      chara: body.chara, jk: body.jk, gyaru: body.gyaru, isekai: body.isekai, harem: body.harem, ai: body.ai, ol: body.ol, soshu: body.soshu, // カテゴリ属性(複数可)
      workState: body.workState,           // 作品状態(新作/準新作/旧作)
      rebuild: body.rebuild,               // この動画自体が作り直し版(動画作成タブのリビルド)
      remade: body.remade,                 // この動画は作り直されて置き換え済み(投稿履歴の作り直し印)
      fanza_list_price: body.fanza_list_price, fanza_price: body.fanza_price,
      fanza_discount_pct: body.fanza_discount_pct, fanza_fetched_at: body.fanza_fetched_at || '',
      fanza_review_count: body.fanza_review_count, fanza_review_avg: body.fanza_review_avg
    });
    return jsonOut_({ ok: true, shortUrl: r.shortUrl, row: r.row });
  } catch (err) {
    return jsonOut_({ ok: false, error: String(err) });
  } finally {
    try { lock.releaseLock(); } catch (e) {}
  }
}

// cid 抽出。(作品URL の cid= か、アフィリンクの lurl をデコードして cid=)
//   ・FANZA Books(book.dmm.(com|co.jp)/product/…)は cid= を持たずパスにIDがあるため、
//     フロント(affiliate-core.js buildAffiliateLink)と同じ規則で内部cidを取り出す。
//     これをしないと Books 作品の「作品cid」列が空になり、復元時に作品URL/投稿済み判定が戻らない。
function extractCid_(url) {
  if (!url) return '';
  var s = String(url);
  // アフィリンク(al.fanza.co.jp/?lurl=…)なら中身のURLをデコードして同じ規則で解析。
  var lm = s.match(/[?&]lurl=([^&]+)/);
  if (lm) { try { var dec = decodeURIComponent(lm[1]); if (dec) { var inner = extractCid_(dec); if (inner) return inner; } } catch (e) {} }
  // FANZA Books：/product/【数字ID】/【content_id】/。2階層目があれば .com/.co.jp を問わず優先
  //   。(数字IDはDMM APIのcontent_id照会に使えないため。フロント affiliate-core.js と同一規則)
  var booksM = s.match(/book\.dmm\.(com|co\.jp)\/product\/([^/?&#\s]+)(?:\/([^/?&#\s]+))?/);
  if (booksM) return booksM[3] || booksM[2];
  // 同人・動画：cid= パラメータ。
  var m = s.match(/cid=([^/?&\s]+)/);
  if (m) return m[1];
  return '';
}
function extractHashtags_(t) { var m = String(t || '').match(/#[^\s#]+/g); return m ? m.join(' ') : ''; }

// 1始まり列番号 → Excel列文字。(A/B/.../Z/AA/AB/...)動的に列参照を組み立てるために使う。
function columnLetter_(n) {
  if (!n || n < 1) return '';
  var s = '';
  while (n > 0) { n--; s = String.fromCharCode(65 + n % 26) + s; n = Math.floor(n / 26); }
  return s;
}

// 計算列の数式。(行番号 r に合わせる)列文字は headerMap_ から動的に取得するため列の増減に強い。
function setComputed_(sh, map, r) {
  function set(h, f) { if (map[h]) sh.getRange(r, map[h]).setFormula(f); }
  set('曜日', '=IF($B' + r + '="","",CHOOSE(WEEKDAY($B' + r + '),"日","月","火","水","木","金","土"))');
  set('day-type', '=IF($B' + r + '="","",IF(OR(WEEKDAY($B' + r + ',2)>=6,COUNTIF(Holidays,INT($B' + r + '))>0),"土日祝",IF(OR(WEEKDAY($B' + r + '+1,2)>=6,COUNTIF(Holidays,INT($B' + r + ')+1)>0),"休前日","平日")))');
  set('時間帯スロット', '=IF($B' + r + '="","",IF(HOUR($B' + r + ')<5,"深夜",IF(HOUR($B' + r + ')<11,"朝",IF(HOUR($B' + r + ')<15,"昼",IF(HOUR($B' + r + ')<19,"夕","夜")))))');
  var cTitle = map['題名(コメント)'] ? columnLetter_(map['題名(コメント)']) : ''; // タイトル文字数(伸びる題名の傾向分析用・D-1)
  if (cTitle) set('タイトル文字数', '=IF(' + cTitle + r + '="","",LEN(' + cTitle + r + '))');
  var cClick  = columnLetter_(map[clickColName_(map)]); // 短縮URLクリック数(旧称：開封数/Bitlyクリック)
  var cViews  = columnLetter_(map['視聴回数']);
  // ★FANZA成約・報酬由来の数式(承認率/CVR/EPC/RPM)は撤去(2026-07-23)。
  //   分子となる手入力4列が一度も埋まらず(実測0件)、結果は常に0＝分析を汚すだけだった。
  //   FANZAは投稿単位の成約を返さないため、今後も埋まる見込みが無い。
  //   残すのは「両辺とも実データがある」リンククリック率%だけ。
  if (cClick && cViews) set('リンククリック率%','=IFERROR(' + cClick + r + '/' + cViews + r + ',"")');
}

// 純粋関数：post_id 列の値配列(2行目以降)と videoId から upsert 先の行番号(2始まり)を返す。
// 一致が無ければ 0。videoId 空なら 0。(=従来の空行再利用/追記へ)
// ※ tests/test_record_upsert.js に同一ロジックのミラーあり。(変更時は両方を揃える)
function upsertRowOf_(postIdCol, videoId) {
  if (!videoId) return 0;
  for (var j = 0; j < postIdCol.length; j++) { if (String(postIdCol[j]) === String(videoId)) return j + 2; }
  return 0;
}

// 1投稿を記録。(短縮失敗でも記録は残す)doPost・無人予約の両方から使用。
// videoId(背骨ID)があれば post_id をそれにし、同ID行へ upsert。(重複行を作らない・変更フィールドのみ更新)
// videoId 無し＝完全に従来動作。(後方互換)
function writeRecord_(channel, f) {
  // T10: 背骨ID(videoId)接頭辞が channel と矛盾するなら、正しいチャンネルへリダイレクト。(拒否でなく＝データ喪失なし)
  //   クライアント側にバグ/旧キャッシュがあっても、宵桜タブに acc1-… の誤行を作らせない最終防壁。
  //   move_row は writeRecord_ を通らないため影響なし。test- 接頭辞も考慮。
  var _pm = String(f.videoId || '').match(/^(?:test-)?(acc[12])-/);
  if (_pm && _pm[1] !== channel) channel = _pm[1];
  // 短縮URLはフロントの独自link-workerが生成した計測キーだけを採る。
  // 生成できない時は外部短縮へ逃がさず、共有URL列に生の投稿URLを残す(リンクは生存・計測不能を隠さない)。
  var shortUrl = f.shortUrl || '';
  var shareUrl = f.shareUrl || f.postUrl || '';
  var sh = getChannelSheet_(channel);
  var map = headerMap_(sh);
  var dcol = map['投稿日時'] || 2;
  var pidc = map['post_id'] || 1;
  var last = sh.getLastRow();
  var now = new Date();
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';

  // 行キー：videoId があればそれ、無ければ従来の時刻ベース。
  var pid = f.videoId || (channel + '-' + Utilities.formatDate(now, tz, 'yyyyMMdd-HHmm'));

  // upsert：同一 videoId の既存行を探す。
  var target = 0;
  if (f.videoId && last >= 2) {
    target = upsertRowOf_(sh.getRange(2, pidc, last - 1, 1).getValues().map(function (r) { return r[0]; }), f.videoId);
  }
  var isNewRow = false;
  if (!target) {
    // 従来通り：空の投稿日時行を再利用、無ければ末尾に追加。
    if (last >= 2) {
      var vals = sh.getRange(2, dcol, last - 1, 1).getValues();
      for (var i = 0; i < vals.length; i++) { if (vals[i][0] === '' || vals[i][0] === null) { target = i + 2; break; } }
    }
    if (!target) { target = last + 1; }
    isNewRow = true;
  }

  setComputed_(sh, map, target); // テンプレ既存行は同じ式で上書き＝無害。新規行にも式を付与。
  function put(h, v) { if (map[h]) sh.getRange(target, map[h]).setValue(v); }
  // upsert更新時に既存値を空で潰さないよう、値があるものだけ書く。
  function putIf(h, v) { if (map[h] && v !== '' && v !== null && v !== undefined) sh.getRange(target, map[h]).setValue(v); }

  put('post_id', pid);
  // 投稿日時：履歴の実投稿時刻(postedAt)があれば最優先。無ければ新規行/投稿URL記録時のみ now。
  // (YouTube URLだけの後追いupsertでは上書きしない＝既存の投稿日時を保護)
  var postedDate = null;
  if (f.postedAt) { var pd = new Date(f.postedAt); if (!isNaN(pd.getTime())) postedDate = pd; }
  if (postedDate) put('投稿日時', postedDate);
  else if (isNewRow || f.postUrl) put('投稿日時', now);
  putIf('題名(コメント)', f.ytTitle || f.title || '');         // YouTube題名を優先して題名(コメント)へ集約
  putIf('作品cid', extractCid_(f.workUrl || f.affiliateUrl || ''));
  putIf('ジャンル', fanzaGenre_(f.workUrl || f.affiliateUrl || ''));  // F列＝同人/Books/データ を作品URLから自動記載(Chami③ 2026-07-31)
  putIf('作品URL', f.workUrl || '');                             // 作品URLそのものを保存＝cidから復元できない階層(FANZA動画等)でもシート由来行に作品↗が戻る(Chami「リロードで作品URLが消える」2026-07-28)
  putIf('投稿先', (f.platform === 'x' || f.platform === 'bsky') ? f.platform : ''); // 投稿先(X/Bsky)＝短縮URLだけの行のX↗/Bsky↗表示をリロード後も保持(Chami「原則X投稿」2026-07-29)
  putIf('短縮URL', shortUrl);                                   // r2＝計測用(codeFromShort_対象・r2以外は入れない)
  if (f.workShortClear) put('作品短縮URL', '');                  // ★ユーザーが意図的に消した=空で確定(導線2導入前の履歴に誤挿入された短縮URLを除去・Chami 2026-07-29)
  else putIf('作品短縮URL', f.workShortUrl || '');               // 導線2(作品クリック)の計測URL=作品クリック数の日次スナップ元
  putIf('共有URL', shareUrl);                                // 独自短縮URL、無ければ生の投稿URL
  putIf('YouTube動画URL', f.youtubeUrl || '');
  putIf('視聴回数', (f.views !== undefined && f.views !== null && f.views !== '') ? f.views : '');   // YouTube再生数
  putIf(clickColName_(map), (f.clicks !== undefined && f.clicks !== null && f.clicks !== '') ? f.clicks : ''); // 短縮URLクリック数
  putIf('post_uri', f.postUri || '');
  putIf('ハッシュタグ', f.hashtags || '');       // 受信していたのに書いていなかった取りこぼしを回収(D-1)
  putIf('リビルド元ID', f.rebuildOf || '');       // リビルド前後の再生数比較をシートで可能に(D-1)
  putIf('目的', f.goal || '');                    // 狙い(成約/集客)＝維持率とクリック数の二系統検証用
  putIf('コメント型', f.cmtType || '');           // コメント型(①〜⑧)＝勝ちパターン集計用
  // FANZA 価格スナップショット。(投稿時1回のみ。null は書かない＝既存値を保護)
  putIf('元値list_price', f.fanza_list_price !== undefined && f.fanza_list_price !== null ? f.fanza_list_price : '');
  putIf('割引後price', f.fanza_price !== undefined && f.fanza_price !== null ? f.fanza_price : '');
  putIf('割引率pct', f.fanza_discount_pct !== undefined && f.fanza_discount_pct !== null ? f.fanza_discount_pct : '');
  putIf('FANZA取得日時', f.fanza_fetched_at || '');
  putIf('レビュー件数(代理指標)', f.fanza_review_count !== undefined && f.fanza_review_count !== null ? f.fanza_review_count : '');
  putIf('レビュー平均', f.fanza_review_avg !== undefined && f.fanza_review_avg !== null ? f.fanza_review_avg : '');
  // カテゴリ：FANZA種別(books/同人/データ)を作品URLから自動判定 + 属性フラグ(chara/jk等)を結合。
  // workUrlもaffiliatUrlも無く属性フラグも無ければ既存値を保護。
  if (map['カテゴリ']) {
    var _catParts = [];
    var _ftype = fanzaType_(f.workUrl || f.affiliateUrl || '');
    if (_ftype) _catParts.push(_ftype);
    if (attrProvided_(f)) { var _attrCat = categoryOf_(f); if (_attrCat) _catParts.push(_attrCat); }
    var _catVal = _catParts.join(', ');
    if (_catVal) sh.getRange(target, map['カテゴリ']).setValue(_catVal);
  }
  // 作品状態：投稿当時の状態。(新作/準新作/旧作)payload に含まれるときだけセット。
  putIf('作品状態', f.workState || '');
  // 作り直し列：明示指定があるときだけセット/解除。(未指定=既存値を保護)
  //   remade=true → 作り直し済(この動画を消して作り直した)／remade=false → 解除
  //   rebuild=true → リビルド版(この動画自体が作り直し版)
  if (map['作り直し']) {
    if (f.remade === true || f.remade === 'true') put('作り直し', '作り直し済');
    else if (f.remade === false || f.remade === 'false') put('作り直し', '');
    else if (f.rebuild === true || f.rebuild === 'true') put('作り直し', 'リビルド版');
  }
  // カウンタは新規行のみ0初期化。(upsert更新で既存のいいね数等を0で潰さない)
  if (isNewRow) { put('いいね', 0); put('リポスト', 0); }
  // 投稿履歴を正とし、投稿日時の新しい順にシートを並べ替える。(空日時は末尾へ)
  // 一括同期(sync_history)では noSort で抑止し、最後に1回だけ並べ替える。
  if (!f.noSort) sortByDate_(sh, dcol);
  return { shortUrl: shortUrl, row: target };
}

// 投稿履歴の一括同期：各アイテムを post_id(背骨ID)キーで upsert し、最後に1回だけ日付降順ソート。
// 投稿履歴を「正」とするため ID・投稿日時(postedAt)・キャラ属性も反映する。(冪等：再実行しても重複しない)
function syncHistory_(channel, items) {
  if (!items || !items.length) return jsonOut_({ ok: true, synced: 0 });
  var n = 0;
  for (var i = 0; i < items.length; i++) {
    var it = items[i] || {};
    if (!it.videoId) continue;
    try {
      writeRecord_(channel, {
        videoId: it.videoId, title: it.title || '', postUrl: it.postUrl || '',
        workUrl: it.workUrl || '', postUri: it.postUri || '', shortUrl: it.shortUrl || '', shareUrl: it.shareUrl || '',
        youtubeUrl: it.youtubeUrl || '', ytTitle: it.ytTitle || '', workShortUrl: it.workShortUrl || '',
        views: it.views, clicks: it.clicks,
        chara: it.chara, jk: it.jk, gyaru: it.gyaru, isekai: it.isekai, harem: it.harem, ai: it.ai, ol: it.ol, soshu: it.soshu, // カテゴリ属性(複数可)
        workState: it.workState,           // 作品状態(新作/準新作/旧作)
        rebuild: it.rebuild, remade: it.remade, // 作り直し(リビルド版/作り直し済)
        goal: it.goal, cmtType: it.cmtType, // 狙い・コメント型(履歴にあれば同期)
        postedAt: it.postedAt || '',
        noShorten: true, noSort: true   // 同期は短縮API呼ばず・並べ替えは最後にまとめて
      });
      n++;
    } catch (e) {}
  }
  var sh = getChannelSheet_(channel), map = headerMap_(sh);
  sortByDate_(sh, map['投稿日時'] || 2);
  return jsonOut_({ ok: true, synced: n });
}

// 投稿履歴の掃除：keepIds(アプリの全post_id)に含まれない行をクリアする。(行は詰めず内容クリア＝再利用可)
// アプリの投稿履歴を「正」とし、履歴から消した投稿をシートからも消す用途。指定チャンネルのタブのみ対象。
function pruneHistory_(channel, keepIds) {
  var sh = getChannelSheet_(channel), map = headerMap_(sh);
  var pidc = map['post_id']; var last = sh.getLastRow();
  if (!pidc || last < 2) return jsonOut_({ ok: true, cleared: 0 });
  var keep = {};
  for (var i = 0; i < keepIds.length; i++) { if (keepIds[i]) keep[String(keepIds[i])] = true; }
  var pids = sh.getRange(2, pidc, last - 1, 1).getValues();
  var cleared = 0;
  for (var r = 0; r < pids.length; r++) {
    var pid = String(pids[r][0] || '');
    if (!pid) continue;                  // 既に空の行はスキップ
    if (!keep[pid]) { sh.getRange(r + 2, 1, 1, sh.getLastColumn()).clearContent(); cleared++; }
  }
  sortByDate_(sh, map['投稿日時'] || 2); // 空行は末尾へ
  return jsonOut_({ ok: true, cleared: cleared });
}

// ============================================================
// 端末間 設定同期(鍵＝秘密以外の設定・投稿履歴を端末間で共有)
//   クライアントは非秘密の localStorage を JSON 化(blob)して push、別端末で pull→上書き→再読込。
//   秘密(app_pw/secret/api_key)はクライアント側で除外済み＝クラウドには保存しない。
//   保存先：非表示シート '_sync'。A1=メタJSON、A2以降=blobチャンク。(1セル約5万字上限を回避)
// ============================================================
function syncSheet_() {
  var ss = openSS_();
  var sh = ss.getSheetByName('_sync');
  if (!sh) { sh = ss.insertSheet('_sync'); try { sh.hideSheet(); } catch (e) {} }
  return sh;
}
// 非秘密設定 blob を保存。(POST)既存内容は毎回全消去してから書き直す。(＝最新スナップショットのみ保持)
function settingsPush_(blob, updatedAt, device) {
  var sh = syncSheet_();
  sh.clearContents();
  blob = String(blob || '');
  var CH = 45000, chunks = [];
  for (var i = 0; i < blob.length; i += CH) chunks.push([blob.slice(i, i + CH)]);
  var meta = { updatedAt: updatedAt || new Date().toISOString(), device: String(device || ''), chunks: chunks.length, len: blob.length };
  sh.getRange(1, 1).setValue(JSON.stringify(meta));
  if (chunks.length) sh.getRange(2, 1, chunks.length, 1).setValues(chunks);
  return jsonOut_({ ok: true, len: blob.length, chunks: chunks.length, updatedAt: meta.updatedAt });
}
// メタのみ返す。(軽量・状態表示用。JSONP GET)
function settingsMeta_() {
  var sh = syncSheet_();
  var v = sh.getRange(1, 1).getValue();
  if (!v) return { ok: true, empty: true };
  var meta = {}; try { meta = JSON.parse(v); } catch (e) { return { ok: true, empty: true }; }
  return { ok: true, empty: false, updatedAt: meta.updatedAt || '', device: meta.device || '', len: meta.len || 0 };
}
// blob 全体を返す。(JSONP GET)チャンクを結合して復元。
function settingsPull_() {
  var sh = syncSheet_();
  var last = sh.getLastRow();
  if (last < 2) return { ok: true, empty: true };
  var meta = {}; try { meta = JSON.parse(sh.getRange(1, 1).getValue() || '{}'); } catch (e) {}
  var vals = sh.getRange(2, 1, last - 1, 1).getValues();
  var blob = ''; for (var i = 0; i < vals.length; i++) blob += (vals[i][0] || '');
  return { ok: true, empty: false, blob: blob, updatedAt: meta.updatedAt || '', device: meta.device || '', len: blob.length };
}

// 記録シートを「投稿日時」降順で並べ替える。(ヘッダ行は固定、2行目以降が対象)
// 計算列の数式は行相対参照($B<row>)のため、並べ替えでも各行が自分の日時を正しく参照する。
function sortByDate_(sh, dcol) {
  var last = sh.getLastRow();
  if (last < 3) return; // データ行が0〜1件なら並べ替え不要
  sh.getRange(2, 1, last - 1, sh.getLastColumn()).sort({ column: dcol, ascending: false });
}

// ---- link-worker 開封数の取り込み(①計測の見える化) ----
//   YT説明欄に貼る短縮URL(go5-short/<code>)の「開かれた回数」を /api/stats から取得し、
//   テンプレ列「Bitlyクリック」(＝今後は link-worker の開封数の意味)に毎時反映する。
//   ※列名はテンプレ互換のため変えない。(意味だけ Bitly→開封数 に変更)
var SHORT_WORKER_URL = 'https://r2.trustsignalbot.workers.dev';
// ★このリストは「自前の計測リンクか」を判定する唯一の材料。**フロント(bluesky.js SHORT.WORKER_HOSTS)と
//   必ず揃えること**。片方だけ新ドメインを足すと、GASがコードを抽出できず視聴履歴シートの
//   クリック列が空のまま→画面は「取得⚠️」になる(2026-07-20 INC-112の実際の事故)。
//   ・5mgl.com(月詠み/acc1) と yoz2.com(宵桜艶帖/acc2) は2026-07-20に切替。同一worker・同一KV。
//   ・旧ホスト(r2/go5-short)は発行済みリンクの計測継続のため残す。
var SHORT_WORKER_HOSTS = [
  'https://5mgl.com',                                 // acc1(月詠み)・現行
  'https://yoz2.com',                                 // acc2(宵桜艶帖)・現行
  'https://r2.trustsignalbot.workers.dev',            // 旧(現在も生存)
  'https://go5-short.trustsignalbot.workers.dev'      // 最旧
];
function shortSecret_() { return prop_('SHORT_SHARED_SECRET') || 'daremogamewoubawareteikukimihakanpekidekyukyokunoidol'; }
// 自前ワーカーのURLから末尾コードを抽出。(da.gd等の別ホストは '')
function codeFromShort_(url) {
  var s = String(url || '');
  var bare = s.replace(/^https?:\/\//, '');   // ★scheme無し("5mgl.com/YD5dl")も許容(画面表示形をそのまま貼った投稿対策)
  for (var i = 0; i < SHORT_WORKER_HOSTS.length; i++) {
    var base = SHORT_WORKER_HOSTS[i].replace(/\/+$/, '').replace(/^https?:\/\//, '');
    if (bare.indexOf(base + '/') === 0) {
      var rest = bare.slice(base.length + 1).split(/[/?#]/)[0];
      if (/^[0-9A-Za-z]+$/.test(rest)) return rest;
    }
  }
  // ★未知ホストを無言で捨てない。ドメイン切替の取りこぼし(＝クリックが永久に空欄)は
  //   静かに起きると誰も気づけない。自前ドメイン風のURLだけログに出す(da.gd等の想定内は除く)。
  if (s && !/^https?:\/\/(da\.gd|tinyurl\.com)\//.test(s)) {
    try { Logger.log('codeFromShort_: 未知の短縮ホスト=' + s + ' (SHORT_WORKER_HOSTSに追加が必要かもしれません)'); } catch (e) {}
  }
  return '';
}
function workerClicks_(code) {
  if (!code) return null;
  try {
    var u = SHORT_WORKER_URL.replace(/\/+$/, '') + '/api/stats?code=' + encodeURIComponent(code) + '&secret=' + encodeURIComponent(shortSecret_());
    var res = UrlFetchApp.fetch(u, { muteHttpExceptions: true });
    if (res.getResponseCode() >= 300) return null;
    var d = JSON.parse(res.getContentText() || '{}');
    return (d && d.ok && typeof d.clicks === 'number') ? d.clicks : null;
  } catch (e) { return null; }
}
// 毎時：直近200行のうち短縮URLが go5-short のものだけ開封数を更新。(軽量・クォータ安全)
function refreshClicks() {
  CH_SHEETS.forEach(function (name) {
    var ss = openSS_(); var sh = ss.getSheetByName(name); if (!sh) return;
    var map = headerMap_(sh); var last = sh.getLastRow();
    var clickCol = map[clickColName_(map)]; // 短縮URLクリック数(旧名 開封数/Bitlyクリック も互換)
    if (last < 2 || !map['短縮URL'] || !clickCol) return;
    var start = Math.max(2, last - 199), n = last - start + 1;
    var urls = sh.getRange(start, map['短縮URL'], n, 1).getValues();
    for (var i = 0; i < urls.length; i++) {
      var code = codeFromShort_(urls[i][0]); if (!code) continue;
      var c = workerClicks_(code);
      if (c !== null) {
        sh.getRange(start + i, clickCol).setValue(c);
        if (map['クリック更新日時']) sh.getRange(start + i, map['クリック更新日時']).setValue(new Date());
      }
      Utilities.sleep(100);
    }
  });
  try { rebuildClickAggSheet_(); } catch (e) {} // クリック更新のたびに作品別合算シートを積み直す(手番ゼロ)
}

// ── 作品別クリック合算(分析部門依頼2026-07-31・X凍結→Bluesky退避対策)────────────
// X→Bluesky退避で、同じ作品でも投稿ごとに導線1短縮URL(YouTube→投稿)が変わり、クリックが
// 複数行に割れる。作品cid(=作品URLの正規化キー・投稿や媒体が変わっても不変)でまとめ直し、
// 1作品=1行の合計クリックにする。合算キーは作品URL/cid(短縮リンクは投稿・媒体ごとに変わり
// タイトルも凍結対策で変わるためキーに使えない/作品URLは記録POST payloadに入り不変)。
// 導線1(短縮URLクリック数)を合算＝記録シートに行ごとに在る値なので「行を足すだけ」で足りる
// (STATS/videoId層に依存しない＝YouTube動画を伴わないBluesky単独投稿でも拾える)。
function clicksByWork_(channel) {
  var pick = (channel === 'acc1' || channel === '月詠み') ? ['月詠み']
           : (channel === 'acc2' || channel === '宵桜艶帖') ? ['宵桜艶帖'] : CH_SHEETS.slice();
  var agg = {};
  pick.forEach(function (name) {
    var ss = openSS_(); var sh = ss.getSheetByName(name); if (!sh) return;
    var map = headerMap_(sh); var last = sh.getLastRow(); if (last < 2) return;
    var clickCol = map[clickColName_(map)];
    var wuCol = map['作品URL'], cidCol = map['作品cid'], tCol = map['題名(コメント)'], sCol = map['短縮URL'];
    var ch = (name === '宵桜艶帖') ? 'acc2' : 'acc1';
    var rows = sh.getRange(2, 1, last - 1, sh.getLastColumn()).getValues();
    rows.forEach(function (row) {
      var wu  = wuCol  ? String(row[wuCol - 1]  || '') : '';
      var cid = cidCol ? String(row[cidCol - 1] || '') : '';
      if (!cid && wu) cid = extractCid_(wu);
      var key = cid || wu; if (!key) return;                 // 作品を特定できない行(cid/作品URLとも空)は除外
      var clk = clickCol ? Number(row[clickCol - 1]) : 0; if (!isFinite(clk)) clk = 0;
      var short = sCol ? String(row[sCol - 1] || '') : '';
      var title = tCol ? String(row[tCol - 1] || '') : '';
      var gk = ch + '\t' + key;                              // 集計はチャンネル別(記録が物理分離のため)
      var a = agg[gk] || (agg[gk] = { channel: ch, key: key, workUrl: wu, title: '', clicks: 0, links: 0, posts: 0 });
      a.clicks += clk; a.posts += 1; if (short) a.links += 1;
      if (title) a.title = title;                            // 下の行ほど新しい=最新タイトルを採用
      if (wu && !a.workUrl) a.workUrl = wu;
    });
  });
  return Object.keys(agg).map(function (k) { return agg[k]; })
    .sort(function (a, b) { return (b.clicks - a.clicks) || (a.channel < b.channel ? -1 : 1); });
}
// 合算結果を専用タブ「作品別クリック合算」へ書き出す(非破壊=新規タブ・既存集計に相乗りしない)。
function rebuildClickAggSheet_() {
  var ss = openSS_(); var name = '作品別クリック合算';
  var sh = ss.getSheetByName(name) || ss.insertSheet(name);
  sh.clearContents();
  var header = ['チャンネル', '作品タイトル', '作品cid/キー', '作品URL', '合計クリック(導線1)', '短縮リンク数', '投稿数', '更新'];
  var now = Utilities.formatDate(new Date(), Session.getScriptTimeZone() || 'Asia/Tokyo', 'yyyy-MM-dd HH:mm');
  var list = clicksByWork_('both'), rows = [header];
  list.forEach(function (r) {
    rows.push([r.channel === 'acc2' ? '宵桜艶帖' : '月詠み', r.title, r.key, r.workUrl, r.clicks, r.links, r.posts, now]);
  });
  sh.getRange(1, 1, rows.length, header.length).setValues(rows);
  return list.length;
}

// ---- Bluesky反応(いいね/リポスト/返信)の定期更新。(毎時トリガー)公開API getPosts を25件ずつ ----
function refreshEngagement() {
  CH_SHEETS.forEach(function (name) {
    var ss = openSS_(); var sh = ss.getSheetByName(name); if (!sh) return;
    var map = headerMap_(sh); var last = sh.getLastRow();
    if (last < 2 || !map['post_uri']) return;
    var uris = sh.getRange(2, map['post_uri'], last - 1, 1).getValues();
    var pending = [];
    for (var i = 0; i < uris.length; i++) { var u = uris[i][0]; if (u) pending.push({ row: i + 2, uri: String(u) }); }
    for (var b = 0; b < pending.length; b += 25) {
      var slice = pending.slice(b, b + 25);
      var q = slice.map(function (x) { return 'uris=' + encodeURIComponent(x.uri); }).join('&');
      try {
        var res = UrlFetchApp.fetch('https://public.api.bsky.app/xrpc/app.bsky.feed.getPosts?' + q, { muteHttpExceptions: true });
        if (res.getResponseCode() >= 300) continue;
        var data = JSON.parse(res.getContentText() || '{}'); var byUri = {};
        (data.posts || []).forEach(function (p) { byUri[p.uri] = p; });
        slice.forEach(function (x) {
          var p = byUri[x.uri]; if (!p) return;
          if (map['いいね']) sh.getRange(x.row, map['いいね']).setValue(p.likeCount || 0);
          if (map['リポスト']) sh.getRange(x.row, map['リポスト']).setValue(p.repostCount || 0);
          if (map['反応更新日時']) sh.getRange(x.row, map['反応更新日時']).setValue(new Date());
        });
      } catch (e) {}
      Utilities.sleep(200);
    }
  });
}

// ============================================================
// 再生数・クリック数の自動スナップショット(毎時トリガー)＝アプリ未起動でも記録される。
//   視聴履歴シートに (日付, videoId) 単位で「その日の最新の累計」を upsert。
//   これを差分計算(computeDeltas_)して 今日/昨日/直近1週間 の増加を出す。
//   ※再生数取得には Script Property `YT_API_KEY`(アプリ⚙のYouTube APIキーと同値)が必要。
// ============================================================
var STATS_SHEET = '視聴履歴';
var STATS_HEADERS = ['記録日時', '日付', 'channel', 'post_id', 'videoId', '再生数', '短縮URLクリック数', '作品クリック数'];
function statsSheet_() {
  var ss = openSS_();
  var sh = ss.getSheetByName(STATS_SHEET) || ss.insertSheet(STATS_SHEET);
  if (sh.getLastRow() === 0) sh.appendRow(STATS_HEADERS);
  return sh;
}
// 最大瞬間風速(一番伸びた区間の伸び率と時間帯)を作品ごとに永続保存するシート。
var PEAK_SHEET = 'ピーク記録';
// ★作品クリックピーク(導線2=ピンク矢印 w)を末尾に追加(2026-08-11 Chami「全部のピークが要る」)。
//   末尾へ足すのは既存列(v/c/更新日時)の位置を動かさないため=timepointSheet_と同じ冪等移行が使える。
//   途中挿入だと既存シートの更新日時列がヘッダだけズレて中身と食い違う(データ行は触らないため)。
var PEAK_HEADERS = ['videoId', '再生ピーク(件/時)', '再生ピーク時間帯', 'クリックピーク(件/時)', 'クリックピーク時間帯', '更新日時', '作品クリックピーク(件/時)', '作品クリックピーク時間帯'];
function peakSheet_() {
  var ss = openSS_();
  var sh = ss.getSheetByName(PEAK_SHEET) || ss.insertSheet(PEAK_SHEET);
  if (sh.getLastRow() === 0) { sh.appendRow(PEAK_HEADERS); }
  else {
    // 冪等移行: 既存シートに新列(作品クリックピーク 等)が無ければヘッダ行へ補う。データ行は触らない
    //   =旧行の作品ピーク列は空欄のまま(computeが null 扱い)。末尾追加なので列ズレを起こさない(2026-08-11)。
    var hdr = sh.getRange(1, 1, 1, PEAK_HEADERS.length).getValues()[0];
    for (var i = 0; i < PEAK_HEADERS.length; i++) {
      if (String(hdr[i] || '') !== PEAK_HEADERS[i]) sh.getRange(1, i + 1).setValue(PEAK_HEADERS[i]);
    }
  }
  return sh;
}
// ピーク記録シート → videoIdごとの {vRate,vWin,cRate,cWin}。
function computePeaks_() {
  var sh = peakSheet_(); var last = sh.getLastRow(); if (last < 2) return {};
  var d = sh.getRange(2, 1, last - 1, PEAK_HEADERS.length).getValues(); var out = {};
  d.forEach(function (r) { if (!r[0]) return; out[r[0]] = { vRate: r[1] === '' ? null : Number(r[1]), vWin: r[2] || '', cRate: r[3] === '' ? null : Number(r[3]), cWin: r[4] || '', wRate: (r[6] === '' || r[6] == null) ? null : Number(r[6]), wWin: r[7] || '' }; });
  return out;
}
function ytApiKey_() { return prop_('YT_API_KEY') || ''; }
function ytIdFromUrl_(u) {
  u = String(u || '');
  var m = u.match(/[?&]v=([0-9A-Za-z_-]{6,})/) || u.match(/youtu\.be\/([0-9A-Za-z_-]{6,})/) || u.match(/shorts\/([0-9A-Za-z_-]{6,})/);
  return m ? m[1] : '';
}
function ytViews_(ids, pubOut, diag) {
  var key = ytApiKey_(), out = {};
  if (!key || !ids.length) return out;
  // pubOut を渡すと publishedAt(実公開時刻ms)も回収する。part に snippet を足すだけ=追加クォータ0。
  var part = pubOut ? 'statistics,snippet' : 'statistics';
  for (var i = 0; i < ids.length; i += 50) {
    // ★YouTube動画IDの形(11文字の[A-Za-z0-9_-])に一致する物だけAPIへ渡す(2026-08-16D恒久対策)。
    //   SALE擬似vid('SALE'/'SALE:krQsP'=コロン混入)や壊れたURL由来の不正IDが1つでもバッチに混ざると
    //   videos.listがそのバッチ全体を400で弾き、同バッチの実在vidの再生数まで丸ごと欠落していた
    //   =viewsが全null→ピーク算出の材料が無くピーク記録が埋まらない一因(実測DIAG viewsKeys=0)。
    var batch = ids.slice(i, i + 50).filter(function (id) { return /^[A-Za-z0-9_-]{11}$/.test(String(id)); });
    if (!batch.length) continue;
    try {
      var u = 'https://www.googleapis.com/youtube/v3/videos?part=' + part + '&id=' + batch.join(',') + '&key=' + encodeURIComponent(key);
      var res = UrlFetchApp.fetch(u, { muteHttpExceptions: true });
      if (diag) diag.push({ i: i, n: batch.length, http: res.getResponseCode(), body: res.getResponseCode() >= 300 ? String(res.getContentText() || '').slice(0, 160) : '' });
      if (res.getResponseCode() >= 300) continue;
      var d = JSON.parse(res.getContentText() || '{}');
      (d.items || []).forEach(function (it) {
        if (!it || !it.id) return;
        if (it.statistics && it.statistics.viewCount != null) out[it.id] = parseInt(it.statistics.viewCount, 10);
        if (pubOut && it.snippet && it.snippet.publishedAt) { var t = Date.parse(it.snippet.publishedAt); if (!isNaN(t)) pubOut[it.id] = t; }
      });
    } catch (e) {}
    Utilities.sleep(120);
  }
  return out;
}
// 名前付きセールURLの短縮コードをアカウント別に保存する。(フロント action=sale_reg から)
//   コードは [0-9A-Za-z] のみ許可(短縮コードの形)。最大30件。snapshotStats がこれを読んで各コードを日次スナップ。
function saleReg_(acc, saleJson) {
  acc = (acc === 'acc2') ? 'acc2' : 'acc1';
  var arr = [];
  try { arr = JSON.parse(saleJson || '[]'); } catch (e) { return { ok: false, error: 'bad_json' }; }
  if (!Array.isArray(arr)) return { ok: false, error: 'not_array' };
  var codes = [];
  arr.forEach(function (c) { c = String(c || ''); if (/^[0-9A-Za-z]+$/.test(c) && codes.indexOf(c) < 0 && codes.length < 30) codes.push(c); });
  PropertiesService.getScriptProperties().setProperty('SALE_CODES_' + acc, JSON.stringify(codes));
  return { ok: true, acc: acc, count: codes.length };
}
function snapshotStats() {
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';
  var today = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');
  var nowStr = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd HH:mm');
  // ★実行の時間予算(2026-08-16B・ピーク全滅の"現"真因の恒久対策)。
  //   GASの1実行は約6分で強制終了する。snapshotStatsは①投稿日時のYouTube公開時刻バックフィル(dateFix・
  //   2026-08-15Aで追加=全履歴行を走査しsetValue)と②全コードのクリック取得(workerClicks_を1コードずつ+80ms待機)
  //   で膨らみ、履歴が増えて6分を超えるようになった=実行ごとに時間切れで失敗→Googleがトリガーを自動停止し
  //   「2026-08-15 19:51Zを最後にスナップが完全停止=ピーク記録シートが埋まらない」状態だった(実測・真因)。
  //   対策=重い2ループを時間予算で頭打ちにし、必ず書き込み/ピーク算出フェーズへ到達させる。打ち切った分は
  //   冪等なので次の5分実行で続行し、数回で定常(バックフィル完了後は軽くなる)。★心がけでなく機構で6分を超えさせない。
  //   ★2026-08-16C修正=ピーク永続化は「本体upsertループの後」にある。旧配分(日時2分+クリック4分)だと
  //     残り2分ではupsertループが終わらず、ピーク永続化(considerPeak_で溜めた分の書き込み)へ到達する前に
  //     6分で殺されていた=スナップは書けてもピークは0のまま(実測23:25の便で確認)。配分を前詰めにし、
  //     upsert/ピーク算出ループ自体も予算で頭打ち=打ち切ってもその時点までの溜め分は必ず永続化へ抜ける(冪等・次回続行)。
  var RUN_T0 = Date.now();
  var BUDGET_DATEFIX_MS = 90000;  // 日時バックフィルは最大90秒
  var BUDGET_CLICKS_MS = 180000;  // クリック取得は通算3分で打ち切り
  var BUDGET_RECS_MS = 300000;    // 本体upsert+ピーク算出は通算5分で打ち切り=残り1分で必ずピーク永続化へ到達させる
  var DIAG = { recs: 0, vNN: 0, cNN: 0, wNN: 0, prev: 0, hrsOK: 0, consider: 0, viewsKeys: 0 }; // ★一時診断(2026-08-16・ピークが0のままの切り分け用)
  var recs = [], tpRecs = [], dateFix = []; // tpRecs=時点記録(投稿からの経過バケット)用の全行(vid無し・クリックのみも含む)／dateFix=投稿日時をYouTube公開時刻へ直す対象行
  CH_SHEETS.forEach(function (name) {
    var ss = openSS_(); var sh = ss.getSheetByName(name); if (!sh) return;
    var map = headerMap_(sh); var last = sh.getLastRow(); if (last < 2) return;
    var pidc = map['post_id'], ytc = map['YouTube動画URL'], sc = map['短縮URL'], dc = map['投稿日時'], wsc = map['作品短縮URL'];
    var chKey = (name === '宵桜艶帖') ? 'acc2' : 'acc1';
    var vals = sh.getRange(2, 1, last - 1, sh.getLastColumn()).getValues();
    vals.forEach(function (row, ri) {
      var vid = ytc ? ytIdFromUrl_(row[ytc - 1]) : '';
      var code = sc ? codeFromShort_(row[sc - 1]) : '';
      var wcode = wsc ? codeFromShort_(row[wsc - 1]) : ''; // 導線2(作品クリック)の計測コード
      // 時点記録(⑤)用: vidが無くてもクリックだけ記録できるよう、YT未連携行も対象に含める。
      var pd = dc ? row[dc - 1] : '';
      var pms = pd instanceof Date ? pd.getTime() : (pd ? (new Date(String(pd).replace(/-/g, '/'))).getTime() : 0);
      if ((vid || code || wcode) && pms) tpRecs.push({ channel: chKey, post_id: pidc ? String(row[pidc - 1] || '') : '', vid: vid, code: code, wcode: wcode, postedAtMs: pms });
      // 投稿日時をYouTube公開時刻へ直す対象(vidとdc列がある行のみ・pmsは空欄でも0で保持し埋め対象にする)。
      if (vid && dc) dateFix.push({ sh: sh, dc: dc, row: ri + 2, vid: vid, pms: pms });
      if (!vid) return;
      recs.push({ channel: chKey, post_id: pidc ? String(row[pidc - 1] || '') : '', vid: vid, code: code, wcode: wcode });
    });
  });
  if (!recs.length && !tpRecs.length) return;
  // 同一videoId(同じ動画を複数投稿・両ch)で重複行を作らないよう vid で1件に正規化。(最初の1件＝コード保持)
  var seenVid = {}, urecs = [];
  recs.forEach(function (r) { if (r.vid && !seenVid[r.vid]) { seenVid[r.vid] = 1; urecs.push(r); } });
  recs = urecs;
  // セール会場リンク(導線3・共通コードJrziR=campaign利用のutm先)も日次記録する。(2026-07-14 Chami依頼)
  //   vid='SALE'の擬似行として保存→computeDeltas_が自動で今日/昨日/週を算出し、フロントの🏮表示が使う。
  recs.push({ channel: '-', post_id: 'SALE', vid: 'SALE', code: 'JrziR' });
  // 名前付きセールURL(夏セール等)も各コードを個別スナップ→フロントで名前別に今日/昨日/週を出す。(Chami依頼2026-07-29)
  //   コードはフロントが action=sale_reg で登録(アカウント別プロパティ)。vid='SALE:'+code で個別行にする。
  var saleSeen = { JrziR: 1 };
  ['acc1', 'acc2'].forEach(function (a) {
    var arr = []; try { arr = JSON.parse(prop_('SALE_CODES_' + a) || '[]'); } catch (e) { arr = []; }
    if (!Array.isArray(arr)) return;
    arr.forEach(function (c) {
      c = String(c || ''); if (!/^[0-9A-Za-z]+$/.test(c) || saleSeen[c]) return;
      saleSeen[c] = 1;
      recs.push({ channel: '-', post_id: 'SALE:' + c, vid: 'SALE:' + c, code: c });
    });
  });
  var vids = recs.map(function (r) { return r.vid; });
  var pubByVid = {};
  var views = ytViews_(vids, pubByVid, (DIAG.yt = []));
  // ★投稿日時をYouTube公開時刻(publishedAt)へ自動収束(Chami依頼 REQ-2f4520e4d7)。
  //   記録の投稿日時は既定で「投稿完了ボタンを押した時刻」(writeRecord_の新規行フォールバックのnow)が入る。
  //   これを5分毎スナップに相乗りで実公開時刻へ直す=新規は公開後≤5分で自動修正・空欄埋め・既存誤記録もバックフィル。
  //   ±60秒以内に一致している行は触らない(冪等)。修正したシートだけ投稿日時で1回整列(fix_date_from_yt と同じ後処理)。
  (function () {
    var fixedSheets = [], seen = {};
    dateFix.forEach(function (x) {
      if (Date.now() - RUN_T0 > BUDGET_DATEFIX_MS) return; // ★予算超過後はこの回の日時修正を打ち切る(次回続行・冪等)。クリック/ピークの時間を守る
      var pub = pubByVid[x.vid];
      if (!pub) return;
      if (x.pms && Math.abs(x.pms - pub) <= 60000) return;
      try {
        x.sh.getRange(x.row, x.dc).setValue(new Date(pub));
        var k = x.sh.getName() + '|' + x.dc;
        if (!seen[k]) { seen[k] = 1; fixedSheets.push({ sh: x.sh, dc: x.dc }); }
      } catch (e) {}
    });
    fixedSheets.forEach(function (f) { try { sortByDate_(f.sh, f.dc); } catch (e) {} });
  })();
  var clickByCode = {};
  // 導線1(短縮URL)＋導線2(作品短縮URL)の両コードのクリックをまとめて取得。(同一コードは1回)
  recs.concat(tpRecs).forEach(function (r) {
    if (Date.now() - RUN_T0 > BUDGET_CLICKS_MS) return; // ★予算超過後はクリック取得を打ち切る(未取得コードは次回続行)。views/ピークは下で必ず書く=関数は必ず完走する
    if (r.code && clickByCode[r.code] === undefined) { clickByCode[r.code] = workerClicks_(r.code); Utilities.sleep(80); }
    if (r.wcode && clickByCode[r.wcode] === undefined) { clickByCode[r.wcode] = workerClicks_(r.wcode); Utilities.sleep(80); }
  });
  var sh = statsSheet_(); var last = sh.getLastRow();
  var data = last >= 2 ? sh.getRange(2, 1, last - 1, STATS_HEADERS.length).getValues() : [];
  // ★日付列はSheetが 'yyyy-MM-dd' 文字列を Date に自動変換して返すことがある。キーは必ず
  //   同一TZの 'yyyy-MM-dd' 文字列に正規化する(Dateのまま比較すると today 文字列と一致せず、
  //   同日行の upsert が効かず重複追記＆deltas全null になる)。
  var idx = {}; for (var i = 0; i < data.length; i++) idx[ymd_(data[i][1], tz) + '|' + data[i][4]] = i + 2;
  // 前回スナップ(vidごとの最新の累計と時刻)＝最大瞬間風速(区間の伸び率)算出用。
  //   ★記録日時セルはSheetsがDateオブジェクトに変換して返す(日付列と同じ・上のymd_注記と同根)。
  //     旧実装は String(セル値).replace(' ','T') を Date.parse していたが、String(Date)は
  //     "Sat Aug 16 2026 …" 形式のため先頭空白置換で常にNaN→tms=0→下の if(prev && prev.tms) が
  //     恒久false→considerPeak_が一度も呼ばれず「ピーク記録シートが永遠に0行」だった(真因・2026-08-16)。
  //     Date/文字列の両対応に正規化する(deltasが生きてピークだけ全滅していたのはこの1行の差)。
  var prevByVid = {};
  for (var j = 0; j < data.length; j++) {
    var pv = data[j][4]; if (!pv) continue;
    var t0 = data[j][0], tms = 0, tstr = '';
    if (t0 instanceof Date) { tms = t0.getTime(); tstr = Utilities.formatDate(t0, tz, 'yyyy-MM-dd HH:mm'); }
    else { tstr = String(t0 || ''); tms = Date.parse(tstr.replace(' ', 'T')) || 0; }
    var pp = prevByVid[pv];
    if (!pp || tms > pp.tms) prevByVid[pv] = { tms: tms, tstr: tstr, views: data[j][5] === '' ? null : Number(data[j][5]), clicks: data[j][6] === '' ? null : Number(data[j][6]), wclicks: (data[j][7] === '' || data[j][7] == null) ? null : Number(data[j][7]) };
  }
  var nowMs = new Date().getTime();
  // ピーク記録シートを読み込み。(vidごとの現ピーク)今runの更新はpeakUpdatesへ。
  var psh = peakSheet_(); var plast = psh.getLastRow();
  var pdata = plast >= 2 ? psh.getRange(2, 1, plast - 1, PEAK_HEADERS.length).getValues() : [];
  var pidx = {}; for (var pk = 0; pk < pdata.length; pk++) pidx[pdata[pk][0]] = pk + 2;
  var peakUpdates = {};
  function curPeak_(vid, kind) {
    if (peakUpdates[vid] && peakUpdates[vid][kind + 'Rate'] != null) return peakUpdates[vid][kind + 'Rate'];
    var rn = pidx[vid]; if (rn) { var col = kind === 'v' ? 1 : (kind === 'c' ? 3 : 6); var val = pdata[rn - 2][col]; return (val === '' || val == null) ? null : Number(val); }
    return null;
  }
  function considerPeak_(vid, kind, rate, win) {
    DIAG.consider++;
    if (rate == null) return;
    if (!(rate > 0)) {
      // ★増加ゼロ(or YT下方補正の負)区間: ピークは更新しないが、まだ一度も記録が無い作品には
      //   0(件/時)を種まきして必ず行を作る(2026-08-16恒久対策)。従来は「増加が観測されるまで無記録」
      //   =低速動画がランキングのピーク窓から消え続け、記録機能の全滅(今回の真因)も「まだ記録なし」と
      //   区別が付かず沈黙していた。0値行なら 表示は必ず埋まり・シート0行=即異常 と構造で判別できる。
      //   SALE擬似行(vid='SALE'/'SALE:コード')は動画ランキング外なので種まき対象外(正のピーク更新は従来通り)。
      if (String(vid).indexOf('SALE') === 0) return;
      if (curPeak_(vid, kind) == null) { var u0 = peakUpdates[vid] || (peakUpdates[vid] = {}); u0[kind + 'Rate'] = 0; u0[kind + 'Win'] = win; }
      return;
    }
    var cur = curPeak_(vid, kind);
    if (cur == null || rate > cur) { var u = peakUpdates[vid] || (peakUpdates[vid] = {}); u[kind + 'Rate'] = Math.round(rate * 10) / 10; u[kind + 'Win'] = win; }
  }
  var appends = [];
  recs.forEach(function (r) {
    if (Date.now() - RUN_T0 > BUDGET_RECS_MS) return; // ★予算超過後は残りrecsのupsert/ピーク算出を打ち切る=溜めたpeakUpdatesの永続化(下)へ必ず抜ける(次回続行・冪等)
    DIAG.recs++;
    var v = views[r.vid]; var c = r.code ? clickByCode[r.code] : null;
    if (v != null) DIAG.vNN++; if (c != null) DIAG.cNN++;
    var wc = r.wcode ? clickByCode[r.wcode] : null; // 導線2(作品クリック)
    if (v == null && c == null && wc == null) return;
    var key = today + '|' + r.vid, rowN = idx[key];
    if (rowN && rowN > 0) {
      sh.getRange(rowN, 1).setValue(nowStr);
      if (v != null) sh.getRange(rowN, 6).setValue(v);
      if (c != null) sh.getRange(rowN, 7).setValue(c);
      if (wc != null) sh.getRange(rowN, 8).setValue(wc); // 作品クリック数列
    } else {
      appends.push([nowStr, today, r.channel, r.post_id, r.vid, v == null ? '' : v, c == null ? '' : c, wc == null ? '' : wc]);
      idx[key] = -1;
    }
    // 最大瞬間風速：前回スナップからの伸び率。(件/時)妥当な間隔のみ採用。
    // ★下限は 0.06h(3.6分)。snapshotStats を5分毎(=0.083h)に縮めた(ピークを早く記録・Chami2026-08-11)ため、
    //   5分間隔(±揺らぎ)を通す下限へ下げた。旧0.12h(7.2分)のままだと5分区間が常に下限割れで
    //   ピークが1件も記録されない(=10分毎に変えた際に下限0.2hを残して起きた2026-08-06の事故と同型)。
    //   事故的なサブ3.6分の二重発火だけを弾く。上限6hは据置(公開直後の急増だけをピークに採る)。
    if (wc != null) DIAG.wNN++;
    var prev = prevByVid[r.vid];
    if (prev && prev.tms) {
      DIAG.prev++;
      var hrs = (nowMs - prev.tms) / 3600000;
      if (hrs >= 0.06 && hrs <= 6) {
        DIAG.hrsOK++;
        var win = String(prev.tstr).slice(5) + '〜' + nowStr.slice(11); // MM-dd HH:mm〜HH:mm
        if (v != null && prev.views != null) considerPeak_(r.vid, 'v', (v - prev.views) / hrs, win);
        if (c != null && prev.clicks != null) considerPeak_(r.vid, 'c', (c - prev.clicks) / hrs, win);
        if (wc != null && prev.wclicks != null) considerPeak_(r.vid, 'w', (wc - prev.wclicks) / hrs, win); // 導線2(作品クリック=ピンク)のピーク(2026-08-11)
      }
    }
  });
  if (appends.length) sh.getRange(sh.getLastRow() + 1, 1, appends.length, STATS_HEADERS.length).setValues(appends);
  // ピーク更新を永続化。(vidごとにupsert。既存より大きい時だけ更新済み)
  Object.keys(peakUpdates).forEach(function (vid) {
    var u = peakUpdates[vid], rn = pidx[vid];
    if (rn) {
      if (u.vRate != null) { psh.getRange(rn, 2).setValue(u.vRate); psh.getRange(rn, 3).setValue(u.vWin); }
      if (u.cRate != null) { psh.getRange(rn, 4).setValue(u.cRate); psh.getRange(rn, 5).setValue(u.cWin); }
      if (u.wRate != null) { psh.getRange(rn, 7).setValue(u.wRate); psh.getRange(rn, 8).setValue(u.wWin); } // 導線2(作品クリック)ピーク
      psh.getRange(rn, 6).setValue(nowStr);
    } else {
      psh.appendRow([vid, u.vRate == null ? '' : u.vRate, u.vWin || '', u.cRate == null ? '' : u.cRate, u.cWin || '', nowStr, u.wRate == null ? '' : u.wRate, u.wWin || '']);
      pidx[vid] = psh.getLastRow();
    }
  });
  pruneStats_(sh, 12);
  // CH書き戻し(2026-07-13A・Chami依頼): 累計再生/クリックを投稿記録シートの列にも反映し、
  //   YouTubeの下方補正(前回スナップより累計が減った分)は「YT補正累計」列へ累積する。
  //   デルタ(昨日/週)は従来通り実測(マイナスあり得る)＝真の視聴増はこの列の増分を引けば分離できる。
  try {
    var corrByVid = {};
    recs.forEach(function (r0) {
      var v0 = views[r0.vid], p0 = prevByVid[r0.vid];
      if (v0 != null && p0 && p0.views != null && v0 < p0.views) corrByVid[r0.vid] = p0.views - v0;
    });
    CH_SHEETS.forEach(function (name3) {
      var ss3 = openSS_(); var sh3 = ss3.getSheetByName(name3); if (!sh3) return;
      var map3 = headerMap_(sh3); var l3 = sh3.getLastRow(); if (l3 < 2) return;
      var ytc3 = map3['YouTube動画URL']; if (!ytc3) return;
      var vc3 = map3['視聴回数'], cc3 = map3[clickColName_(map3)], sc3 = map3['短縮URL'], corrc3 = map3['YT補正累計'];
      var vals3 = sh3.getRange(2, 1, l3 - 1, sh3.getLastColumn()).getValues();
      for (var r3 = 0; r3 < vals3.length; r3++) {
        var vid3 = ytIdFromUrl_(vals3[r3][ytc3 - 1]); if (!vid3) continue;
        var rowN3 = r3 + 2;
        var v3 = views[vid3];
        if (vc3 && v3 != null && Number(vals3[r3][vc3 - 1]) !== v3) sh3.getRange(rowN3, vc3).setValue(v3);
        var code3 = sc3 ? codeFromShort_(vals3[r3][sc3 - 1]) : '';
        var c3 = code3 ? clickByCode[code3] : null;
        if (cc3 && c3 != null && Number(vals3[r3][cc3 - 1]) !== c3) sh3.getRange(rowN3, cc3).setValue(c3);
        var corr3 = corrByVid[vid3];
        if (corrc3 && corr3 > 0) {
          var cur3 = Number(vals3[r3][corrc3 - 1] || 0);
          sh3.getRange(rowN3, corrc3).setValue(cur3 + corr3);
        }
      }
    });
  } catch (e) {}
  // ⑤時点記録: 投稿からの経過バケット(30分〜72h)を跨いだ最初のスナップで再生数/クリック数を確定記録。
  try { captureTimepoints_(tpRecs, views, clickByCode, nowStr, tz); } catch (e) {}
  DIAG.viewsKeys = Object.keys(views).length;
  DIAG.peakUpdates = Object.keys(peakUpdates).length;
  return DIAG; // ★一時診断(2026-08-16)。ピークが0のままの切り分け用。トリガー実行時は戻り値は無視される
}
// 12日より古い履歴行を掃除。(週次差分に必要なぶんだけ保持)
function pruneStats_(sh, keepDays) {
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';
  var cut = new Date(); cut.setDate(cut.getDate() - keepDays);
  var cutStr = Utilities.formatDate(cut, tz, 'yyyy-MM-dd');
  var last = sh.getLastRow(); if (last < 2) return;
  var dates = sh.getRange(2, 2, last - 1, 1).getValues();
  for (var i = dates.length - 1; i >= 0; i--) { if (ymd_(dates[i][0], tz) < cutStr) sh.deleteRow(i + 2); } // ★Date/文字列を正規化して比較
}
// 日付セルを 'yyyy-MM-dd' 文字列に正規化。(Date/文字列どちらで返っても同一TZの日付キーにする)
function ymd_(v, tz) {
  tz = tz || Session.getScriptTimeZone() || 'Asia/Tokyo';
  if (v instanceof Date) return Utilities.formatDate(v, tz, 'yyyy-MM-dd');
  var s = String(v || '');
  var m = s.match(/^(\d{4})-(\d{2})-(\d{2})/); if (m) return m[0];
  var d = new Date(s); return isNaN(d.getTime()) ? s : Utilities.formatDate(d, tz, 'yyyy-MM-dd');
}
// 視聴履歴から videoId ごとの 今日/昨日/直近1週間 の増加(再生数・クリック数)を算出。
function computeDeltas_() {
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';
  var sh = statsSheet_(); var last = sh.getLastRow(); if (last < 2) return {};
  var data = sh.getRange(2, 1, last - 1, STATS_HEADERS.length).getValues();
  var byVid = {};
  data.forEach(function (row) {
    var date = ymd_(row[1], tz), vid = row[4]; if (!vid || !date) return; // ★日付は文字列キーに正規化
    (byVid[vid] || (byVid[vid] = {}))[date] = { v: row[5] === '' ? null : Number(row[5]), c: row[6] === '' ? null : Number(row[6]), w: (row[7] === '' || row[7] == null) ? null : Number(row[7]) };
  });
  // 投稿日(vid別・最古)を記録シートから取得。ベースライン不在時の「0起点」判定に使う(Chami仕様2026-07-12):
  //   ・今日/昨日=その暦日の増分(投稿日に関係なく) ・週=直近7日間の合計
  //   ・投稿日が期間内でベースラインが存在し得ない場合は0起点(例: 今日投稿→今日=累計そのまま・週=同)
  //   ・「–」が許されるのは今日投稿の「昨日」のみ
  var postedByVid = {};
  CH_SHEETS.forEach(function (name) {
    var ss2 = openSS_(); var sh2 = ss2.getSheetByName(name); if (!sh2) return;
    var map2 = headerMap_(sh2); var l2 = sh2.getLastRow(); if (l2 < 2) return;
    var ytc2 = map2['YouTube動画URL'], dc2 = map2['投稿日時']; if (!ytc2 || !dc2) return;
    sh2.getRange(2, 1, l2 - 1, sh2.getLastColumn()).getValues().forEach(function (row) {
      var v2 = ytIdFromUrl_(row[ytc2 - 1]); if (!v2) return;
      var ds2 = ymd_(row[dc2 - 1], tz); if (!ds2) return;
      if (!postedByVid[v2] || ds2 < postedByVid[v2]) postedByVid[v2] = ds2;
    });
  });
  function dstr(off) { var d = new Date(); d.setDate(d.getDate() + off); return Utilities.formatDate(d, tz, 'yyyy-MM-dd'); }
  var today = dstr(0), yest = dstr(-1), wk = dstr(-7);
  var ZERO = { v: 0, c: 0 };
  var out = {};
  Object.keys(byVid).forEach(function (vid) {
    var m = byVid[vid], dates = Object.keys(m).sort();
    var posted = postedByVid[vid] || '';
    // ★クリック計測URL(導線1=c / 導線2=w)の短縮コードが差し替わると、新コードのカウンタは0起点になり
    //   日次スナップの系列が [.., 16, 16, 0, 3] のように「段差で落ちる」。この段差を検出して旧コードの
    //   最終値を土台へ繰り上げ、単調増加の「実数」へ積み直す(Chami「累計0なのに先週-16」2026-07-29)。
    //   ※クリックは減らない前提のc/wだけ。再生数(v)はYouTubeの下方修正で正当に減るので積み直さない。
    //   ※取得失敗はnull(空欄)で記録され段差判定に使わない=偶発0で誤って繰り上げない。
    function reconMonotonic_(k) {
      var carry = 0, prevRaw = null;
      for (var ri = 0; ri < dates.length; ri++) {
        var cell = m[dates[ri]], raw = cell[k];
        if (raw == null) continue;
        if (prevRaw != null && raw < prevRaw) carry += prevRaw; // コード差し替え=旧コード最終値を土台に繰上げ
        cell[k] = raw + carry;                                  // 実数へ積み直し(以後 lastNonNull/curOf はこの値を読む)
        prevRaw = raw;
      }
    }
    reconMonotonic_('c'); reconMonotonic_('w');
    // ★列ごと(v=再生/c=クリック)に独立して基準を解決する。(2026-07-12C・根本修正)
    //   「再生数は前から記録・クリックは今日から記録開始」のような列単位のズレで、
    //   既存スナップの空欄(null)を基準に採って⚠を出していた設計ミスを直す。
    //   規則: 基準日以前に非nullが無い列=「その列の記録がまだ始まっていなかった」→0起点。
    //   (今日投稿の0起点・7日以内投稿の週0起点も、この一般則に自然に含まれる)
    function lastNonNull(k, ds, inclusive) { // ds以前(未満)で最後にk列が非nullだった値
      var best = null;
      for (var i = 0; i < dates.length; i++) {
        var ok = inclusive ? (dates[i] <= ds) : (dates[i] < ds);
        if (ok && m[dates[i]][k] != null) best = m[dates[i]][k];
      }
      return best;
    }
    function curOf(k) { var c = m[today]; if (c && c[k] != null) return c[k]; return lastNonNull(k, '9999-99-99', true); }
    function calc(k) {
      var cur = curOf(k);
      if (cur == null) return { t: null, y: null, w: null, cur: null }; // その列は一度も記録なし=正直に⚠(取得失敗系)
      var bT = lastNonNull(k, today, false); if (bT == null) bT = 0;   // 今日の基準: 無ければ記録開始=今日→0起点
      var bW = lastNonNull(k, wk, true);     if (bW == null) bW = 0;   // 週の基準: 無ければ記録開始が7日以内→0起点
      var y;
      if (posted === today) y = null; // 唯一の–許容(今日投稿の昨日)
      else {
        var aY = lastNonNull(k, today, false);         // 昨日終了時点の値
        var bY = lastNonNull(k, yest, false);          // 一昨日終了時点の値(無ければ記録開始が昨日→0起点)
        y = (aY == null) ? null : (aY - (bY == null ? 0 : bY)); // aY自体が無い=昨日以前の記録ゼロ→⚠(不可知)
      }
      return { t: cur - bT, y: y, w: cur - bW, cur: cur };
    }
    var V = calc('v'), C = calc('c'), W = calc('w');
    // twc/ywc/wwc = 導線2(作品クリック=ピンク矢印)の今日/昨日/週デルタ。(Chami依頼2026-07-14)
    // cc/cwc = 積み直し済みの「実数の累計」(導線1/導線2)。短縮コード差し替えで0起点に戻る前の分も含む。
    //   フロントはこれを累計表示の下限に使い、「累計0なのに週N」「週-16」の矛盾を根から消す。(Chami 2026-07-29)
    out[vid] = { tv: V.t, yv: V.y, wv: V.w, tc: C.t, yc: C.y, wc: C.w, twc: W.t, ywc: W.y, wwc: W.w, cc: C.cur, cwc: W.cur };
  });
  return out;
}

// 初回1回：毎時トリガーを登録。
//   refreshClicks＝link-worker 開封数の取り込み／refreshEngagement＝Bluesky反応／
//   snapshotStats＝再生数・クリック数の日次スナップショット。(今日/昨日/週の増加算出用)
//   再実行で既存トリガーを掃除してから貼り直す。
function setupTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    var f = t.getHandlerFunction();
    if (f === 'refreshClicks' || f === 'refreshEngagement' || f === 'snapshotStats' ||
        f === 'runCompetitorDaily' || f === 'runCompetitorDiscovery') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('refreshClicks').timeBased().everyHours(1).create();
  ScriptApp.newTrigger('refreshEngagement').timeBased().everyHours(1).create();
  // ⑤時点記録の精度確保＋ピークを早く記録するためスナップを5分毎に(Chami依頼2026-08-11「ピークを早く記録できるように」)。
  //   許容窓9分と組み合わせ「バケット+0〜5分」以内に確定記録=旧10分毎より時点もピークも早く埋まる。
  //   ★下限0.06h(3.6分)と対で運用(下の considerPeak_ 区間判定)。間隔を縮める時は下限も必ず一緒に下げる
  //     (10分毎時に下限0.2hのまま残しピークが1件も記録されなかった事故=2026-08-06 の再発防止)。
  ScriptApp.newTrigger('snapshotStats').timeBased().everyMinutes(5).create();
  // 競合サーチ(gas/競合.gs): 日次スナップ=毎日4時台 / 発見=日曜4時台。watch対象0件の間は無害に空回り
  ScriptApp.newTrigger('runCompetitorDaily').timeBased().everyDays(1).atHour(4).create();
  ScriptApp.newTrigger('runCompetitorDiscovery').timeBased().onWeekDay(ScriptApp.WeekDay.SUNDAY).atHour(4).create();
}

// ============================================================
// ⑤ 時点記録: 投稿時刻からの経過バケット(30分/1h/2h/6h/24h/72h)ごとに、そのバケットを
//   跨いだ最初のスナップ実行時の再生数・クリック数を「時点記録」シートへ確定保存する。
//   旧実装(ランキングタブのlocalStorageバケット)は端末でアプリを開いた時しか記録されず
//   欠測が常態化していたため、サーバー(30分毎トリガー)で確実に記録する。(2026-07-12)
//   ・許容窓を過ぎたバケットは記録しない(遅れた値を「その時点の値」と偽らない)＝空欄は未記録の正直な表現
//   ・1行=1。(post_id×バケット)分析はピボットで post_id 別に横持ち化できる
// ============================================================
var TIMEPOINT_SHEET = '時点記録';
// ★'ピンククリック'(導線2=作品クリック)を末尾へ追加(2026-08-08)。末尾なのは既存行の列ズレを避けるため
//   (途中挿入すると旧行の記録日時がピンク値として誤読される)。旧行は空欄=null。timepointSheet_ で冪等移行。
var TIMEPOINT_HEADERS = ['post_id', 'channel', '投稿日時', 'バケット', '経過分(実測)', '再生数', 'クリック数', '記録日時', 'ピンククリック'];
// ★12時間/48時間 を追加(Chami報告2026-08-06「全候補が記録されてるかチェック」)。旧実装はこの2窓を
//   GAS未記録にしていた=端末スナップ頼みで常態的に空だった。8窓すべてをサーバー記録に揃える。
var TIME_BUCKETS = [[30, '30分'], [60, '1時間'], [120, '2時間'], [360, '6時間'], [720, '12時間'], [1440, '24時間'], [2880, '48時間'], [4320, '72時間']];
function timepointSheet_() {
  var ss = openSS_(); var sh = ss.getSheetByName(TIMEPOINT_SHEET);
  if (!sh) { sh = ss.insertSheet(TIMEPOINT_SHEET); sh.appendRow(TIMEPOINT_HEADERS); }
  else if (sh.getLastRow() === 0) { sh.appendRow(TIMEPOINT_HEADERS); }
  else {
    // 冪等移行: 既存シートに新列(ピンククリック 等)が無ければヘッダ行へ補う。データ行は触らない
    //   =旧行のピンク列は空欄のまま(computeが null 扱い)。列ズレを起こさないので安全(2026-08-08)。
    var hdr = sh.getRange(1, 1, 1, TIMEPOINT_HEADERS.length).getValues()[0];
    for (var i = 0; i < TIMEPOINT_HEADERS.length; i++) {
      if (String(hdr[i] || '') !== TIMEPOINT_HEADERS[i]) sh.getRange(1, i + 1).setValue(TIMEPOINT_HEADERS[i]);
    }
  }
  return sh;
}
// 時点記録シート → videoIdごとの {b30:{v,c,w,age}, b60:.., b120:.., b360:.., b1440:.., b4320:..}。
//   ランキングタブの「窓」表示用。シートは post_id 単位なので記録シートで post_id→videoId に解決してから返す。
//   ※GASが記録するのは 30分/1時間/2時間/6時間/12時間/24時間/48時間/72時間 の8バケット・再生数(v)/導線1クリック(c)/
//     導線2(作品クリック=ピンク w)。★2026-08-08に導線2(w)を追加=端末を開いていない投稿でもピンク矢印の
//     バケットが埋まる(Chami「ピンクのクリックが集計されてない」)。(2026-08-06に12h/48hを追加)
function computeTimepoints_() {
  var sh = timepointSheet_(); var last = sh.getLastRow(); if (last < 2) return {};
  // post_id → videoId の対応表を記録シートから作る。
  var pid2vid = {};
  CH_SHEETS.forEach(function (name) {
    var ss = openSS_(); var s = ss.getSheetByName(name); if (!s) return;
    var map = headerMap_(s); var lr = s.getLastRow(); if (lr < 2) return;
    var pc = map['post_id'], yc = map['YouTube動画URL']; if (!pc || !yc) return;
    var vals = s.getRange(2, 1, lr - 1, s.getLastColumn()).getValues();
    vals.forEach(function (row) {
      var pid = String(row[pc - 1] || ''); if (!pid) return;
      var vid = ytIdFromUrl_(row[yc - 1]); if (vid && !pid2vid[pid]) pid2vid[pid] = vid;
    });
  });
  var LAB = { '30分': 'b30', '1時間': 'b60', '2時間': 'b120', '6時間': 'b360', '12時間': 'b720', '24時間': 'b1440', '48時間': 'b2880', '72時間': 'b4320' };
  var d = sh.getRange(2, 1, last - 1, TIMEPOINT_HEADERS.length).getValues();
  var out = {};
  d.forEach(function (r) {
    var pid = String(r[0] || ''); if (!pid) return;
    var vid = pid2vid[pid]; if (!vid) return;
    var key = LAB[String(r[3])]; if (!key) return;
    var age = r[4], v = r[5], c = r[6], w = r[8]; // r[7]=記録日時 / r[8]=ピンククリック(導線2・2026-08-08追加)
    if (!out[vid]) out[vid] = {};
    if (!out[vid][key]) out[vid][key] = { v: (v === '' ? null : Number(v)), c: (c === '' ? null : Number(c)), w: (w === '' || w == null ? null : Number(w)), age: (age === '' ? null : Number(age)) };
  });
  return out;
}
function captureTimepoints_(tpRecs, viewsByVid, clickByCode, nowStr, tz) {
  if (!tpRecs || !tpRecs.length) return 0;
  var sh = timepointSheet_(); var last = sh.getLastRow();
  var seen = {};
  if (last >= 2) {
    var ex = sh.getRange(2, 1, last - 1, 4).getValues();
    for (var i = 0; i < ex.length; i++) seen[String(ex[i][0]) + '|' + String(ex[i][3])] = 1;
  }
  var now = Date.now(); var added = [];
  tpRecs.forEach(function (r) {
    if (!r.post_id || !r.postedAtMs) return;
    var elapsed = (now - r.postedAtMs) / 60000;
    TIME_BUCKETS.forEach(function (b, bi) {
      var min = b[0], label = b[1];
      if (elapsed < min) return;
      // ★恒久(2026-08-23 軍議依頼): 旧実装は tol=9 の固定窓([min, min+9])でしか記録できず、
      //   その9分の間に snapshotStats が回らない(=5分毎トリガーが1回でも落ちる/6分上限で殺される・
      //   あるいは vid/クリックがまだ解決していない)と、そのバケットは二度と埋まらず永久欠測になった
      //   (実測=Chami手動投稿の水木金4本が b720 だけ残り b30〜b360 が全欠。トリガー取りこぼし＋
      //    YouTube URL結線が遅れた投稿で顕在化)。窓を「次のバケット境界の直前まで」へ広げる=そのバケット
      //   区間の間にデータの揃ったスナップが1回でも走れば必ず記録される。実経過分(下の Math.round(elapsed))
      //   を列5に必ず保存しているので、遅れて記録されても年齢正規化は下流(computeTimepoints_ の age)で保たれる。
      var cap = (bi + 1 < TIME_BUCKETS.length) ? TIME_BUCKETS[bi + 1][0] : (min + (min - TIME_BUCKETS[bi - 1][0])); // 最終(72h)は直前間隔ぶん(=96h)を上限
      if (elapsed >= cap) return; // 次のバケット区間に入った=この境界はもう遅すぎる(次バケット側が拾う)
      if (seen[r.post_id + '|' + label]) return;
      var v = (r.vid && viewsByVid && viewsByVid[r.vid] != null) ? viewsByVid[r.vid] : '';
      var c = (r.code && clickByCode && clickByCode[r.code] != null) ? clickByCode[r.code] : '';
      var w = (r.wcode && clickByCode && clickByCode[r.wcode] != null) ? clickByCode[r.wcode] : ''; // 導線2(ピンク)の時点値
      if (v === '' && c === '' && w === '') return; // どれも取れない行は書かない
      added.push([r.post_id, r.channel, Utilities.formatDate(new Date(r.postedAtMs), tz, 'yyyy-MM-dd HH:mm'), label, Math.round(elapsed), v, c, nowStr, w]);
      seen[r.post_id + '|' + label] = 1;
    });
  });
  if (added.length) sh.getRange(sh.getLastRow() + 1, 1, added.length, TIMEPOINT_HEADERS.length).setValues(added);
  return added.length;
}

// ============================================================
// ⑥ 列順統一: 両chシートの列を CANONICAL_HEADERS の並びへ固定する。(冪等)
//   無い列は正位置へ挿入。(空)CANONICALに無い列は末尾へ自然に寄る。値・書式ごとmoveColumnsで移動。
// ============================================================
function reorderHeaders_() {
  var out = {};
  CH_SHEETS.forEach(function (name) {
    var ss = openSS_(); var sh = ss.getSheetByName(name);
    if (!sh || sh.getLastRow() === 0) { out[name] = 'not_found'; return; }
    var moved = 0, inserted = 0;
    for (var target = 0; target < CANONICAL_HEADERS.length; target++) {
      var lastCol = sh.getLastColumn();
      var headers = sh.getRange(1, 1, 1, lastCol).getValues()[0].map(function (h) { return String(h); });
      var cur = headers.indexOf(CANONICAL_HEADERS[target]);
      if (cur === -1) {
        // 挿入位置が現在の列数を超える(=canonical末尾に新列を足した)場合はinsertColumnBeforeが範囲外エラーに
        // なるため末尾追加に切り替える。(2026-07-13B: YT補正累計の追加で発覚)
        if (target + 1 <= lastCol) sh.insertColumnBefore(target + 1); else sh.insertColumnAfter(lastCol);
        sh.getRange(1, target + 1).setValue(CANONICAL_HEADERS[target]); inserted++; continue;
      }
      if (cur === target) continue;
      sh.moveColumns(sh.getRange(1, cur + 1, sh.getMaxRows(), 1), target + 1); // 左方向への移動のみ発生(cur>target)
      moved++;
    }
    var finalHeaders = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0].map(String);
    out[name] = { moved: moved, inserted: inserted, cols: sh.getLastColumn(), extraTail: finalHeaders.slice(CANONICAL_HEADERS.length) };
  });
  return out;
}

// ============================================================
// Phase5：無人予約投稿(タブを閉じても、時間トリガーが自動投稿)
//   追加プロパティ：BSKY_HANDLE / BSKY_APP_PW。画像は base64→ドライブ一時保存→投稿後ゴミ箱。
// ============================================================
var RES_SHEET = '予約';
var RES_HEADERS = ['予約ID', '予約日時', '本文', '画像fileId', 'slot_id', 'ステータス', '結果URI', '結果URL', '投稿日時', 'エラー', 'channel', 'meta'];
var RCOL = { id: 1, when: 2, text: 3, img: 4, slot: 5, status: 6, uri: 7, url: 8, postedAt: 9, error: 10, channel: 11, meta: 12 };

function getResSheet_() {
  var ss = openSS_();
  var sh = ss.getSheetByName(RES_SHEET) || ss.insertSheet(RES_SHEET);
  if (sh.getLastRow() === 0) { sh.appendRow(RES_HEADERS); return sh; }
  // 既存シートに meta 列が無ければ末尾に追加。(冪等・D-1で追加)
  if (sh.getLastColumn() < RES_HEADERS.length) {
    var hdr = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0].map(String);
    if (hdr.indexOf('meta') === -1) sh.getRange(1, RCOL.meta).setValue('meta');
  }
  return sh;
}
function getDriveFolder_() {
  var name = 'go5-reservations';
  var it = DriveApp.getFoldersByName(name);
  return it.hasNext() ? it.next() : DriveApp.createFolder(name);
}
function dataUrlToBlob_(dataUrl) {
  var m = String(dataUrl).match(/^data:([^;]+);base64,(.*)$/);
  var type = m ? m[1] : 'image/jpeg', data = m ? m[2] : dataUrl;
  return Utilities.newBlob(Utilities.base64Decode(data), type);
}
function handleReserve_(body) {
  var sh = getResSheet_(); var imgId = '';
  if (body.image) {
    var blob = dataUrlToBlob_(body.image).setName('rsv_' + new Date().getTime() + '.jpg');
    imgId = getDriveFolder_().createFile(blob).getId();
  }
  var id = Utilities.getUuid(), row = [];
  row[RCOL.id - 1] = id; row[RCOL.when - 1] = body.scheduled_at || ''; row[RCOL.text - 1] = body.text || '';
  row[RCOL.img - 1] = imgId; row[RCOL.slot - 1] = body.slot_id || ''; row[RCOL.status - 1] = 'pending';
  row[RCOL.uri - 1] = ''; row[RCOL.url - 1] = ''; row[RCOL.postedAt - 1] = ''; row[RCOL.error - 1] = '';
  row[RCOL.channel - 1] = body.channel || 'acc1';
  // 動画メタ(videoId/カテゴリ/作品状態/リビルド元)をJSONで保持→投稿時に記録へ中継。(D-1・薄い行の解消)
  row[RCOL.meta - 1] = body.meta ? (typeof body.meta === 'string' ? body.meta : JSON.stringify(body.meta)) : '';
  sh.appendRow(row);
  return jsonOut_({ ok: true, id: id });
}
function runReservations() {
  var sh = getResSheet_(); var last = sh.getLastRow(); if (last < 2) return;
  var rows = sh.getRange(2, 1, last - 1, RES_HEADERS.length).getValues();
  var now = new Date();
  for (var i = 0; i < rows.length; i++) {
    if (rows[i][RCOL.status - 1] !== 'pending') continue;
    var when = new Date(rows[i][RCOL.when - 1]);
    if (isNaN(when.getTime()) || when > now) continue;
    sh.getRange(i + 2, RCOL.status).setValue('posting'); SpreadsheetApp.flush();
    try {
      var imgId = rows[i][RCOL.img - 1];
      var blob = imgId ? DriveApp.getFileById(imgId).getBlob() : null;
      var text = rows[i][RCOL.text - 1];
      var ch = rows[i][RCOL.channel - 1] || 'acc1';
      var res = bskyPost_(text, blob, ch); // ★予約行のchannelの資格情報で投稿(誤アカウント防止)
      sh.getRange(i + 2, RCOL.status).setValue('posted');
      sh.getRange(i + 2, RCOL.uri).setValue(res.uri);
      sh.getRange(i + 2, RCOL.url).setValue(res.postUrl);
      sh.getRange(i + 2, RCOL.postedAt).setValue(new Date());
      try {
        // 予約時に凍結した動画メタ(videoId/カテゴリ/作品状態/リビルド元)を記録へ中継。(D-1)
        var meta = {};
        try { var mj = rows[i][RCOL.meta - 1]; if (mj) meta = JSON.parse(mj) || {}; } catch (e) { meta = {}; }
        var attrs = meta.attrs || {};
        writeRecord_(ch, {
          videoId: meta.videoId || '',
          title: (String(text).split('\n')[0] || ''), postUrl: res.postUrl,
          affiliateUrl: (String(text).match(/https?:\/\/[^\s]+/) || [''])[0],
          workUrl: meta.workUrl || '', hashtags: extractHashtags_(text), postUri: res.uri,
          workState: meta.workState, rebuild: meta.rebuild, rebuildOf: meta.rebuildOf || '',
          goal: meta.goal || '', cmtType: meta.cmtType || '',
          chara: attrs.chara, jk: attrs.jk, gyaru: attrs.gyaru, isekai: attrs.isekai, harem: attrs.harem, ai: attrs.ai, ol: attrs.ol, soshu: attrs.soshu
        });
      } catch (e) {}
      if (imgId) { try { DriveApp.getFileById(imgId).setTrashed(true); } catch (e) {} }
    } catch (err) {
      sh.getRange(i + 2, RCOL.status).setValue('error');
      sh.getRange(i + 2, RCOL.error).setValue(String(err));
    }
    Utilities.sleep(300);
  }
}

// Bluesky 投稿。(サーバー側＝GASのアプリパスワードで投稿)
// ★channel別の資格情報(BSKY_HANDLE_ACC1/_ACC2 等)を優先。無ければ従来のBSKY_HANDLE/PWにフォールバック。
//   これで無人予約が「予約したアカウントとは別のアカウントで実投稿される」取り違えを防ぐ。
function bskyCreds_(channel) {
  var suf = channel === 'acc2' ? '_ACC2' : '_ACC1';
  var h = prop_('BSKY_HANDLE' + suf), p = prop_('BSKY_APP_PW' + suf);
  if (h && p) return { handle: h, pw: p, scoped: true };
  var otherSuf = channel === 'acc2' ? '_ACC1' : '_ACC2';
  var otherScopedSet = !!(prop_('BSKY_HANDLE' + otherSuf) && prop_('BSKY_APP_PW' + otherSuf));
  return { handle: prop_('BSKY_HANDLE'), pw: prop_('BSKY_APP_PW'), scoped: false, otherScopedSet: otherScopedSet };
}
function bskyPost_(text, imageBlob, channel) {
  channel = channel || 'acc1';
  var cr = bskyCreds_(channel);
  var handle = cr.handle, pw = cr.pw;
  // 片方だけ per-account 資格が設定済み＝移行中。要求chの資格が無ければ誤アカウント投稿を避けて中止。
  //   (per-account 資格が全く無い純レガシーは従来通り共有BSKY_HANDLE/PWで投稿＝後方互換)
  if (!cr.scoped && cr.otherScopedSet) throw new Error(channel + ' の資格情報(BSKY_HANDLE_' + (channel === 'acc2' ? 'ACC2' : 'ACC1') + ' / BSKY_APP_PW_' + (channel === 'acc2' ? 'ACC2' : 'ACC1') + ')が未設定のため中止(誤アカウント投稿防止)');
  if (!handle || !pw) throw new Error('BSKY_HANDLE / BSKY_APP_PW 未設定');
  var svc = 'https://bsky.social';
  var s = JSON.parse(UrlFetchApp.fetch(svc + '/xrpc/com.atproto.server.createSession', {
    method: 'post', contentType: 'application/json',
    payload: JSON.stringify({ identifier: String(handle).replace(/^@/, ''), password: pw }), muteHttpExceptions: true
  }).getContentText());
  if (!s.accessJwt) throw new Error('Blueskyログイン失敗');
  var embed = null;
  if (imageBlob) {
    var up = JSON.parse(UrlFetchApp.fetch(svc + '/xrpc/com.atproto.repo.uploadBlob', {
      method: 'post', contentType: imageBlob.getContentType() || 'image/jpeg',
      headers: { Authorization: 'Bearer ' + s.accessJwt }, payload: imageBlob.getBytes(), muteHttpExceptions: true
    }).getContentText());
    // ★alt(代替テキスト)は常に空。無人予約投稿でも画像ビューアに④コメント等が出るのを止める(Chami依頼2026-07-18・フロントのbluesky-core.jsと対で修正)。
    if (up.blob) embed = { '$type': 'app.bsky.embed.images', images: [{ alt: '', image: up.blob }] };
  }
  var record = { '$type': 'app.bsky.feed.post', text: text, createdAt: new Date().toISOString(), langs: ['ja'] };
  var facets = detectFacets_(text);
  if (facets.length) record.facets = facets;
  if (embed) record.embed = embed;
  var res = JSON.parse(UrlFetchApp.fetch(svc + '/xrpc/com.atproto.repo.createRecord', {
    method: 'post', contentType: 'application/json', headers: { Authorization: 'Bearer ' + s.accessJwt },
    payload: JSON.stringify({ repo: s.did, collection: 'app.bsky.feed.post', record: record }), muteHttpExceptions: true
  }).getContentText());
  var rkey = String(res.uri || '').split('/').pop();
  return { uri: res.uri || '', postUrl: (s.handle && rkey) ? ('https://bsky.app/profile/' + s.handle + '/post/' + rkey) : '' };
}

// 本文中の URL(#link) とハッシュタグ(#tag) の facet(index は UTF-8 バイトオフセット)
function byteLen_(s) { return Utilities.newBlob(String(s)).getBytes().length; }
function detectFacets_(text) {
  text = String(text || ''); var facets = [], used = [], m;
  var ure = /https?:\/\/[^\s]+/g;
  while ((m = ure.exec(text))) {
    var url = m[0].replace(/[.,;:!?。、！？))】」』]+$/, '');
    var s = m.index, e = s + url.length; used.push([s, e]);
    facets.push({ index: { byteStart: byteLen_(text.slice(0, s)), byteEnd: byteLen_(text.slice(0, e)) },
      features: [{ '$type': 'app.bsky.richtext.facet#link', uri: url }] });
  }
  var tre = /(^|\s)(#[^\s#]+)/g, t;
  while ((t = tre.exec(text))) {
    var hash = t[2].replace(/[.,;:!?。、！？))】」』]+$/, '');
    if (hash.length < 2) continue;
    var ts = t.index + t[1].length, te = ts + hash.length;
    if (used.some(function (r) { return ts < r[1] && te > r[0]; })) continue;
    facets.push({ index: { byteStart: byteLen_(text.slice(0, ts)), byteEnd: byteLen_(text.slice(0, te)) },
      features: [{ '$type': 'app.bsky.richtext.facet#tag', tag: hash.slice(1) }] });
  }
  facets.sort(function (a, b) { return a.index.byteStart - b.index.byteStart; });
  return facets;
}

// 初回1回：予約を5分ごとに自動投稿するトリガーを登録
function setupReservationTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'runReservations') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('runReservations').timeBased().everyMinutes(5).create();
}
