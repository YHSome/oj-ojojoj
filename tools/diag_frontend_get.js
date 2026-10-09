/* 诊断前端读题目失败的原因 */
const path = require('path');
const C = require(path.join(__dirname, '..', 'frontend', 'assets', 'tinywebdb.js'));
const DB = globalThis.OJDB;

(async () => {
  const db = new DB({ log: (k, m) => console.log('  log:', m) });

  const idx = await db.getRaw('idx:problems', null);
  console.log('idx:problems 原始值 =', JSON.stringify(idx));

  const rawEnc = await db.call('get', { tag: 'prob:P1001' });
  const encoded = rawEnc && (rawEnc['prob:P1001'] !== undefined ? rawEnc['prob:P1001'] : Object.values(rawEnc)[0]);
  console.log('\n云端返回（仍是安全编码态，前 120 字）:\n ', String(encoded).slice(0, 120));

  console.log('\nA) 直接 JSON.parse(云端原文) —— 正确顺序');
  let a = null;
  try { a = JSON.parse(encoded); console.log('   ✔ 成功，title =', a.title, '| 题面前 30 字 =', JSON.stringify(a.statement.slice(0, 30))); }
  catch (e) { console.log('   ✘ 失败:', e.message); }

  console.log('\nB) 先反转义再 JSON.parse —— 当前 getJson 的做法');
  const C2 = { unsafe: globalThis.OJText.unsafe };
  const un = C2.unsafe(String(encoded));
  console.log('   反转义后前 120 字:\n ', un.slice(0, 120).replace(/\n/g, '\\n'));
  try { JSON.parse(un); console.log('   ✔ 成功'); }
  catch (e) { console.log('   ✘ 失败:', e.message); }

  console.log('\nC) 当前 getJson("prob:P1001") 实际返回');
  const got = await db.getJson('prob:P1001', null);
  console.log('   ->', got === null ? 'null（前端就会显示"没有题目"）' : JSON.stringify(got).slice(0, 80));

  console.log('\nD) 判题相关（无换行的值）是否正常');
  console.log('   getJson("sub:...") 用同一条路径，值里没有换行所以看不出来 —— 这就是它一直没被发现的原因');
})();
