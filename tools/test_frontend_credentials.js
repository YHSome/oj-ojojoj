/* 验证：无 config.js（模拟 GitHub Pages）+ 用户手填凭据 + 本机带 config.js 三种情况 */
const fs = require('fs');
const path = require('path');
const FRONT = path.join(__dirname, '..', 'frontend', 'assets');
const TWDB = path.join(FRONT, 'tinywebdb.js');

// 假的 localStorage：可控且可隔离
function freshStorage() {
  const store = {};
  globalThis.localStorage = {
    getItem: k => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: k => { delete store[k]; }
  };
  return store;
}
function loadClient() {
  delete require.cache[require.resolve(TWDB)];
  delete globalThis.OJDB;
  require(TWDB);
  return globalThis.OJDB;
}

(async () => {
  let ok = true;

  console.log('== 情况 1：公开托管（没有 config.js、本机也没存过凭据） ==');
  delete globalThis.OJ_CONFIG;
  freshStorage();
  let DB = loadClient();
  let db = new DB({ log: () => {} });
  console.log('  user=%s secret=%s hasCredentials=%s', db.cfg.user, db.cfg.secret, db.hasCredentials());
  ok = ok && (db.hasCredentials() === false);
  console.log('  → 页面会显示「未配置」并引导去「连接设置」：', db.hasCredentials() === false ? '✔' : '✘');

  // 读出本机真实凭据（模拟用户在设置里填自己的）
  const src = fs.readFileSync(path.join(FRONT, 'config.js'), 'utf8').replace(/\bwindow\b/g, 'globalThis');
  eval(src);
  const real = globalThis.OJ_CONFIG;
  delete globalThis.OJ_CONFIG;

  console.log('\n== 情况 2：用户在「连接设置」里填自己的实例 ==');
  db.saveCredentials(real.api, real.user, real.secret);
  console.log('  hasCredentials=%s  localStorage 里存了=%s',
    db.hasCredentials(), JSON.stringify(JSON.parse(globalThis.localStorage.getItem('oj_credentials'))).slice(0, 60));
  const info = await db.ping();
  console.log('  ping =', JSON.stringify(info));
  ok = ok && db.hasCredentials() && info.ok;
  console.log('  → 保存后立即可用：', (db.hasCredentials() && info.ok) ? '✔' : '✘');

  console.log('\n== 情况 3：本机部署（带 assets/config.js，原用法不受影响） ==');
  freshStorage();
  globalThis.OJ_CONFIG = { api: real.api, user: real.user, secret: real.secret };
  DB = loadClient();
  db = new DB({ log: () => {} });
  console.log('  user=%s hasCredentials=%s', db.cfg.user, db.hasCredentials());
  ok = ok && db.hasCredentials();
  console.log('  → 仍可直接使用：', db.hasCredentials() ? '✔' : '✘');

  console.log('\n== 情况 4：Pages 上无论如何都不含密钥（检查文件里没有真实 user/secret） ==');
  const tw = fs.readFileSync(TWDB, 'utf8');
  const idx = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'index.html'), 'utf8');
  const leak = tw.includes(real.secret) || idx.includes(real.secret) || tw.includes(real.user);
  console.log('  源码里出现真实 user/secret：', leak ? '✘ 有' : '✔ 没有');
  ok = ok && !leak;

  console.log('\n' + (ok ? '✅ 全部符合预期' : '❌ 有不符项'));
  process.exit(ok ? 0 : 1);
})().catch(e => { console.error('失败:', e); process.exit(1); });
