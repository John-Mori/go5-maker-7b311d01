// GAS(コード.gs)のch→シート振り分けが3ch(月詠み/宵桜艶帖/癒やし倉庫)であることの回帰テスト。
// 2026-10-12: 二択(acc2以外は全部月詠み)のせいで history&channel=acc3 が月詠みの107件を返していた。
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '..', 'gas', 'コード.gs'), 'utf8');
let pass = 0, fail = 0;
function check(name, ok) { if (ok) { pass++; console.log('PASS: ' + name); } else { fail++; console.log('FAIL: ' + name); } }

const pick = (re) => { const m = src.match(re); return m ? m[0] : ''; };
const ctx = {};
vm.runInNewContext(pick(/var CH_SHEETS = \[[^\]]*\];/) + '\n' +
  pick(/function sheetName_\(channel\) \{[^\n]*\}/) + '\n' +
  pick(/function sheetCh_\(name\) \{[^\n]*\}/) + '\nthis.CH_SHEETS = CH_SHEETS; this.sheetName_ = sheetName_; this.sheetCh_ = sheetCh_;', ctx);

check('sheetName_ acc1=月詠み', ctx.sheetName_('acc1') === '月詠み');
check('sheetName_ acc2=宵桜艶帖', ctx.sheetName_('acc2') === '宵桜艶帖');
check('sheetName_ acc3=癒やし倉庫(月詠みへ落ちない)', ctx.sheetName_('acc3') === '癒やし倉庫');
check('sheetCh_ は sheetName_ の逆', ['acc1', 'acc2', 'acc3'].every((c) => ctx.sheetCh_(ctx.sheetName_(c)) === c));
check('CH_SHEETS に3chとも在る', ['月詠み', '宵桜艶帖', '癒やし倉庫'].every((n) => ctx.CH_SHEETS.indexOf(n) >= 0));
check('post_id 接頭辞ガードが acc[12] の二択に戻っていない', !/\(acc\[12\]\)/.test(src));
check("ch名の二択(=== 'acc2' ? 宵桜艶帖 : 月詠み)が残っていない", !/'acc2'\)?\s*\?\s*'宵桜艶帖'\s*:\s*'月詠み'/.test(src));
check('posted_cids が acc3 を返す', /res\.acc3 = postedCidsOne_\('acc3'\)/.test(src));
check('SHORT_WORKER_HOSTS に xdgh3.com', /'https:\/\/xdgh3\.com'/.test(src));

console.log('\n結果: ' + pass + ' PASS / ' + fail + ' FAIL');
process.exit(fail ? 1 : 0);
