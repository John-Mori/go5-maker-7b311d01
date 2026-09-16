#!/usr/bin/env node
/**
 * bump.mjs — フロントHTMLの `?v=N` を一括バンプする(全部門共通・手動sedの置換)。
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
 * 対象: アセット参照(?v=)を持つフロントHTML=index.html + 分割ページ(候補/分析ランキング/ドラフト/投稿履歴)。
 *   ★分割ページ(KouhoLists.html / analytics.html / Stock.html / StockLists.html)も index.html と
 *     同じ ?v= を共有するため対象に含める(2026-08-11 別ページ化・2026-08-16 投稿履歴を StockLists.html へ分離)。
 *     ★ここに足し忘れると分割ページだけ古いJSがキャッシュされ静かに事故る(=CIスモークが版混在でfail)。
 *
 * ★取り残し検出(2026-09-16 AD研究室モドリッチの計測を受けて追加):
 *   「全参照が同一N」だけを見る混在チェックは、揃った瞬間に検出力が0になる
 *   (index.htmlを触らないコミットでJSだけ変えると、混在すら起きず静かに取り残す)。
 *   → `.bump_state.json` に「直近バンプの起点commit」を焼き、--check のたびに
 *      その起点からHEADまでの間で参照アセットが変更されていないかを見る(git diffで実測)。
 *      混在の有無に関係なく毎回効く=揃えても検出力は落ちない。
 */
import { readFileSync, writeFileSync, existsSync, readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
// ?v= を持つフロントHTMLを全部対象にする(将来ページが増えてもここへ足す)。
// ★次の配列(名前リテラル)が「バンプ対象=正本」。孤児検出(下)も vermix_foresight.py もここ1本を読む
//   =二重管理を作らない。vermix はこの宣言を正規表現で読むので、宣言の書式(名前=角括弧の配列リテラル)は崩さない。
const TARGETS = ["index.html", "KouhoLists.html", "analytics.html", "Stock.html", "StockLists.html"];
const TARGET_PATHS = TARGETS
  .map((f) => join(ROOT, f))
  .filter((p) => existsSync(p)); // 存在するものだけ実処理の対象にする
const RE = /\?v=(\d+)/g;
const HAS_VER = /\?v=\d+/; // 存在判定用(RE は /g で lastIndex を持つため test には使わない)

const argv = process.argv.slice(2);
const check = argv.includes("--check");
const toIdx = argv.indexOf("--to");
const explicit = toIdx >= 0 ? parseInt(argv[toIdx + 1], 10) : null;

if (!TARGET_PATHS.length) {
  console.error("対象HTMLが1つも見つからない。ROOT を間違えている可能性がある: " + ROOT);
  process.exit(2);
}

// ★孤児検出(2026-08-23 案2=single-source-predicate / AD研究室の下り②。移植元=scripts/kaizen/vermix_foresight.py):
//   リポジトリ直下(GitHub Pagesの配信ルート)に ?v= を持つHTMLが在るのに TARGETS 配列 に無い=
//   バンプ対象外で古いJSが配られ続ける「孤児」。TARGETS 配列 への追記を忘れると bump も --check も
//   素通りし、CI配信版全一致スモークが約20分後に赤で初めて気付く(上の L22-23 が自認する既知の穴)。
//   → その載せ忘れを bump の入口で止める=判定を一本化(bump本走・--check・CI・デプロイが全部この1本を見る)。
//   スコープは「直下のルートHTMLのみ」= schedule/ 等のサブディレクトリは別サブシステム(.verstamp で別管理)なので対象外。
//   判定は「孤児を検出したら止める」だけ(勝手に TARGETS 配列 へ足して自動バンプはしない=バンプ対象かは人間判断へ回す・過検知は止める方向へ倒す)。
const orphans = readdirSync(ROOT)
  .filter((name) => name.endsWith(".html") && !TARGETS.includes(name))
  .filter((name) => HAS_VER.test(readFileSync(join(ROOT, name), "utf8")));
if (orphans.length) {
  console.error(`⚠ 孤児(TARGETS 外なのに ?v= を持つ直下HTML)= ${orphans.length}件: ${orphans.join(", ")}`);
  console.error("  バンプ対象外=このページだけ古いJSが配られ続け、CI配信版全一致スモークが約20分後に赤になる。その前に止めた。");
  console.error("  対処①この版が本当にバンプ対象なら scripts/bump.mjs の TARGETS 配列へ追記する(人間判断)。");
  console.error("  対処②配信面でない(退役・作業用)なら直下から移す。--check でも同じ判定で止まる。");
  process.exit(8);
}

// 全対象ファイルの ?v= を横断で集める(混在検出は「全ファイル通し」で行う=CIスモークと同じ観点)。
const files = TARGET_PATHS.map((path) => {
  const src = readFileSync(path, "utf8");
  const nums = [...src.matchAll(RE)].map((m) => parseInt(m[1], 10));
  return { path, src, nums };
});
const found = files.flatMap((f) => f.nums);

if (!found.length) {
  console.error("?v= の参照が1つも無い。対象を間違えている可能性がある: " + TARGET_PATHS.join(", "));
  process.exit(2);
}

const uniq = [...new Set(found)].sort((a, b) => a - b);
const cur = uniq[uniq.length - 1];

// ★取り残し検出: 全参照が同一Nでなければ、過去のバンプが取り残している(=古いアセットが配られ続けている)。
//   バンプ前に必ず気付けるようにする。--to での強制統一が復旧手段。
if (uniq.length > 1) {
  console.error(`⚠ ?v= が混在している: ${uniq.join(", ")} (参照 ${found.length} 箇所 / ${files.length} ファイル)`);
  console.error("  過去のバンプが取り残している=古いアセットがキャッシュされ続けている恐れ。");
  if (!explicit) {
    console.error(`  復旧: node scripts/bump.mjs --to ${cur + 1}  (全参照を強制的に揃える)`);
    process.exit(3);
  }
}

// ★取り残し検出: 直近バンプの起点(.bump_state.json)からHEADまでの間で、
//   参照アセット(src/href の ?v= 付きパス)が変更されていないかを見る。
//   混在チェック(uniq.length>1)と違い、揃っていても常に効く=検出力が0にならない。
const STATE_PATH = join(ROOT, ".bump_state.json");
function detectStaleAssets() {
  if (!existsSync(STATE_PATH)) return null; // 初回導入前=判定材料なし(赤にしない)
  let state;
  try {
    state = JSON.parse(readFileSync(STATE_PATH, "utf8"));
  } catch {
    return null; // 壊れたstateで検査を止めない(fail-open)
  }
  if (!state.base_commit) return null;

  const ASSET_RE = /(?:src|href)="([^"?]+)\?v=\d+"/g;
  const assetPaths = new Set();
  for (const f of files) {
    let m;
    ASSET_RE.lastIndex = 0;
    while ((m = ASSET_RE.exec(f.src))) assetPaths.add(m[1]);
  }

  const diff = spawnSync("git", ["diff", "--name-only", state.base_commit, "HEAD"], { cwd: ROOT, encoding: "utf8" });
  if (diff.status !== 0) return null; // 起点commitがもう無い(履歴書き換え等)=fail-open、混在チェックに任せる
  const changed = new Set(diff.stdout.split("\n").map((s) => s.trim()).filter(Boolean));

  return [...assetPaths].filter((p) => changed.has(p)).sort();
}

if (check) {
  console.log(`現在 v=${cur} / 参照 ${found.length} 箇所 / ${files.length} ファイル / 混在 ${uniq.length > 1 ? "あり:" + uniq.join(",") : "なし"}`);
  const stale = detectStaleAssets();
  if (stale && stale.length) {
    console.error(`⚠ 中身が変わったのに ?v= が据え置きの疑い= ${stale.length}件: ${stale.join(", ")}`);
    console.error("  直近バンプの起点以降にこれらが変更された。node scripts/bump.mjs でバンプすること。");
    process.exit(9);
  }
  console.log("V=" + cur);
  process.exit(0);
}

const next = explicit != null && !Number.isNaN(explicit) ? explicit : cur + 1;
if (next <= cur && explicit == null) {
  console.error(`次の版数(${next})が現在(${cur})以下。中止する。`);
  process.exit(4);
}

// 全ファイルを検証してから書く(1ファイルでも壊れたら全部書かない=中途半端な混在を作らない)。
const writes = [];
for (const f of files) {
  const out = f.src.replace(RE, `?v=${next}`);
  const after = [...out.matchAll(RE)].map((m) => parseInt(m[1], 10));
  const bad = after.filter((n) => n !== next);
  if (bad.length) {
    console.error(`置換後に不一致が残った(${f.path}: ${bad.length}箇所)。書き込みを中止する。`);
    process.exit(5);
  }
  if (after.length !== f.nums.length) {
    console.error(`参照数が変化した(${f.path}: ${f.nums.length} → ${after.length})。書き込みを中止する。`);
    process.exit(6);
  }
  writes.push({ path: f.path, out, count: after.length });
}

for (const w of writes) writeFileSync(w.path, w.out);
const total = writes.reduce((s, w) => s + w.count, 0);
console.log(`v=${cur} → v=${next} (${total} 箇所 / ${writes.length} ファイルを更新)`);

// ★恒久(C-038 2026-08-12): 本体版を上げたら schedule/(カレンダーiframe)の verstamp も同じ入口で焼き直す。
//   これまで schedule/ の版上げ後に `check_schedule_ver.mjs --stamp` を手で打ち忘れ、CIの
//   「schedule版ずれ門」が緑→赤になる焼き直し漏れが再発していた(HQ実測2026-08-11・run 31505669288系)。
//   bump を1コマンドの入口にして「版を上げたら自動で焼く」を機構化する。
//   ・schedule資産が無変更 → 同一内容を焼き直すだけ(差分ゼロ・無害)。
//   ・schedule資産を変えたのに ?v= 据え置き → --stamp が exit 1 で止める=CIの20分後ではなく
//     bump の瞬間に気付ける(=先に schedule/index.html の版を上げてくれ、というCIと同じ指示)。
const stampScript = join(dirname(fileURLToPath(import.meta.url)), "check_schedule_ver.mjs");
if (existsSync(stampScript)) {
  const r = spawnSync(process.execPath, [stampScript, "--stamp"], { encoding: "utf8" });
  if (r.stdout) process.stdout.write(r.stdout);
  if (r.stderr) process.stderr.write(r.stderr);
  if (r.status !== 0) {
    console.error("⚠ schedule/ の verstamp 焼き直しに失敗(schedule資産を変えたのに ?v= が据え置きの可能性)。");
    console.error("  本体の ?v= は上げ済み。上の指示どおり schedule/index.html の版を上げてから再実行すること。");
    process.exit(7);
  }
  console.log("↳ schedule/.verstamp.json も焼き直した(差分があれば同じコミットに含めること)");
}

// ★取り残し検出の起点を焼く: 今バンプした瞬間のHEADを「ここまでは検査済み」の基準にする。
//   次回 --check はこの起点からの差分だけを見るので、今回同梱コミットで動く参照アセット変更は
//   まだ「起点より前」=誤検知しない(起点はこのバンプ実行時点のHEAD=これから積むコミットの親)。
const headRev = spawnSync("git", ["rev-parse", "HEAD"], { cwd: ROOT, encoding: "utf8" });
if (headRev.status === 0) {
  const baseCommit = headRev.stdout.trim();
  writeFileSync(STATE_PATH, JSON.stringify({ base_commit: baseCommit, bumped_to: next, bumped_at: new Date().toISOString() }, null, 2) + "\n");
  console.log(`↳ .bump_state.json を焼いた(起点=${baseCommit.slice(0, 7)})`);
} else {
  console.error("⚠ git rev-parse HEAD に失敗。.bump_state.json は更新しなかった(取り残し検出が次回働かない可能性)。");
}
console.log("V=" + next);
