/* ============================================================================
 *  e2e_frontend.js —— 用真实前端模块跑端到端（等价于无头浏览器）
 *
 *  直接 require 前端的 assets/crypto.js 与 assets/tinywebdb.js，
 *  完整走一遍：注册/登录 → 取判题机公钥 → RSA-OAEP 加密源码 → 分片写云端
 *  → 入队 → 等判题机取码/判题 → 拉密文结果 → 用本机私钥解密 → 验签。
 *
 *  用法: node tools/e2e_frontend.js [PID] [sample] [user]
 * ==========================================================================*/
const path = require('path');
const FRONT = path.join(__dirname, '..', 'frontend', 'assets');
const C = require(path.join(FRONT, 'crypto.js'));
require(path.join(FRONT, 'tinywebdb.js'));
const DB = globalThis.OJDB;

const fs = require('fs');
const PID = process.argv[2] || 'a-plus-b';
const SAMPLE = process.argv[3] || 'ac';
const USER = process.argv[4] || ('web' + Math.floor(Math.random() * 900 + 100));

const CODES = {
  ac: '#include <bits/stdc++.h>\nint main(){ long long a,b; if(scanf("%lld %lld",&a,&b)!=2) return 0; printf("%lld\\n",a+b); return 0; }\n',
  wa: '#include <bits/stdc++.h>\nint main(){ long long a,b; scanf("%lld %lld",&a,&b); printf("%lld\\n",a-b); return 0; }\n',
  ce: '#include <bits/stdc++.h>\nint main(){ this is not c++ }\n',
  pyre: 'a , b = map(int, input().split)\nprint(a + b)\n'
};
const LANG = { pyre: 'py' };

// 也支持直接给一个源码文件路径：node e2e_frontend.js P1001 /path/to/main.py
let CODE = CODES[SAMPLE], LANGID = LANG[SAMPLE] || 'cpp';
if (!CODE) {
  try { CODE = fs.readFileSync(SAMPLE, 'utf8'); LANGID = /\.py$/.test(SAMPLE) ? 'py' : 'cpp'; }
  catch (e) { CODE = CODES.ac; }
}

function log(kind, msg) {
  const tag = { ok: '✔', err: '✘', warn: '!', info: '·' }[kind] || '·';
  console.log('  ' + tag + ' ' + msg);
}

const sleep = ms => new Promise(r => setTimeout(r, ms));
const nowSec = () => Math.floor(Date.now() / 1000);
const newSid = () => String(Date.now() % 1000000) + String(Math.floor(Math.random() * 1000)).padStart(3, '0');
const newCid = () => 'n' + String(Date.now() % 1000000) + String(Math.floor(Math.random() * 10000)).padStart(4, '0');

(async () => {
  const db = new DB({ log });

  console.log('== 0) 云端连通性 ==');
  const n = await db.count();
  log('ok', '云端标签数 = ' + n);

  console.log('\n== 1) 注册/登录（命令总线 RPC，与网页同一路径） ==');
  let cid = newCid();
  await db.putJson('cmd:' + cid, {
    cid, op: 'register', args: { user: USER, pass: 'web12345', nick: USER },
    user: '', token: '', status: 'pending', ts: nowSec()
  });
  let rep = null;
  for (let i = 0; i < 40 && !rep; i++) { await sleep(1200); rep = await db.getJson('reply:' + cid, null); }
  if (!rep) throw new Error('注册超时：判题机没在跑？');
  if (!rep.ok && rep.msg !== '用户已存在') throw new Error('注册失败: ' + rep.msg);
  log('ok', '用户 ' + USER + ' → ' + rep.msg);

  cid = newCid();
  await db.putJson('cmd:' + cid, {
    cid, op: 'login', args: { user: USER, pass: 'web12345' },
    user: '', token: '', status: 'pending', ts: nowSec()
  });
  rep = null;
  for (let i = 0; i < 40 && !rep; i++) { await sleep(1200); rep = await db.getJson('reply:' + cid, null); }
  if (!rep || !rep.ok) throw new Error('登录失败: ' + (rep && rep.msg));
  const token = rep.data.token;
  log('ok', '登录成功，token = ' + token.slice(0, 12) + '…');

  console.log('\n== 2) 取判题机公钥 oj:pubkey ==');
  const judgePub = await db.getJson('oj:pubkey', null);
  if (!judgePub || !judgePub.n) throw new Error('云端没有 oj:pubkey，先启动判题机');
  const judgeFp = judgePub.fingerprint || await C.fingerprint(judgePub);
  log('ok', '判题机公钥指纹 = ' + judgeFp);

  console.log('\n== 3) 生成客户端密钥并 RSA-OAEP 加密源码 ==');
  const kp = await C.generateKeyPair(2048);
  const clientPub = await C.exportPublicJwk(kp.publicKey);
  const clientFp = await C.fingerprint(clientPub);
  log('ok', '客户端公钥指纹 = ' + clientFp + '（结果只有本机私钥能解）');

  const code = CODE;
  const t0 = Date.now();
  const env = await C.seal(judgePub, code, { to: judgeFp });
  log('ok', '加密 ' + Buffer.byteLength(code, 'utf8') + ' 字节 → ' + env.n + ' 个 RSA 密文块，用时 ' +
    (Date.now() - t0) + 'ms');

  const sid = newSid();
  const perTag = Math.max(1, Math.floor(db.cfg.chunkChars / 345));
  const groups = [];
  for (let i = 0; i < env.c.length; i += perTag) groups.push(env.c.slice(i, i + perTag).join('\n'));
  for (let g = 0; g < groups.length; g++) await db.setRaw('code:' + sid + ':' + g, groups[g]);
  await db.putJson('code:' + sid, {
    chunked: true, n: groups.length, size: code.length, base: 'code:' + sid + ':',
    alg: env.alg, enc: env.enc, sha256: env.sha256, to: judgeFp,
    state: 'sealed', ts: nowSec()
  });
  log('ok', '密文入库 code:' + sid + ' + ' + groups.length + ' 个分片');

  const prob = await db.getJson('prob:' + PID, null);
  await db.putJson('sub:' + sid, {
    sid, user: USER, pid: PID, lang: LANGID, status: 'pending', ts: nowSec(),
    judge: '', verdict: '', score: 0, time_ms: 0, memory_kb: 0, cases_passed: 0,
    case_count: 0, msg: '排队中', prob_rev: (prob && prob.rev) || '', attempt: 0,
    lease_token: '', lease_until: 0, rejudge: '', enc: 'RSA-OAEP-256',
    client_pubkey: clientPub
  });
  await db.putJson('q:' + sid, { sid, ts: nowSec(), pid: PID, lang: LANGID, user: USER });
  log('ok', '已入队 sid=' + sid + '（判题机每 3 秒轮询一次）');

  console.log('\n== 4) 等判题机取码并判题 ==');
  let sub = null, sawJudging = false, sawCodeTaken = false, t1 = Date.now();
  while (Date.now() - t1 < 180000) {
    sub = await db.getJson('sub:' + sid, null);
    const codeTag = await db.getJson('code:' + sid, null);
    if (codeTag && codeTag.state === 'judging' && !sawJudging) {
      sawJudging = true;
      log('ok', '云端 code:' + sid + ' → ' + codeTag.state + '（密文已被判题机取走）');
    }
    if (codeTag && codeTag.state === 'done' && !sawCodeTaken) {
      sawCodeTaken = true;
      log('ok', '云端 code:' + sid + ' → done（' + (codeTag.verdict || '') + '）');
    }
    if (sub && (sub.status === 'done' || sub.status === 'failed')) break;
    await sleep(1500);
  }
  if (!sub || (sub.status !== 'done' && sub.status !== 'failed')) throw new Error('等待判题超时');
  log('ok', '判题状态 = ' + sub.status + '，verdict = ' + sub.verdict + '，分数 = ' + sub.score);
  const leftover = await db.getRaw('code:' + sid + ':0', null);
  log(leftover === null || leftover === '' ? 'ok' : 'warn',
    '云端残留密文分片: ' + (leftover ? '仍存在' : '已清除'));

  console.log('\n== 5) 取回密文结果并用本机私钥解密 ==');
  const payload = await db.getJson('res:' + sid, null);
  if (!payload) throw new Error('没有 res 结果');
  let full = payload, sigOk = null;
  if (payload.state === 'sealed') {
    const man = payload.sealed_env;
    let body = '';
    for (let i = 0; i < (man.n || 0); i++) body += (await db.getRaw('res:' + sid + ':' + i, '')) || '';
    const envelope = Object.assign({}, man, { c: body.split('\n').filter(x => x.trim()) });
    const text = await C.openSealed(kp.privateKey, envelope);
    full = JSON.parse(text);
    if (man.sig) sigOk = await C.verifySignature(judgePub, text, man.sig);
    log('ok', '解密成功（' + text.length + ' 字符），判题机签名 = ' + (sigOk ? '有效 ✔' : '无效 ✘'));
  } else {
    log('warn', '结果是明文（未启用结果加密）');
  }
  console.log('\n== 结果 ==');
  console.log('  verdict = ' + full.verdict + '  score = ' + full.score +
    '  time = ' + full.time_ms + 'ms  memory = ' + full.memory_kb + 'KB');
  (full.cases || []).forEach(c => console.log('   case ' + c.i + '  ' + c.verdict + '  ' +
    c.time_ms + 'ms  ' + c.memory_kb + 'KB  ' + (c.msg || '').slice(0, 60)));
  if (full.compile_log) console.log('  编译日志: ' + full.compile_log.split('\n')[0].slice(0, 120));

  const srcBack = full.source || '';
  const srcOk = srcBack === code;
  console.log('  源码随加密结果回传: ' + (srcOk ? '✔ 与提交内容完全一致（' + srcBack.length + ' 字符）'
    : (srcBack ? '✘ 不一致' : '— 未回传')));

  const expect = { ac: 'AC', wa: 'WA', ce: 'CE', pyre: 'RE' }[SAMPLE];
  const pass = (!expect || full.verdict === expect) && sigOk !== false && sawJudging && srcOk;
  console.log('\n' + (pass ? '✅ 前端↔后端 加密端到端通过' : '❌ 端到端未达预期'));
  process.exit(pass ? 0 : 1);
})().catch(e => { console.error('端到端失败: ' + (e && e.message || e)); process.exit(1); });
