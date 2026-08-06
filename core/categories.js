/**
 * core/categories.js — 動画のカテゴリ(ジャンル)の唯一の正本。(Go5Cats)
 *
 * 【解く問題】これまでカテゴリは 8 個ハードコードで、5 箇所(index.html の
 *   チェックボックス / bluesky.js の MOVIE_ATTRS・GENRE_ATTR_KEYWORDS / drafts.js の
 *   ATTR_KEYS / stock.js の MOVIE_ATTR_IDS / yt-clicks.js の ATTR_DEFS)に同じ内容が
 *   別々に書かれていた。追加・並べ替え・色替えができず、増やすと 5 箇所を手で直す必要があった。
 *
 * 【対策】カテゴリを 1 つのレジストリ(この Go5Cats)へ集約する。上記 5 箇所は全て
 *   Go5Cats.list() から派生させる。Chami は「カテゴリ編集」ボタンで
 *   追加(色・キーワード指定)・並べ替え・削除ができ、候補・投稿履歴・自動チェックへ即反映される。
 *
 * 保存先 localStorage `movie_categories_v1`(全端末同期＝storage-keys.js の SYNC_EXACT に登録)。
 *   組み込み 8 個は消せない(hidden で隠すのみ)。追加分は色・キーワード・並び順・削除が自由。
 *
 * 【カテゴリ 1 件の形】{ key, label, color, keywords:[], builtin, hidden }
 *   - key      … 内部キー。item[key]=true で記録され GAS/シートの列名にもなる。組み込みは chara/jk/…。追加分は c<base36>。
 *   - label    … 画面表示名。
 *   - color    … #RRGGBB。チェックボックスの文字色・履歴タグ色。
 *   - keywords … FANZA ジャンル名/フロア名との部分一致キーワード(自動チェック用)。
 *   - builtin  … 組み込みなら true(消せない)。
 *   - hidden   … true でチェックボックス欄から隠す(組み込みを使わない時)。
 *
 * elId(key) = 'movieAttr' + Cap(key) ＝既存の要素 ID(movieAttrChara 等)と完全一致。
 */
(function (root) {
  'use strict';
  var LS = 'movie_categories_v1';

  // 組み込みカテゴリ(色・キーワードは従来の style.css / bluesky.js の値を踏襲)。
  var BUILTIN = [
    { key: 'chara',  label: 'キャラ',   color: '#d0566a', keywords: ['二次創作'] },
    { key: 'jk',     label: 'JK',       color: '#e89bc4', keywords: ['女子校生', '女子高生', 'JK'] },
    { key: 'gyaru',  label: 'ギャル',   color: '#cba94e', keywords: ['ギャル'] },
    { key: 'isekai', label: '異世界',   color: '#9b7ed1', keywords: ['異世界', '転生'] },
    { key: 'harem',  label: 'ハーレム', color: '#ef6da8', keywords: ['ハーレム'] },
    // ★AI: タグ(genre)に載らず「コミック(AI)」等フロア名で示される作品を拾うため、フロア名も部分一致に含める。
    //   中黒・半角/全角カッコ・スペース違いで実ページと綴りがズレて拾えない事故があったため、実在する表記ゆれを網羅する。
    { key: 'ai',     label: 'AI',       color: '#4d9fff', keywords: ['AI生成', 'AIイラスト', 'AIグラビア', 'AIコミック', 'AIボイス', 'AI画像', 'コミック・AI', 'コミック(AI)', 'コミック（AI）', '(AI)', '（AI）'] },
    { key: 'ol',     label: 'OL',       color: '#b56db0', keywords: ['OL'] },
    { key: 'soshu',  label: '総集編',   color: '#e0863c', keywords: ['総集編'] }
  ];
  // 追加カテゴリの初期色候補(既存色と重複しにくい順)。
  var PALETTE = ['#3fb6a8', '#2fa96e', '#5bb8ae', '#c98a3a', '#7fa5d8', '#d68fb0', '#8fbf6a', '#c05a5a', '#7d6fc0', '#5a9ec0'];

  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function cap(s) { s = String(s || ''); return s.charAt(0).toUpperCase() + s.slice(1); }
  function elId(key) { return 'movieAttr' + cap(key); }

  function lsGet() { try { return localStorage.getItem(LS); } catch (e) { return null; } }
  function lsSet(v) { try { localStorage.setItem(LS, v); } catch (e) {} }

  // 組み込みを土台に、保存済みの並び順・色・キーワード・追加分・hidden を重ねて確定リストを作る。
  //   保存が空/壊れていても組み込み 8 個は必ず返す(＝新規端末や破損でカテゴリが消えない)。
  function load() {
    var stored = null;
    try { stored = JSON.parse(lsGet() || 'null'); } catch (e) { stored = null; }
    var builtinByKey = {};
    BUILTIN.forEach(function (b) { builtinByKey[b.key] = b; });
    if (!Array.isArray(stored) || !stored.length) return BUILTIN.map(function (b) { return normalize(b, true); });

    var out = [], seen = {};
    stored.forEach(function (s) {
      if (!s || !s.key || seen[s.key]) return;
      seen[s.key] = 1;
      var b = builtinByKey[s.key];
      // 組み込みは「コード側の標準キーワード」を常にunionで取り込む。
      //   ＝過去に保存された端末では s.keywords が古い綴りのまま凍結され、コードでキーワードを直しても
      //     load() が s.keywords を優先して既存端末へ永久に届かなかった(AI作品がAIとして読めない再発の真因)。
      //   ユーザーがカテゴリ編集で足したキーワードは温存し、コード側の改善分だけを追加する(非破壊・重複排除)。
      var kws = Array.isArray(s.keywords) ? s.keywords.slice() : (b ? b.keywords.slice() : []);
      if (b) b.keywords.forEach(function (k) { if (kws.indexOf(k) < 0) kws.push(k); });
      out.push(normalize({
        key: s.key,
        label: s.label != null ? s.label : (b ? b.label : s.key),
        color: s.color || (b ? b.color : PALETTE[0]),
        keywords: kws,
        hidden: !!s.hidden
      }, !!b));
    });
    // 保存に無い組み込み(将来追加した組み込み等)は末尾へ補う＝消えない。
    BUILTIN.forEach(function (b) { if (!seen[b.key]) out.push(normalize(b, true)); });
    return out;
  }

  function normalize(c, builtin) {
    return {
      key: String(c.key),
      label: String(c.label == null ? c.key : c.label),
      color: /^#[0-9a-fA-F]{3,8}$/.test(String(c.color || '')) ? c.color : PALETTE[0],
      keywords: (Array.isArray(c.keywords) ? c.keywords : []).map(function (k) { return String(k || ''); }).filter(Boolean),
      builtin: !!builtin,
      hidden: !!c.hidden
    };
  }

  var _cache = null;
  function list() { if (!_cache) _cache = load(); return _cache; }
  function visible() { return list().filter(function (c) { return !c.hidden; }); }
  function byKey(k) { var a = list(); for (var i = 0; i < a.length; i++) if (a[i].key === k) return a[i]; return null; }
  function colorOf(k) { var c = byKey(k); return c ? c.color : '#9fb0c3'; }
  function labelOf(k) { var c = byKey(k); return c ? c.label : k; }

  var _subs = [];
  function onChange(fn) { if (typeof fn === 'function') _subs.push(fn); }
  function emit() { _subs.forEach(function (fn) { try { fn(); } catch (e) {} }); }

  function persist(arr) {
    _cache = arr.map(function (c) { return normalize(c, c.builtin); });
    // 保存は差分だけでなく全件(組み込み含む)。色・並び順・キーワードの編集も保持するため。
    lsSet(JSON.stringify(_cache.map(function (c) {
      return { key: c.key, label: c.label, color: c.color, keywords: c.keywords, hidden: c.hidden, builtin: c.builtin };
    })));
    emit();
  }

  function genKey() {
    var k, used = {}; list().forEach(function (c) { used[c.key] = 1; });
    do { k = 'c' + (Date.now().toString(36)) + Math.floor(Math.random() * 1000).toString(36); } while (used[k]);
    return k;
  }

  // 追加。label 必須。color/keywords 任意。返り値=新カテゴリの key。
  function add(label, color, keywords) {
    var arr = list().slice();
    var k = genKey();
    arr.push(normalize({
      key: k, label: label || '新カテゴリ',
      color: color || PALETTE[arr.length % PALETTE.length],
      keywords: keywords || []
    }, false));
    persist(arr);
    return k;
  }
  function update(key, patch) {
    var arr = list().map(function (c) {
      if (c.key !== key) return c;
      var n = clone(c);
      if (patch.label != null) n.label = patch.label;
      if (patch.color != null) n.color = patch.color;
      if (patch.keywords != null) n.keywords = patch.keywords;
      if (patch.hidden != null) n.hidden = !!patch.hidden;
      return n;
    });
    persist(arr);
  }
  // 削除は追加分のみ(組み込みは hidden で隠す)。
  function remove(key) {
    var c = byKey(key); if (!c) return;
    if (c.builtin) { update(key, { hidden: true }); return; }
    persist(list().filter(function (x) { return x.key !== key; }));
  }
  // 並べ替え。keys = 新しい順のキー配列(欠けたキーは末尾に元順で残す)。
  function reorder(keys) {
    var pos = {}; keys.forEach(function (k, i) { pos[k] = i; });
    var arr = list().slice().sort(function (a, b) {
      var pa = (a.key in pos) ? pos[a.key] : 1e9, pb = (b.key in pos) ? pos[b.key] : 1e9;
      return pa - pb;
    });
    persist(arr);
  }

  // 文字列群(ジャンル名・フロア名・サービス名 等)に対して、各カテゴリのキーワードが
  //   部分一致(indexOf)するかを判定。返り値 = {key:true, ...}。キーワード空のカテゴリは一致しない。
  //   ★部分一致＝「姉」カテゴリは作品の「姉・妹」ジャンルにも一致する(Chami依頼2026-08-02③)。
  function matchText(texts) {
    var arr = (texts || []).map(function (t) { return String(t || ''); }).filter(Boolean);
    var o = {};
    visible().forEach(function (c) {
      if (!c.keywords.length) return;
      var hit = c.keywords.some(function (kw) { return arr.some(function (t) { return t.indexOf(kw) >= 0; }); });
      if (hit) o[c.key] = true;
    });
    return o;
  }

  var API = {
    list: list, visible: visible, byKey: byKey, colorOf: colorOf, labelOf: labelOf,
    elId: elId, add: add, update: update, remove: remove, reorder: reorder,
    matchText: matchText, onChange: onChange, PALETTE: PALETTE,
    // UI(チェックボックス描画・編集モーダル)は categories-ui.js が root.Go5CatsUI に載せる。
    _reload: function () { _cache = null; return list(); }
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  if (root) root.Go5Cats = API;
})(typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : this));
