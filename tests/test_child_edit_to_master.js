// 投稿モードの「子の文」の手直しが投稿本文(固定文)へ戻る形になる番犬
// (Chami msg 1561144626054955010「新しくドラフトで動画作ると元に戻る。戻らないようにして」)。
//   C-1 触っていない行=本文のプレースホルダのまま・自動の2行目は本文へ入れない
//   C-2 手で足した/直した行は残り、置換された短縮URLは本文側の表記へ戻る
//   C-3 消した行は本文からも消える
//   C-4 対応が取れない(本文と欄の行がずれる)時は null=書き戻さない
//   C-5 本文から作り直すと手直しが出る(=次のドラフトで元に戻らない)
const assert = require('assert');
const core = require('../core/movie-attrs-core.js');

const WPH = '(商品紹介短縮URL)', SPH = '(セール紹介短縮用URL)';
const master = ['⇩気になった方はコチラから💕 #PR #漫画', WPH, '', SPH].join('\n');
function compose(m) {
  const t = m.split(WPH).join('https://xdgh3.com/Oc7M6').split(SPH).join('https://xdgh3.com/odquD');
  return core.withAffiStatusLine(t, { discountPct: 70, releaseDate: '2020-01-01' });
}
const sys = compose(master);
assert.strictEqual(sys.split('\n')[1], '70%OFFの話題作✨️');

assert.strictEqual(core.childEditToMaster(master, sys, sys), master, 'C-1 無編集は本文そのまま');
console.log('  PASS C-1');

let ed = sys.replace('#PR #漫画', '#PR #漫画 #おすすめ') + '\nhttps://xdgh3.com/odquD ←今だけ';
let nm = core.childEditToMaster(master, sys, ed);
assert.strictEqual(nm, ['⇩気になった方はコチラから💕 #PR #漫画 #おすすめ', WPH, '', SPH, SPH + ' ←今だけ'].join('\n'), 'C-2');
console.log('  PASS C-2');

ed = sys.split('\n').filter((l, i) => i !== 3 && i !== 4).join('\n');
nm = core.childEditToMaster(master, sys, ed);
assert.strictEqual(nm, ['⇩気になった方はコチラから💕 #PR #漫画', WPH].join('\n'), 'C-3 空行とセール行を消した');
console.log('  PASS C-3');

assert.strictEqual(core.childEditToMaster('全然ちがう本文', sys, sys), null, 'C-4');
console.log('  PASS C-4');

ed = sys.replace('#PR #漫画', '#PR #漫画 #おすすめ');
nm = core.childEditToMaster(master, sys, ed);
assert.strictEqual(compose(nm), ed, 'C-5 次に開いた時も手直しが出る');
// 手直しの後にもう一度直しても(欄=sys・本文=書き戻し後)続けて対応が取れる
const ed2 = ed.replace('#おすすめ', '#おすすめ #新刊');
assert.strictEqual(core.childEditToMaster(nm, ed, ed2), nm.replace('#おすすめ', '#おすすめ #新刊'));
console.log('  PASS C-5');
console.log('test_child_edit_to_master: OK');
