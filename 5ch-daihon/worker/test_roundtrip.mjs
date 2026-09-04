// 5ch-daihon Worker: YAML round-trip でコメントが保全されることを検証する最小Nodeテスト。
// 実行: node test_roundtrip.mjs (このファイルと同じ場所に node_modules/yaml が要る = `npm i yaml` 済み)
//
// ★入力は test_fixture_cutlist.yaml (このテスト専用の新規フィクスチャ)を使う。実物の
//   local/5ch/projects/holodri_noel/holodri_noel_cutlist.yaml ではない理由=
//   実物の work.output フィールド(56行目)がダブルクォート文字列内で Windows パスの
//   バックスラッシュをエスケープせず書かれており(例 "D:\SougouStartFolder\...")、
//   YAML仕様上は不正なエスケープシーケンス(\S, \5, \l 等)になっている(既存データの
//   バグ・本テスト実装で見つけた・修正はスコープ外=既存ファイルを書き換えない)。
//   yamlパッケージの parseDocument はこれを doc.errors に積んで best-effort で読み進めるが、
//   doc.toString() は "Document with errors cannot be stringified" で例外を投げる。
//   → 実物データを使うと「本テストの対象外の既存バグ」でテストが落ちるため、同じ構造
//   (長大な冒頭/末尾コメント・cuts配列・notes)を持つ壊れていないフィクスチャで検証する。
//   ★この既存バグはREADMEにも明記した(Chami手番＝R2投入前に実物のcut_listを直す必要あり)。
//
// 検証内容:
//   1) フィクスチャを読み込む。
//   2) parseDocument→該当cutのcaption_textだけをsetInで書き換え→toString()で文字列化する
//      (= 5ch-daihon/worker/src/index.js の handleSaveField と同じ手順)。
//   3) 書き換え後のテキストに、冒頭コメント(露出注記・Chami裁定履歴)の目印文字列が残っていることを確認。
//   4) 書き換え対象フィールドの値が新しい値に変わっていることを確認。
//   5) 対照実験として、素朴な yaml.parse→yaml.stringify の往復ではコメントが消えることも示す
//      (= なぜDocument APIを使うかの根拠)。

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { parseDocument, parse, stringify } from "yaml";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC_PATH = path.resolve(__dirname, "test_fixture_cutlist.yaml");

let passCount = 0, failCount = 0;
function check(label, cond) {
  if (cond) { console.log("PASS: " + label); passCount++; }
  else { console.error("FAIL: " + label); failCount++; }
}

const originalText = readFileSync(SRC_PATH, "utf8");

// ── 1) Document API round-trip(= handleSaveField と同じ手順) ──
const doc = parseDocument(originalText);
const cutsNode = doc.get("cuts", true);
check("cuts配列が読める", !!(cutsNode && cutsNode.items && cutsNode.items.length > 0));

const idx = cutsNode.items.findIndex((item) => String(item.get("cut_id")) === "cut_001");
check("cut_001が見つかる", idx >= 0);

const NEW_VALUE = "【テスト】書き換え後のキャプション";
doc.setIn(["cuts", idx, "caption_text"], NEW_VALUE);
const rewritten = doc.toString();

// ── 2) 冒頭コメント(露出注記・裁定履歴)が保全されているか ──
const COMMENT_MARKERS = [
  "test_fixture_cutlist.yaml", // ファイル先頭コメントの1行目
  "露出注記",                    // 🐧さんの露出注記を模した目印
  "Chami裁定",                  // ヘッダコメント中のChami裁定への言及
];
for (const marker of COMMENT_MARKERS) {
  check("冒頭コメント保全: 「" + marker + "」が残っている", rewritten.includes(marker));
}

// 末尾のコメント(声の割り当てチェック等)も保全されているか。
check("末尾コメント保全: 「声の割り当てチェック」が残っている", rewritten.includes("声の割り当てチェック"));
check("末尾コメント保全: 「尺の受け入れ条件」が残っている", rewritten.includes("尺の受け入れ条件"));

// 他コマのnotes(コメントではなく値だが、setInの副作用で消えていないかの確認)。
check("cut_002のnotesが残っている", rewritten.includes("答え合わせ=これも残ること"));

// ── 3) 書き換え対象の値が実際に変わっているか ──
const docAfter = parseDocument(rewritten);
const cutsAfter = docAfter.get("cuts", true);
const cut001After = cutsAfter.items.find((item) => String(item.get("cut_id")) === "cut_001");
check("caption_textが新しい値になっている", cut001After && cut001After.get("caption_text") === NEW_VALUE);

// 書き換えていない他フィールド(narration_text)は変わっていないこと。
const originalDoc = parseDocument(originalText);
const cut001Before = originalDoc.get("cuts", true).items.find((item) => String(item.get("cut_id")) === "cut_001");
check(
  "narration_textは書き換えていない(不変)",
  cut001After.get("narration_text") === cut001Before.get("narration_text")
);

// ── 4) 対照実験: 素朴な parse→stringify はコメントを消す(= Document APIを使う根拠) ──
const naiveObj = parse(originalText);
const naiveText = stringify(naiveObj);
check(
  "対照実験: 素朴なparse→stringifyは冒頭コメントを消す(想定どおりの退行)",
  !naiveText.includes("露出注記")
);

console.log("");
console.log("=== 結果: PASS=" + passCount + " FAIL=" + failCount + " ===");
if (failCount > 0) process.exit(1);
