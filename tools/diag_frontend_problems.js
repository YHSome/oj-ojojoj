/* 模拟前端「题目列表」页的加载逻辑，验证修复后能拿到题面 */
const fs = require('fs');
const path = require('path');
const FRONT = path.join(__dirname, '..', 'frontend', 'assets');
const localCfg = path.join(FRONT, 'config.js');
if (fs.existsSync(localCfg)) {
  eval(fs.readFileSync(localCfg, 'utf8').replace(/\bwindow\b/g, 'globalThis'));
} else {
  console.error('缺少 frontend/assets/config.js（复制 config.example.js 并填值）');
  process.exit(2);
}
require(path.join(FRONT, 'tinywebdb.js'));
const DB = globalThis.OJDB;

(async () => {
  const db = new DB({ log: (k, m) => console.log('  !', m) });
  const ids = await db.getJson('idx:problems', []);
  console.log('题号索引 idx:problems =', JSON.stringify(ids));
  let ok = 0;
  for (const pid of ids) {
    const p = await db.getJson('prob:' + pid, null);
    if (!p) { console.log('  ✘', pid, '读不到'); continue; }
    ok++;
    const st = p.statement || p.statement_md || '';
    console.log('  ✔ ' + pid.padEnd(9) + ' ' + String(p.title).padEnd(14) +
      ' rev=' + String(p.rev || '-').padEnd(12) +
      ' 题面 ' + st.length + ' 字 / ' + st.split('\n').length + ' 行' +
      ' / 测试点 ' + p.case_count + ' / 满分 ' + p.total_score);
  }
  console.log('\n结论:', ok === ids.length ? '✅ 前端能正常列出全部题目' : '❌ 仍有题目读不到');
  process.exit(ok === ids.length ? 0 : 1);
})();
