#!/usr/bin/env node
/**
 * bump.mjs — index.html の `?v=N` を一括バンプする(全部門共通・手動sedの置換)。
 *
 * なぜ要るか(2026-07-17 改修αの実体験):
 *   並行セッションが常態化したため、手動 `sed -i 's/?v=342/?v=343/g'` は衝突装置になった。
 *   実際に、別セッションが未コミットで342へ上げていたのを知らずに私が343を打ち、相手へ
 *   「344へ再バンプしてくれ」と要求する事態になった。さらに sed は「置換前の値」を人が
 *   手で指定するため、**現在値を1つでも読み違えると取り残しが出て静かに事故る**
 *   (=古いJSがキャッシュされ、修正が届かない)。
 *   → 現在値を「ファイルから検出」し、「全参照が同一Nであること」を検証してから+1する。
 *      どのセッションから実行しても、その瞬間のディスク状態を基準にするので衝突しない。
 *
 * 使い方:
 *   node scripts/bump.mjs              # 現在値+1へ一括バンプ
 *   node scripts/bump.mjs --check      # 変更せず現在値と参照数だけ表示
 *   node scripts/bump.mjs --to 350     # 明示指定(通常は使わない・復旧用)
 *
 * 出力: 新しい版数を最終行に `V=<N>` で出す(スクリプトから拾えるように)。
 * 対象: index.html のみ(アセット参照の正本。他HTMLは参照を持たない)。
 */
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const TARGET = join(ROOT, "index.html");
const RE = /\?v=(\d+)/g;

const argv = process.argv.slice(2);
const check = argv.includes("--check");
const toIdx = argv.indexOf("--to");
const explicit = toIdx >= 0 ? parseInt(argv[toIdx + 1], 10) : null;

const src = readFileSync(TARGET, "utf8");
const found = [...src.matchAll(RE)].map((m) => parseInt(m[1], 10));

if (!found.length) {
  console.error("?v= の参照が1つも無い。対象を間違えている可能性がある: " + TARGET);
  process.exit(2);
}

const uniq = [...new Set(found)].sort((a, b) => a - b);
const cur = uniq[uniq.length - 1];

// ★取り残し検出: 全参照が同一Nでなければ、過去のsedが失敗している(=一部が古いまま配られている)。
//   バンプ前に必ず気付けるようにする。--to での強制統一が復旧手段。
if (uniq.length > 1) {
  console.error(`⚠ ?v= が混在している: ${uniq.join(", ")} (参照 ${found.length} 箇所)`);
  console.error("  過去のバンプが取り残している=古いアセットがキャッシュされ続けている恐れ。");
  if (!explicit) {
    console.error(`  復旧: node scripts/bump.mjs --to ${cur + 1}  (全参照を強制的に揃える)`);
    process.exit(3);
  }
}

if (check) {
  console.log(`現在 v=${cur} / 参照 ${found.length} 箇所 / 混在 ${uniq.length > 1 ? "あり:" + uniq.join(",") : "なし"}`);
  console.log("V=" + cur);
  process.exit(0);
}

const next = explicit != null && !Number.isNaN(explicit) ? explicit : cur + 1;
if (next <= cur && explicit == null) {
  console.error(`次の版数(${next})が現在(${cur})以下。中止する。`);
  process.exit(4);
}

const out = src.replace(RE, `?v=${next}`);
const after = [...out.matchAll(RE)].map((m) => parseInt(m[1], 10));
const bad = after.filter((n) => n !== next);
if (bad.length) {
  console.error(`置換後に不一致が残った(${bad.length}箇所)。書き込みを中止する。`);
  process.exit(5);
}
if (after.length !== found.length) {
  console.error(`参照数が変化した(${found.length} → ${after.length})。書き込みを中止する。`);
  process.exit(6);
}

writeFileSync(TARGET, out);
console.log(`v=${cur} → v=${next} (${after.length} 箇所を更新)`);
console.log("V=" + next);
