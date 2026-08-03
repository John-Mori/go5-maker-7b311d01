/**
 * tests/test_sync_coverage.js — 同期方針カバレッジ検査(PDCAの機構化・Chami依頼2026-08-04)
 *
 * 【解く問題】「言われてから同期に載せる」を繰り返していた=新機能でlocalStorageキーを足しても、
 *   それを端末間で共有すべきか(sync)/端末ローカルでよいか(local)/秘密か(secret)を誰も判定せず、
 *   Chamiがバグとして踏むまで同期漏れが見えなかった。
 *
 * 【機構】全JSを走査してlocalStorageキーを洗い出し、scripts/sync_decisions.json に
 *   「決定つき」で載っているか＋その決定が実際の同期ゲート(sync.jsのisSyncLsKey / storage-keysのisSecret)と
 *   一致するかを検査する。新キーは台帳へ1行足さないと落ちる=足す時に必ず同期方針を決めさせる。
 *
 * 実行: node tests/test_sync_coverage.js
 */
"use strict";
var fs = require("fs"), path = require("path");
var Keys = require("../core/storage-keys.js");
var Sync = require("../core/sync.js")._test;
var ROOT = path.join(__dirname, "..");
var ledger = JSON.parse(fs.readFileSync(path.join(ROOT, "scripts", "sync_decisions.json"), "utf8")).keys;

var fails = 0, checks = 0;
function fail(msg) { fails++; console.log("❌ " + msg); }
function ok() { checks++; }

// ── アプリのJSを走査(worker/schedule/tests/node_modules は対象外=別ランタイム) ──
function listJs(dir, acc) {
  fs.readdirSync(dir, { withFileTypes: true }).forEach(function (e) {
    var p = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (/^(node_modules|tests|schedule|\.git)$/.test(e.name)) return;
      if (/-worker$/.test(e.name) || e.name === "drive-worker") return; // Cloudflare Worker=別localStorage無し
      listJs(p, acc);
    } else if (/\.js$/.test(e.name)) acc.push(p);
  });
  return acc;
}
var reLit = /localStorage\.(?:setItem|getItem|removeItem)\(\s*['"]([a-zA-Z0-9_]+)['"]/g;
var reDyn = /['"]([a-zA-Z0-9_]+_)['"]\s*\+\s*(?:acct|acc|acctId|getCurrentAccount|current)/g;
var found = {};
listJs(ROOT, []).forEach(function (f) {
  var t = fs.readFileSync(f, "utf8"), m;
  while ((m = reLit.exec(t))) found[m[1]] = 1;
  while ((m = reDyn.exec(t))) found[m[1] + "<acc>"] = 1;
});
// 正規化: 末尾 "__" を "__<acc>" へ(アカウント別キーの表記統一)。ノイズ(短すぎ/裸の "__")は捨てる。
var keys = {};
Object.keys(found).forEach(function (k) {
  if (k === "__<acc>" || k === "__" || k.replace(/<acc>/, "").length < 3) return;
  keys[k.replace(/__$/, "__<acc>")] = 1;
});

// ── 各キー: 台帳に決定があり、実ゲートと一致するか ──
function sampleOf(k) { return k.replace(/<acc>/g, "acc1"); }
function realDecision(sample) {
  if (Keys.isSecret(sample)) return "secret";
  // 実ブラウザのゲート isSyncLsKey は「sync.js内の直書きリスト OR Keys.syncAllowed」。Nodeでは sync.js から
  //   window.Go5Keys が見えず後者が効かないため、ここで Keys.syncAllowed を明示ORして本番と同じ判定に戻す。
  return (Sync.isSyncLsKey(sample) || Keys.syncAllowed(sample)) ? "sync" : "local";
}
Object.keys(keys).sort().forEach(function (k) {
  var dec = ledger[k];
  if (!dec) { fail("台帳に未登録のキー: '" + k + "' — scripts/sync_decisions.json へ {decision: sync|local|secret, why} を追記して同期方針を決めること"); return; }
  ok();
  var real = realDecision(sampleOf(k));
  if (dec.decision !== real) {
    fail("キー '" + k + "': 台帳の決定=" + dec.decision + " だが実際の同期ゲート=" + real +
      " — 決定が sync なら storage-keys.js/sync.js の許可リストへ、local/secret ならゲートから外すこと(不一致=同期漏れ or 意図せぬ同期)");
  }
  if (!dec.why || !String(dec.why).trim()) fail("キー '" + k + "': 理由(why)が空");
});

// ── 台帳にあるが走査で見つからないキー=陳腐化の可能性(動的生成キーは正常なので警告のみ) ──
var stale = Object.keys(ledger).filter(function (k) { return !keys[k]; });
if (stale.length) console.log("ⓘ 台帳にあるが今回の走査で未検出(動的生成キーなら正常): " + stale.join(", "));

console.log("\n" + (fails ? "❌ " + fails + " FAIL / " : "✅ ALL PASS  (") + checks + (fails ? " checked" : " keys checked)"));
if (fails) process.exit(1);
