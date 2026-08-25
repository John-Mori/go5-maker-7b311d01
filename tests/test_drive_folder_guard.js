/* CI実行対象(.js): Drive同名フォルダの単一化境界を本物のWorker関数で検証する。 */
const assert = require('assert');

(async function () {
  const { getOrCreateExactFolder } = await import('../drive-worker/src/index.js');

  let created = 0;
  const existing = await getOrCreateExactFolder('P-existing-ci', '同名作品', 'TOKEN', {
    list: async () => ['FOLDER_EXISTING'],
    create: async () => { created++; return { id: 'SHOULD_NOT_CREATE' }; },
  });
  assert.strictEqual(existing.folder.id, 'FOLDER_EXISTING');
  assert.strictEqual(existing.reused, true);
  assert.strictEqual(created, 0);

  let listed = 0;
  created = 0;
  const ops = {
    list: async () => {
      listed++;
      await new Promise((resolve) => setTimeout(resolve, 10));
      return [];
    },
    create: async () => {
      created++;
      await new Promise((resolve) => setTimeout(resolve, 10));
      return { id: 'FOLDER_ONLY_ONE' };
    },
  };
  const pair = await Promise.all([
    getOrCreateExactFolder('P-parallel-ci', '同時再送', 'TOKEN', ops),
    getOrCreateExactFolder('P-parallel-ci', '同時再送', 'TOKEN', ops),
  ]);
  assert.strictEqual(pair[0].folder.id, 'FOLDER_ONLY_ONE');
  assert.strictEqual(pair[1].folder.id, 'FOLDER_ONLY_ONE');
  assert.strictEqual(listed, 1);
  assert.strictEqual(created, 1);

  created = 0;
  await assert.rejects(getOrCreateExactFolder('P-list-fail-ci', '照合不能', 'TOKEN', {
    list: async () => { throw new Error('drive-list-error'); },
    create: async () => { created++; return { id: 'DUPLICATE' }; },
  }), /folder_lookup_failed/);
  assert.strictEqual(created, 0, '一覧確認不能時は二重作成より再試行を選ぶ');

  console.log('PASS: Drive同名フォルダの再利用・並列単一化・fail-closed');
})().catch(function (e) {
  console.error(e);
  process.exit(1);
});
