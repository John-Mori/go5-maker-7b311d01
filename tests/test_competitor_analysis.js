const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Frontend: 速度順で最大20件、指定された3段の情報を表示し、外部文字列をescapeする。
global.window = { Go5Util: {} };
global.localStorage = { getItem() { return null; }, setItem() {} };
global.document = { readyState: 'loading', addEventListener() {}, getElementById() { return null; } };
const { analysisHtml } = require('../competitor.js');
const titles = Array.from({ length: 25 }, (_, i) => ({
  videoId: 'video-' + String(i).padStart(2, '0'),
  channelName: i === 24 ? '<script>危険</script>' : 'チャンネル' + i,
  subscriberCount: i === 23 ? null : 1000 + i,
  title: '題名' + i,
  speed: i * 10,
  totalViews: 10000 + i,
  publishedAt: i === 24 ? '2026-07-24T23:05:56Z' : '2026-07-23T00:00:00Z',
  isShort: 'yes'
}));
const html = analysisHtml({ watchChannels: 3 }, { titles });
assert.equal((html.match(/class="comp-an-video"/g) || []).length, 20, '上位20件だけ表示する');
assert.ok(html.indexOf('チャンネル24') < html.indexOf('チャンネル23'), '1日の伸びが多い順に並ぶ');
assert.match(html, /登録者数 1,024/);
assert.match(html, /\+240\/日/);
assert.match(html, /総再生数 10,024/);
assert.match(html, /投稿日 7月25日 8時05分/);
assert.match(analysisHtml({}, { titles: [{ title: '日時なし' }] }), /投稿日 取得不可/);
assert.match(html, /非公開・取得不可/);
assert.doesNotMatch(html, /<script>危険<\/script>/, 'チャンネル名をHTMLとして解釈させない');
assert.match(html, /&lt;script&gt;危険&lt;\/script&gt;/);
const unsafeDigestHtml = analysisHtml({ watchChannels: '<img src=x onerror=alert(1)>' }, { titles: [] });
assert.doesNotMatch(unsafeDigestHtml, /<img src=x onerror=alert\(1\)>/, '監視数をHTMLとして解釈させない');
assert.match(unsafeDigestHtml, /<b>0<\/b> 監視中/);
const pendingHtml = analysisHtml({}, { titles: [
  { videoId: 'measured', channelName: '計測済', title: '済', speed: 5, totalViews: 10 },
  { videoId: 'pending', channelName: '計測前', title: '待ち', speed: null, totalViews: 999 }
] });
assert.ok(pendingHtml.indexOf('計測済') < pendingHtml.indexOf('計測前'), '計測前動画は計測済み順位の後ろへ置く');
assert.match(pendingHtml, /計測中/, '計測前でも一覧から消さない');

// GAS: 同日の複数取得を1日にまとめ、欠測日数で割った1日平均と最新総再生数を返す。
const gasSource = fs.readFileSync(path.join(__dirname, '..', 'gas', '競合.gs'), 'utf8');
const context = {
  console,
  Session: { getScriptTimeZone() { return 'Asia/Tokyo'; } },
  Utilities: {
    formatDate(value) {
      const d = value instanceof Date ? value : new Date(value);
      return d.toISOString().slice(0, 10);
    },
    sleep() {}
  }
};
vm.createContext(context);
vm.runInContext(gasSource, context, { filename: '競合.gs' });

function makeSheet(headers, rows) {
  const all = [headers].concat(rows);
  return {
    getLastRow() { return all.length; },
    getLastColumn() { return headers.length; },
    getRange(row, col, numRows, numCols) {
      return {
        getValues() {
          return all.slice(row - 1, row - 1 + numRows).map(r => r.slice(col - 1, col - 1 + numCols));
        }
      };
    }
  };
}
function mapHeaders(sheet) {
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const out = {};
  headers.forEach((h, i) => { out[h] = i + 1; });
  return out;
}
const now = new Date();
const day3 = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
const day2 = new Date(day3.getTime() - 86400000);
const day1 = new Date(day3.getTime() - 2 * 86400000);
const iso = d => d.toISOString().slice(0, 10);
const published = new Date(day1.getTime() - 86400000).toISOString();
const vidHeaders = ['video_id', 'channel_id', 'タイトル', '公開日時', '長さ秒', 'isShort', '初回取得日'];
const chHeaders = ['channel_id', 'チャンネル名', 'URL', '登録者数', '総再生数', '動画数', '状態', '発見経路', 'uploads', '追加日', '最終更新', 'Bluesky', 'X', '訴求メモ'];
const dailyHeaders = ['日付', 'video_id', 'channel_id', '再生数', '高評価', 'コメント数'];
const sheets = {
  '競合_動画': makeSheet(vidHeaders, [
    ['vid-a', 'chan-a', '題名A', published, 30, 'yes', iso(day1)],
    ['vid-b', 'chan-b', '題名B', published, 40, 'yes', iso(day1)],
    ['vid-c', 'chan-c', '題名C', published, 50, 'yes', iso(day1)]
  ]),
  '競合_チャンネル': makeSheet(chHeaders, [
    ['chan-a', 'チャンネルA', '', 1234, '', '', 'watch', '', '', '', '', '', '', ''],
    ['chan-b', 'チャンネルB', '', '', '', '', 'watch', '', '', '', '', '', '', ''],
    ['chan-c', 'チャンネルC', '', 3000, '', '', 'watch', '', '', '', '', '', '', '']
  ]),
  '競合_日次': makeSheet(dailyHeaders, [
    [new Date(day1), 'vid-a', 'chan-a', 100, 0, 0],
    [iso(day1), 'vid-a', 'chan-a', 150, 0, 0],
    [iso(day3), 'vid-a', 'chan-a', 350, 0, 0],
    [iso(day2), 'vid-b', 'chan-b', 500, 0, 0],
    [iso(day3), 'vid-b', 'chan-b', 700, 0, 0],
    [iso(day3), 'vid-c', 'chan-c', 900, 0, 0]
  ])
};
context.compSheet_ = name => sheets[name];
context.headerMap_ = mapHeaders;
const result = context.compTitles_(30, 20);
assert.equal(result.titles[0].videoId, 'vid-b');
assert.equal(result.titles[0].speed, 200);
assert.equal(result.titles[0].totalViews, 700);
assert.equal(result.titles[0].channelName, 'チャンネルB');
assert.equal(result.titles[0].subscriberCount, null, '登録者数非公開を0と誤認しない');
assert.equal(result.titles[1].videoId, 'vid-a');
assert.equal(result.titles[1].speed, 100, '2日間で+200を+100/日に正規化する');
assert.equal(result.titles[1].measurementDays, 2);
assert.equal(result.titles[1].totalViews, 350, '同日後勝ちの最新総再生数を返す');
assert.equal(result.titles[1].subscriberCount, 1234);
assert.equal(result.titles[2].speed, null, '1日分だけなら計測中にする');
assert.deepEqual(
  ['title', 'isShort', 'speed', 'features'].filter(k => Object.hasOwn(result.titles[0], k)),
  ['title', 'isShort', 'speed', 'features'],
  '既存のcomp_titles契約を維持する'
);
// YouTube側で登録者数が非公開へ変わった場合、古い登録者数を残さないための判定を返す。
context.ytApiKey_ = () => 'test-key';
context.compQuotaAdd_ = () => true;
context.UrlFetchApp = {
  fetch() {
    return {
      getResponseCode() { return 200; },
      getContentText() {
        return JSON.stringify({
          items: [{
            id: 'chan-hidden',
            snippet: { title: '非公開チャンネル' },
            statistics: { hiddenSubscriberCount: true, viewCount: '321', videoCount: '7' },
            contentDetails: { relatedPlaylists: { uploads: 'uploads-hidden' } }
          }]
        });
      }
    };
  }
};
const hiddenChannel = context.ytChannels_(['chan-hidden'])['chan-hidden'];
assert.equal(hiddenChannel.subs, null);
assert.equal(hiddenChannel.hiddenSubs, true);
assert.equal(hiddenChannel.name, '非公開チャンネル');

// 日次更新では非公開へ変わった登録者数セルを空欄に戻し、古い値を残さない。
const updatedCells = [];
const channelUpdateSheet = {
  getLastRow() { return 2; },
  getLastColumn() { return chHeaders.length; },
  getRange(row, col) {
    return { setValue(value) { updatedCells.push({ row, col, value }); } };
  }
};
const emptyVideoSheet = {
  getLastRow() { return 1; },
  getLastColumn() { return vidHeaders.length; }
};
const emptyDailySheet = { getLastRow() { return 1; } };
context.compWatchChannels_ = () => [{ channelId: 'chan-hidden', rowIndex: 2, uploads: '' }];
context.compSheet_ = name => name === '競合_チャンネル' ? channelUpdateSheet :
  (name === '競合_動画' ? emptyVideoSheet : emptyDailySheet);
context.headerMap_ = sheet => sheet === channelUpdateSheet ? mapHeaders(makeSheet(chHeaders, [])) : mapHeaders(makeSheet(vidHeaders, []));
context.ytChannels_ = () => ({
  'chan-hidden': { name: '非公開チャンネル', subs: null, hiddenSubs: true, views: 321, videos: 7, uploads: '' }
});
context.ytVideosMeta_ = () => ({});
context.compUpsertVideos_ = () => {};
context.ytVideosStats_ = () => ({});
const dailyRun = context.runCompetitorDaily();
assert.equal(dailyRun.ok, true);
assert.ok(updatedCells.some(cell => cell.col === 4 && cell.value === ''), '非公開へ変わった登録者数セルを空欄にする');
console.log('PASS: competitor top20 / channel metrics / normalized daily growth');