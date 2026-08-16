/**
 * core/disc-line-core.js — 割引文サフィックス(の新作/の準新作/の総集編…)の唯一の正本。(Go5DiscLine)
 *
 * 【解く問題】割引行末尾のサフィックス生成/剥がしが js/bluesky.js に直書きで、2026-08-02→04→05 と
 *   3回も仕様追加されたのに純粋関数テストが0本だった(検証は window フックのみ=Node で叩けない)。
 *   準新作を割引文へ出す改修(Chami依頼2026-08-16③)を機に、生成と剥がしを1本へ集約しテストを付ける。
 *   deriveWorkState / aiHint と同じ「正本1本化＋本物を叩く Node テスト」の型(C-038)＝片方だけ直して割れる再発を封じる。
 *
 * 【排他】新作 > 準新作(同時ONは新作優先)。総集編は両立。bluesky.js readWorkState の優先順位と一致させる。
 */
(function (root) {
  'use strict';

  // 割引行末尾のサフィックス。
  //   新作のみ='の新作' / 準新作のみ='の準新作' / 総集編のみ='の総集編' /
  //   新作&総集編='の新作&総集編' / 準新作&総集編='の準新作&総集編' / どれも無し=''。
  function discSuffix(isNew, isJun, isDigest) {
    var head = isNew ? '新作' : (isJun ? '準新作' : '');
    if (head && isDigest) return 'の' + head + '&総集編';
    if (head) return 'の' + head;
    if (isDigest) return 'の総集編';
    return '';
  }

  // 既存の割引行に上のサフィックスだけを差し込む純粋関数。数字・単位・末尾の絵文字はそのまま保持。
  //   既存のサフィックス(新作/準新作/総集編)は一旦剥がしてから付け直す(再トグルで重ならない)。
  //   ★剥がしは「準?新作」＝新作/準新作の両方を拾う(準新作は先頭「準」で旧 regex に不マッチだった穴を塞ぐ)。
  function respliceDiscLine(line, isNew, isJun, isDigest) {
    var s = String(line == null ? '' : line);
    var m = s.match(/^(.*?(?:オフ|円))(.*)$/);       // head=「…N%オフ / …N円」まで、tail=その後ろの装飾
    if (!m) return s;
    var tail = m[2].replace(/^の(?:準?新作(?:&総集編)?|総集編)/, '');  // 既存サフィックス(準新作/新作/総集編)を剥がす
    return m[1] + discSuffix(isNew, isJun, isDigest) + tail;
  }

  var API = { discSuffix: discSuffix, respliceDiscLine: respliceDiscLine };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  if (root) root.Go5DiscLine = API;
})(typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : this));
