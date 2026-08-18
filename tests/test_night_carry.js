// tests/test_night_carry.js
// 「深夜0〜3時の投稿は前日の深夜枠(24:xx〜27:xx)に属す」判定(js/yt-clicks.js dayBucketMin_)の回帰。
//   Chami依頼2026-08-18=「8/18の3時までに投稿したものは8/17に回す。8/18の投稿候補に出さない」。
// ★実ソースから dayBucketMin_ / ymdOf_ / NIGHT_CARRY_MAX_MIN を抜き出してそのまま eval する
//   =コピーではないので、本体を書き換えたら次回この検査が再評価する(空PASSにならない)。
process.env.TZ = "Asia/Tokyo"; // getHours() はJST端末前提。TZ固定で決定的にする。

const fs = require("fs");
const path = require("path");

const src = fs.readFileSync(path.join(__dirname, "..", "js", "yt-clicks.js"), "utf8");

function extract(re, label) {
  const m = re.exec(src);
  if (!m) throw new Error("抜き出し失敗: " + label + "(本体の該当関数が見つからない=定義名が変わった可能性)");
  return m[0];
}

const ymdSrc = extract(/function ymdOf_\(dObj\)\s*\{[\s\S]*?\n  \}/, "ymdOf_");
const bucketSrc = extract(/function dayBucketMin_\(ms, dateStr, includeNightCarry\)\s*\{[\s\S]*?\n  \}/, "dayBucketMin_");
const carrySrc = extract(/var NIGHT_CARRY_MAX_MIN = [^;]+;/, "NIGHT_CARRY_MAX_MIN");

const sandbox = {};
new Function(carrySrc + "\n" + ymdSrc + "\n" + bucketSrc +
  "\nthis.dayBucketMin_ = dayBucketMin_;").call(sandbox);
const dayBucketMin_ = sandbox.dayBucketMin_;

function ms(y, mo, d, h, mi) { return new Date(y, mo - 1, d, h, mi, 0).getTime(); }

let fail = 0;
function eq(actual, expected, label) {
  const ok = actual === expected;
  if (!ok) { fail++; console.error("FAIL " + label + " : 期待=" + expected + " 実際=" + actual); }
  else console.log("PASS " + label);
}

// 8/18 02:00 の投稿。
// ① 自分の暦日 8/18 の候補には出さない(=null)。← 今回の主眼
eq(dayBucketMin_(ms(2026, 8, 18, 2, 0), "2026-08-18", true), null, "8/18 02:00 は 8/18 の候補に出さない");
// ② 前日 8/17 の深夜枠には 26:00(=1560分) として出す。
eq(dayBucketMin_(ms(2026, 8, 18, 2, 0), "2026-08-17", true), 26 * 60, "8/18 02:00 は 8/17 に 26:00 として出す");
// ③ 境界=3:00ちょうども前日側(=8/18からは外す)。
eq(dayBucketMin_(ms(2026, 8, 18, 3, 0), "2026-08-18", true), null, "8/18 03:00 ちょうども 8/18 から外す");
eq(dayBucketMin_(ms(2026, 8, 18, 3, 0), "2026-08-17", true), 27 * 60, "8/18 03:00 は 8/17 に 27:00 として出す");
// ④ 境界超え=3:01 は当日の通常枠(181分)。前日には回さない。
eq(dayBucketMin_(ms(2026, 8, 18, 3, 1), "2026-08-18", true), 181, "8/18 03:01 は 8/18 に 03:01 として出す");
eq(dayBucketMin_(ms(2026, 8, 18, 3, 1), "2026-08-17", true), null, "8/18 03:01 は 8/17 には出さない");
// ⑤ 昼の投稿は従来どおり当日枠(変化なし)。
eq(dayBucketMin_(ms(2026, 8, 18, 14, 0), "2026-08-18", true), 14 * 60, "8/18 14:00 は 8/18 に 14:00");
// ⑥ night-carry 無効時は当日の深夜も当日枠(後方互換)。
eq(dayBucketMin_(ms(2026, 8, 18, 2, 0), "2026-08-18", false), 120, "carry無効時は 8/18 02:00 を当日に出す(後方互換)");

if (fail) { console.error("\n" + fail + " 件 FAIL"); process.exit(1); }
console.log("\nすべてPASS(test_night_carry)");
