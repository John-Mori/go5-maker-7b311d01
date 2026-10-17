/**
 * core/movie-attrs-core.js — 動画カテゴリ自動チェックの「判定」の唯一の正本。(Go5MovieAttrsCore)
 *
 * 【解く問題】AIカテゴリの自動チェックが入らない不具合が、直しても別画面で再発した(2026-08-12 同夜5回)。
 *   真因= 同じ「AIか?」の判定式が 4 箇所にコピーされ、経路ごとに少しずつ食い違っていた：
 *     ①候補バッジ candidates.js isAiWork_(genres/floor/ai・全角ＡＩも半角化)
 *     ②候補→作成 bluesky.js applyGenres の aiHint(!!ai || genre/AI/ || floor/AI/・全角化なし)
 *     ③作品URLフェッチ bluesky.js autoApplyAttrsFromInfo_ の aiHint(!!ai || genre/AI/ のみ・floor/AI/なし)
 *     ④テスト tests/test_categories_ai.js が式を「再実装」(＝本物を検証していない=入れたが効かないの温床)
 *   ②③が違う=候補から飛んだ時とURL入力時でAI判定が別結果になり、片方でチェックが空振りしていた。
 *
 * 【対策】判定を本モジュール 1 本へ集約する。候補→作成 も 作品URLフェッチ も 候補バッジ も、必ず
 *   ここ(aiHint / resolve)を通す。テストも本物のここを直接叩く。＝2経路が式を持ち合って食い違う再発を
 *   機構で封じる(kaizen 実依頼 2026-08-13・Chami Go)。
 *
 * 依存: core/categories.js(Go5Cats)。matchText でキーワード部分一致、AI だけは開示文の少なさゆえ
 *   救済ヒント(aiHint)で補う。ブラウザ(window)と Node(module.exports)の両対応。
 */
(function (root) {
  'use strict';

  // 全角英字→半角(ＡＩ→AI)。FANZA のタグ/フロア表記ゆれで /AI/ が素通りするのを防ぐ。
  //   ★候補バッジ(candidates.js)と同一規則。以前は候補バッジだけが全角化しており、チェックボックス側は
  //   全角ＡＩを取りこぼしていた(バッジは AI・でもチェックは入らない、の食い違い)。ここで一本化する。
  function toHalfWidth(s) {
    return String(s == null ? '' : s).replace(/[Ａ-Ｚａ-ｚ]/g, function (c) { return String.fromCharCode(c.charCodeAt(0) - 0xFEE0); });
  }

  // ジャンル配列に緩く「AI」を含むか(全角ＡＩも半角化して判定)。
  function looseAiFromGenres(genres) {
    return (genres || []).some(function (g) { return /AI/i.test(toHalfWidth(g)); });
  }

  // 「この作品は AI 作品か?」の唯一の判定。優先度:
  //   1) worker が FANZA 必須開示文「AI生成」から立てた明示フラグ ai(genre/floor に AI が載らない同人AI用)
  //   2) genre タグに緩く AI(AI生成/AIイラスト 等)
  //   3) floor 名に AI(「コミック・AI」等・タグに載らずフロア名でしか示されない作品)
  //   ★title は英単語 "ai"(rainy/maid)を誤検出するため判定対象にしない。
  function aiHint(input) {
    input = input || {};
    return !!input.ai || looseAiFromGenres(input.genres) || /AI/i.test(toHalfWidth(input.floor));
  }

  // 「AIではない」と言い切れるか。workerの判定規則の版(aiRule)が今の版の確定falseだけを非AIとみなす。
  //   旧版(開示文「AI生成」だけ)は開示文を書かないAI作品(実測 d_709161)を非AIと確定していた=
  //   その古い false でAIチェックを外したり、候補を確認済みに凍結したりしない(2026-10-15 Chami報告①)。
  var AI_RULE = 2;
  function aiVerifiedFalse(info) {
    info = info || {};
    return !info.ai && !!info.aiChecked && Number(info.aiRule) === AI_RULE;
  }

  // カテゴリ判定に流す文字列群(ジャンル ∪ 作品名 ∪ フロア名 ∪ サービス名)。空文字は落とす。
  //   ★作品名も混ぜる=総集編は「総集編」タグが無く作品名にだけ載る作品が多いため(Chami依頼2026-08-06)。
  function composeTexts(input) {
    input = input || {};
    var genres = input.genres || [];
    return genres
      .concat(input.title ? [input.title] : [])
      .concat(input.floor ? [input.floor] : [])
      .concat(input.service ? [input.service] : []);
  }

  // 自動チェックの確定結果 {key:true, ...} を返す唯一の判定口。cats = Go5Cats。
  //   matchText でキーワード部分一致を取り、AI だけは救済ヒント(aiHint)で補って hits.ai を立てる。
  function resolve(input, cats) {
    input = input || {};
    var hits = (cats && cats.matchText) ? (cats.matchText(composeTexts(input)) || {}) : {};
    if (aiHint(input) && cats && cats.byKey && cats.byKey('ai')) hits.ai = true;
    return hits;
  }

  // 発売日 → 作品状態(新作=14日以内 / 準新作=90日以内 / 旧作)。唯一の正本。
  //   ★境目はFANZAの表示に合わせる=「新作 販売から14日以内 / 準新作 販売から15〜90日以内」(以前は30日で、FANZAが準新作と出す作品を新作と書いていた・Chami msg 1559935692459606080)。
  //   ★源を1本化(2026-08-13・C-038・Chami報告「新作判定が漏れる」)。以前 bluesky.js / candidates.js /
  //   yt-clicks.js に別実装があり、新作チェック(discountNew2)を実際に立てる bluesky.js版だけ日付パースが
  //     new Date(String(dateStr).replace(/\//g,'-'))  ← スラッシュ→ハイフンのみ・スペース区切りはそのまま
  //   だった。FANZA/DMM API の date は "YYYY-MM-DD HH:mm:ss"(スペース区切り・T無し)で来る=この非ISO形式は
  //   iOS Safari(WebKit)が Invalid Date にし(V8は寛容で気づけない)、isNaN→'' で新作でもチェックが立たず
  //   本文に「の新作」が入らなかった。candidates.js/yt-clicks.js は .replace(' ','T') で正規化済みだったが
  //   起点の bluesky.js だけ抜けていた。3経路をこの1本へ集約して食い違いを封じる(AIカテゴリと同型の恒久対策)。
  //   nowMs は試験用(省略時は現在時刻)。
  function deriveWorkState(dateStr, nowMs) {
    if (!dateStr) return '';
    var s = String(dateStr);
    var t = Date.parse(s.replace(' ', 'T'));         // "YYYY-MM-DD HH:mm:ss" を ISO(T区切り)へ正規化
    if (isNaN(t)) t = new Date(s.replace(/\//g, '-')).getTime(); // 保険:スラッシュ表記("YYYY/MM/DD")
    if (isNaN(t)) return '';
    var days = ((nowMs == null ? Date.now() : nowMs) - t) / 86400000;
    if (days <= 14) return '新作';
    if (days <= 90) return '準新作';
    return '旧作';
  }

  // 作品紹介の定型文(即アフィのコピペ欄・Blueskyドラフトの子投稿)。唯一の正本(Chami msg 1559480072589803612)。
  //   2行目: 新作=割引ありで「新作N%OFF✨️」・なし(定価)で「話題の新作✨️」/ 準新作=「準新作N%OFF✨️」「話題の準新作✨️」
  //   (定価は「話題の」を付ける・Chami msg 1559935014261620787)
  //   (準新作を新作と出さない・Chami msg 1559676496841539657)/ 旧作(発売日不明も)=「N%OFFの話題作✨️」「話題作✨️」。
  //   info は FANZA作品情報(releaseDate|date・discountPct・price・listPrice)。割引は定価>売価が分かる時はそれも満たす時だけ。
  var AFFI_POST_HEAD = '⇩気になった方はコチラから💕 #PR #漫画';
  function affiStatusLine(info, nowMs) {
    info = info || {};
    var ws = deriveWorkState(info.releaseDate || info.date || '', nowMs);
    var pct = Math.round(Number(info.discountPct || info.pct) || 0);
    if (pct > 0 && info.listPrice && info.price != null && !(Number(info.price) < Number(info.listPrice))) pct = 0;
    var fresh = (ws === '新作' || ws === '準新作');
    if (pct > 0) return fresh ? ws + pct + '%OFF✨️' : pct + '%OFFの話題作✨️';
    return fresh ? '話題の' + ws + '✨️' : '話題作✨️';
  }
  function affiPostText(info, link, nowMs) {
    var t = AFFI_POST_HEAD + '\n' + affiStatusLine(info, nowMs);
    return link ? t + '\n\n' + link : t;
  }
  // ドラフトの「子の文(返信)」=投稿本文(固定文)由来の文へ、見出し行の直後に2行目(新作/準新作/話題作)を差し込む。
  //   既に2行目があれば今の作品情報で置き換える。見出し行が無い文は触らない(null=差し込めなかった)。
  //   (Chami msg 1559679396363636736「ドラフトの子の文にも反映して」)
  var AFFI_STATUS_RE = /^(?:(?:話題の)?(?:新作|準新作)(?:\d+%OFF)?|(?:\d+%OFFの)?話題作)✨️?$/;
  function withAffiStatusLine(text, info, nowMs) {
    var lines = String(text == null ? '' : text).replace(/\r\n?/g, '\n').split('\n');
    for (var i = 0; i < lines.length; i++) {
      if (lines[i].trim().indexOf('⇩気になった方はコチラから') !== 0) continue; // 絵文字の異体(💕/💕️)や後ろのタグ違いでも拾う
      var st = affiStatusLine(info, nowMs);
      if (i + 1 < lines.length && AFFI_STATUS_RE.test(lines[i + 1].trim())) lines[i + 1] = st;
      else lines.splice(i + 1, 0, st);
      return lines.join('\n');
    }
    return null;
  }

  // 投稿モードの「子の文」を手で直した内容を、そのchの投稿本文(固定文)へ書き戻す形に戻す。
  //   子の文=本文(master)の短縮URL/プレースホルダ置換+見出し直後の2行目(新作/話題作)差し込み(=sys)。
  //   手で触っていない行は本文の元の行(プレースホルダのまま)、触った行は手の文(置換されたURLだけ本文側の表記へ戻す)。
  //   2行目の自動行は本文へ入れない。対応が取れない時は null(=書き戻さない)。
  //   (Chami msg 1561144626054955010「新しくドラフトで動画作ると元に戻る。戻らないようにして」)
  function childEditToMaster(master, sys, edited) {
    function split_(t) { return String(t == null ? '' : t).replace(/\r\n?/g, '\n').split('\n'); }
    function isHead_(l) { return String(l || '').trim().indexOf('⇩気になった方はコチラから') === 0; }
    function isSt_(l) { return AFFI_STATUS_RE.test(String(l || '').trim()); }
    var M = split_(master), S = split_(sys), E = split_(edited);
    var map = [], pairs = [], i = 0, j = 0;
    while (i < S.length) {
      if (j < M.length && S[i] === M[j]) { map.push(j); i++; j++; continue; }
      if (isSt_(S[i]) && i > 0 && isHead_(S[i - 1])) {
        if (j < M.length && isSt_(M[j])) { map.push(j); i++; j++; } else { map.push(-1); i++; }
        continue;
      }
      if (j >= M.length) return null;
      var a = M[j], b = S[i], p = 0, s = 0;
      while (p < a.length && p < b.length && a[p] === b[p]) p++;
      while (s < a.length - p && s < b.length - p && a[a.length - 1 - s] === b[b.length - 1 - s]) s++;
      var mt = a.slice(p, a.length - s), st = b.slice(p, b.length - s);
      if (/^(?:https?:\/\/)?[\w.-]+\.[a-z]{2,}\/\S+$/i.test(st)) pairs.push([st, mt]);
      map.push(j); i++; j++;
    }
    if (j !== M.length) return null;
    pairs.sort(function (x, y) { return y[0].length - x[0].length; });
    // E と S の行LCS(手で残した行=Sの行と一致)
    var n = E.length, m = S.length, dp = [], r, c;
    for (r = 0; r <= n; r++) { var row = []; for (c = 0; c <= m; c++) row.push(0); dp.push(row); }
    for (r = n - 1; r >= 0; r--) for (c = m - 1; c >= 0; c--) dp[r][c] = E[r] === S[c] ? dp[r + 1][c + 1] + 1 : Math.max(dp[r + 1][c], dp[r][c + 1]);
    var out = [];
    r = 0; c = 0;
    while (r < n) {
      if (c < m && E[r] === S[c]) { if (map[c] >= 0) out.push(M[map[c]]); r++; c++; continue; }
      if (c < m && dp[r][c + 1] >= dp[r + 1][c]) { c++; continue; } // Sの行が消された
      var line = E[r];
      if (isSt_(line) && out.length && isHead_(out[out.length - 1])) { r++; continue; } // 自動の2行目は手で変えても本文へ入れない(毎回作品情報で出し直す)
      pairs.forEach(function (pr) { line = line.split(pr[0]).join(pr[1]); });
      out.push(line); r++;
    }
    return out.join('\n');
  }

  var API = {
    childEditToMaster: childEditToMaster,
    withAffiStatusLine: withAffiStatusLine,
    affiStatusLine: affiStatusLine,
    affiPostText: affiPostText,
    toHalfWidth: toHalfWidth,
    looseAiFromGenres: looseAiFromGenres,
    aiHint: aiHint,
    AI_RULE: AI_RULE,
    aiVerifiedFalse: aiVerifiedFalse,
    composeTexts: composeTexts,
    resolve: resolve,
    deriveWorkState: deriveWorkState
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  if (root) root.Go5MovieAttrsCore = API;
})(typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : this));
