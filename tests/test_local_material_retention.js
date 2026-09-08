"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");

function read(file) {
  return fs.readFileSync(path.join(__dirname, "..", file), "utf8");
}

const drafts = read("js/drafts.js");
const stock = read("js/stock.js");
const sync = read("core/sync.js");

assert.ok(drafts.includes("draftsource:"), "元画像を保持するIndexedDBキーが必要");
assert.ok(drafts.includes("stashSourceIdb_"), "元画像を保存して読み戻す処理が必要");
assert.ok(drafts.includes("loadSourceIdb_"), "元画像を復元する処理が必要");
assert.ok(!drafts.includes("MAX_DRAFTS"), "下書きの任意件数上限を置かない");
assert.ok(!/var\s+ARCHIVE_MAX\s*=/.test(stock), "作成履歴の任意件数上限を置かない");
assert.ok(!/var\s+MAX\s*=\s*20/.test(stock), "ドラフトの任意件数上限を置かない");
assert.ok(!stock.includes("dropped.forEach(function (m) { delBlobs_(m.id); })"), "件数超過で動画Blobを削除しない");
assert.ok(!sync.includes("slimStockArchive(finalV, 3)"), "同期で古いサムネイルを間引かない");

console.log("PASS: local material retention policy");
