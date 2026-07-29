#!/usr/bin/env node
// check_click_recon.mjs — クリック(導線1/導線2)集計の不変条件をCIで固定する門。
//
// 背景(2026-07-30 朝レビュー): 直近24hで最も往復した型は「クリック計測/累計/整合の"データの流れ"」だった。
//   短縮コードが差し替わると日次スナップのカウンタが0起点に戻り、
//     ・累計(r2 KV・現コード)=0 なのに 週=8   (Chami「いつも助かってます」)
//     ・週デルタ = cur - baseline が負に   (Chami「先週-16」)
//   という矛盾が繰り返しChamiから再報告された。gas/コード.gs computeDeltas_ に段差検出の
//   「積み直し(reconMonotonic_)」を入れて解消したが、GASはCIで実行できない。
//   ここに同一ロジックのミラーを置き、不変条件をfixtureで固定して"静かな回帰"を止める。
//   ★変更時は gas/コード.gs computeDeltas_ の reconMonotonic_/calc と両方を揃える(test_record_upsert.js と同じ流儀)。
//
// 不変条件(クリック列 c/w のみ。再生数vはYouTube下方修正で正当に減るため対象外):
//   (1) 週デルタは負にならない          週 = cur - baseline ≥ 0
//   (2) 累計は週デルタを内包する         累計 ≥ 週
//   (3) 積み直し後の系列は単調非減少

// ---- gas/コード.gs computeDeltas_ のミラー(純粋ロジック) ----
function reconMonotonic(m, dates, k) {
  let carry = 0, prevRaw = null;
  for (const d of dates) {
    const raw = m[d][k];
    if (raw == null) continue;
    if (prevRaw != null && raw < prevRaw) carry += prevRaw; // コード差し替え=旧コード最終値を土台に繰上げ
    m[d][k] = raw + carry;
    prevRaw = raw;
  }
}
function lastNonNull(m, dates, k, ds, inclusive) {
  let best = null;
  for (const d of dates) {
    const ok = inclusive ? (d <= ds) : (d < ds);
    if (ok && m[d][k] != null) best = m[d][k];
  }
  return best;
}
// today/wk を引数で受ける(Date.now非依存=決定的テスト)。
function calc(m, dates, k, today, wk) {
  const cellToday = m[today];
  let cur = (cellToday && cellToday[k] != null) ? cellToday[k] : lastNonNull(m, dates, k, '9999-99-99', true);
  if (cur == null) return { week: null, cum: null };
  let bW = lastNonNull(m, dates, k, wk, true); if (bW == null) bW = 0;
  return { week: cur - bW, cum: cur };
}

function analyze(series, today, wk) {
  // series: [{date, c, w}] を m へ
  const m = {}; const dates = [];
  for (const r of series) { m[r.date] = { c: r.c ?? null, w: r.w ?? null }; dates.push(r.date); }
  dates.sort();
  reconMonotonic(m, dates, 'c'); reconMonotonic(m, dates, 'w');
  return {
    c: calc(m, dates, 'c', today, wk),
    w: calc(m, dates, 'w', today, wk),
    reconSeries: dates.map(d => ({ date: d, c: m[d].c, w: m[d].w })),
  };
}

// ---- fixtures: Chamiが実際に報告した2ケースを再現 ----
const FIX = [
  {
    name: '導線2の短縮コード差し替え(先週-16の再現)',
    // w列: 7日前16 → 途中で新コードに差し替わり0起点 → 3まで伸びた
    series: [
      { date: '2026-07-22', w: 16 },
      { date: '2026-07-24', w: 16 },
      { date: '2026-07-28', w: 0 },
      { date: '2026-07-30', w: 3 },
    ],
    today: '2026-07-30', wk: '2026-07-23',
    col: 'w',
  },
  {
    name: '累計0なのに週8(いつも助かってますの再現)',
    series: [
      { date: '2026-07-22', w: 8 },
      { date: '2026-07-25', w: 8 },
      { date: '2026-07-29', w: 0 },
      { date: '2026-07-30', w: 0 },
    ],
    today: '2026-07-30', wk: '2026-07-23',
    col: 'w',
  },
  {
    name: '導線1でも同様(差し替え後も週≥0・累計≥週)',
    series: [
      { date: '2026-07-23', c: 30 },
      { date: '2026-07-27', c: 5 },   // コード差し替えで0起点付近へ
      { date: '2026-07-30', c: 12 },
    ],
    today: '2026-07-30', wk: '2026-07-23',
    col: 'c',
  },
];

let failed = 0;
for (const f of FIX) {
  const r = analyze(f.series, f.today, f.wk);
  const res = r[f.col];
  const errs = [];
  // (1) 週は負にならない
  if (res.week != null && res.week < 0) errs.push(`週デルタが負: ${res.week}`);
  // (2) 累計 ≥ 週
  if (res.cum != null && res.week != null && res.cum < res.week) errs.push(`累計<週: 累計${res.cum} < 週${res.week}`);
  // (3) 積み直し系列は単調非減少
  let prev = null;
  for (const s of r.reconSeries) {
    const v = s[f.col];
    if (v == null) continue;
    if (prev != null && v < prev) { errs.push(`積み直し後に減少: ${prev}→${v}`); break; }
    prev = v;
  }
  if (errs.length) { failed++; console.error(`NG [${f.name}] ${errs.join(' / ')}`); }
  else console.log(`OK [${f.name}] 週=${res.week} 累計=${res.cum}`);
}

if (failed) { console.error(`\nクリック集計の不変条件に違反 ${failed} 件。gas/コード.gs computeDeltas_ の積み直しが壊れていないか確認。`); process.exit(1); }
console.log('\nクリック集計の不変条件OK(週≥0 / 累計≥週 / 単調非減少)');
