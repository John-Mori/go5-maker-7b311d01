// ch表示名を「acc2なら宵桜・それ以外は月詠み」の二択で書くと、acc3(癒やし倉庫)が月詠みと誤表示される。
// v992(ドラフトカード)・v995(投稿履歴)で同じ穴を2回踏んだので、二択の書き方を js/ core/ 全体で禁止する。
// あわせて yt-clicks.js の acctName_ を本物のまま実行し、acc3 が癒やし倉庫になることを確かめる。
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const root = path.join(__dirname, '..');
let pass = 0, fail = 0;
function ok(c, msg) { if (c) { pass++; console.log('ok  ' + msg); } else { fail++; console.log('NG  ' + msg); } }

const BIN = /['"]acc2['"]\s*\?\s*['"]宵桜[^'"]*['"]\s*:\s*['"]月詠み|['"]acc1['"]\s*\?\s*['"]月詠み[^'"]*['"]\s*:\s*['"]宵桜/;
const hits = [];
for (const dir of ['js', 'core']) {
  for (const f of fs.readdirSync(path.join(root, dir))) {
    if (!f.endsWith('.js')) continue;
    fs.readFileSync(path.join(root, dir, f), 'utf8').split(/\r?\n/).forEach((ln, i) => { if (!/^\s*\/\//.test(ln) && BIN.test(ln)) hits.push(dir + '/' + f + ':' + (i + 1)); });
  }
}
ok(hits.length === 0, 'ch名の二択(acc2→宵桜/他→月詠み)が無い' + (hits.length ? ' → ' + hits.join(', ') : ''));

const src = fs.readFileSync(path.join(root, 'js', 'yt-clicks.js'), 'utf8').replace(/\r\n/g, '\n');
const m = src.match(/  function acctName_\(a\) \{[\s\S]*?\n  \}\n/);
ok(!!m, 'acctName_ を取り出せる');
if (m) {
  const run = (go5) => { const sb = { window: { Go5Acct: go5 }, String }; vm.createContext(sb); vm.runInContext(m[0] + '\nthis.f = acctName_;', sb); return sb.f; };
  const withAcct = run({ labelOf: (a) => ({ acc1: '月詠み', acc2: '宵桜艶帖', acc3: '癒やし倉庫' })[a] || '' });
  ok(withAcct('acc3') === '癒やし倉庫', 'acc3 → 癒やし倉庫');
  ok(withAcct('acc1') === '月詠み色恋劇場', 'acc1 → 月詠み色恋劇場(従来どおり)');
  ok(withAcct('acc2') === '宵桜艶帖', 'acc2 → 宵桜艶帖');
  const noAcct = run(undefined);
  ok(noAcct('acc3') === '癒やし倉庫', 'Go5Acct が無くても acc3 → 癒やし倉庫');
}
console.log((fail ? 'FAIL' : 'OK') + ' test_no_binary_ch_label: ' + pass + ' pass, ' + fail + ' fail');
process.exit(fail ? 1 : 0);
