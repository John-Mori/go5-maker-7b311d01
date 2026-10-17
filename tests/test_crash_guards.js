// iPhoneのタブが落ちる(メモリ・処理詰まり)原因を塞いだ箇所が、後の改修で元へ戻らないための番犬。
// (Chami msg 1561055385383862336「よくクラッシュするからクラッシュしないように…見た目や機能を変えないでメンテナンスして」)
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const repo = path.join(__dirname, '..');
const read = (f) => fs.readFileSync(path.join(repo, f), 'utf8');
const app = read('js/app.js'), bs = read('js/bluesky.js'), cand = read('js/candidates.js');
const yt = read('js/yt-clicks.js'), stock = read('js/stock.js');

// 投稿プレビュー: 同じ写真なら1文字ごとに作り直さない・隠す時は手放す
const show = bs.slice(bs.indexOf('  function showPreviewImage(file) {'), bs.indexOf('  // ---- プレビュー描画'));
assert(show.includes('file === lastImgFile'), '同じ写真ならObjectURLを作り直さない');
assert(/function hidePreviewImage\(\) \{[\s\S]*?revokeObjectURL\(lastImgUrl\)/.test(show), '隠す時にObjectURLを手放す');
assert(bs.includes('graphemeSeg_ || (graphemeSeg_ = new Intl.Segmenter'), '文字数カウントの分割器は使い回す');

// 動画作成: 文字入力の再描画は1フレームにまとめる・録画トラックと前回の完成URLを手放す
assert(app.includes('els.top.addEventListener("input", previewSoon_);'), '④コメント入力の再描画はまとめる');
assert(app.includes('els.author.addEventListener("input", previewSoon_);'), '作者入力の再描画はまとめる');
assert(!app.includes('els.top.addEventListener("input", preview);'), '④コメントで1キーごとの全面再描画へ戻さない');
assert(app.includes('stream.getTracks().forEach((t) => t.stop())'), '録画後にキャンバスの録画トラックを止める');
assert(/prevResultUrl[\s\S]{0,300}URL\.revokeObjectURL\(prevResultUrl\)/.test(app), '前回の完成動画URLを手放す');

// 候補一覧: 背景からの描き直しはまとめる・読めない時の再試行は間隔を広げる
assert(/function bgRender_\(\) \{\s*if \(_bgRenderTimer\) return;/.test(cand), '背景の全体描き直しは1回へまとめる');
assert(cand.includes('Math.min(60000, 1500 * Math.pow(2'), '同期画像の再読込の再試行は間隔を広げる');
assert(cand.includes('if (document.hidden) return; retryVisibleHistoryImages_(true);'), '裏に回っている間は30秒の再武装を止める');

// 投稿履歴: 投稿時刻の大きなJSONを項目ごとに解析し直さない
const hpt = yt.slice(yt.indexOf('  function historyPostTime_(it, ymap) {'), yt.indexOf('  function youtubePostTime_(rec) {'));
assert(hpt.includes('readHistoryPostTimes_()'), '読むだけの経路は解析結果を使い回す');
assert(!hpt.includes('loadHistoryPostTimes_()'), '項目ごとのJSON解析へ戻さない');

// ドラフト: 末尾コマ取得の一時videoを手放す
const vef = stock.slice(stock.indexOf('  function videoEndFramePreview_(blob) {'), stock.indexOf('  function blobToDataUrl_(blob, cb) {'));
assert(vef.includes("v.removeAttribute('src'); v.load();"), '一時videoのデコーダを手放す');

console.log('test_crash_guards: OK');
