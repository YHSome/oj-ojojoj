/* ============================================================================
 *  app.js —— OJ 前端逻辑（纯静态，无框架）
 *
 *  提交流程（严格按需求）：
 *    1) 读云端 oj:pubkey（判题机公钥）
 *    2) 用公钥非对称加密源码 → 分片写进 code:<SID> 与 code:<SID>:i
 *    3) 写 sub:<SID>（带自己的公钥 client_pubkey，用于让判题机把结果加密回传）
 *    4) 写 q:<SID> 入队
 *    5) 轮询 sub:<SID>：pending → judging → done；判题机取码后会把 code:<SID> 改成"判题中"
 *    6) 结果 res:<SID> 是密文 → 用本机私钥解密 + 用判题机公钥验签
 * ==========================================================================*/
(function () {
  'use strict';

  var DB = window.OJDB, TXT = window.OJText, C = window.OJCrypto;

  /* ------------------------------------------------------------ 全局状态 */
  var state = {
    db: null,
    session: null,          // {user, token, nick}
    clientKeys: null,       // {publicKey, privateKey}
    clientPubJwk: null,
    judgePubJwk: null,
    judgeFp: '',
    problems: [],
    current: null,          // 当前题目
    watch: [],              // 正在轮询的 {sid, timer, panel}
    lastResult: null
  };

  var LS = {
    get: function (k, d) { try { return JSON.parse(localStorage.getItem(k)) || d; } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* ignore */ } },
    del: function (k) { try { localStorage.removeItem(k); } catch (e) { /* ignore */ } }
  };
  var SS = {
    get: function (k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { sessionStorage.setItem(k, v); } catch (e) { /* ignore */ } }
  };

  /* ------------------------------------------------- 本地源码存档（我的代码）
     判题机取码后会把云端密文删掉（隐私设计），所以「我的代码」由浏览器自己留一份：
     只有这台机器这个浏览器能看到，不上云、不外泄。超出体积上限就丢最旧的。 */
  var SRC = {
    KEY: 'oj_src_archive',
    MAX_ITEMS: 60,
    MAX_CHARS: 300000,
    all: function () { return LS.get(SRC.KEY, {}); },
    put: function (sid, rec) {
      try {
        var a = SRC.all();
        a[sid] = rec;
        var keys = Object.keys(a).sort(function (x, y) { return (a[y].ts || 0) - (a[x].ts || 0); });
        var total = 0;
        keys.forEach(function (k, i) {
          total += (a[k].code || '').length;
          if (i >= SRC.MAX_ITEMS || total > SRC.MAX_CHARS) delete a[k];
        });
        LS.set(SRC.KEY, a);
      } catch (e) { log('warn', '本地源码存档失败（可能空间不足）: ' + e.message); }
    },
    get: function (sid) { return SRC.all()[sid] || null; },
    drop: function (sid) { var a = SRC.all(); delete a[sid]; LS.set(SRC.KEY, a); }
  };

  /* --------------------------------------------------------------- 工具 */
  function $(sel) { return document.querySelector(sel); }
  function $$(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }
  function esc(s) {
    return String(s === undefined || s === null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function nowSec() { return Math.floor(Date.now() / 1000); }
  function newSid() { return String(Date.now() % 1000000) + String(Math.floor(Math.random() * 1000)).padStart(3, '0'); }
  function newCid() { return 'w' + String(Date.now() % 1000000) + String(Math.floor(Math.random() * 10000)).padStart(4, '0'); }
  function short(s, n) { s = String(s || ''); return s.length > n ? s.slice(0, n) + '…' : s; }

  function toast(msg, kind) {
    var el = $('#toast');
    el.className = 'toast show ' + (kind || '');
    el.textContent = msg;
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.className = 'toast'; }, 3600);
  }

  function log(kind, msg) {
    var box = $('#log');
    if (!box) return;
    var line = document.createElement('div');
    line.className = 'log-line ' + (kind || '');
    line.textContent = '[' + new Date().toLocaleTimeString() + '] ' + msg;
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
  }

  function showTab(name) {
    $$('.tab').forEach(function (t) { t.classList.toggle('active', t.dataset.tab === name); });
    $$('.panel').forEach(function (p) { p.classList.toggle('active', p.dataset.panel === name); });
    if (name === 'rank') loadRank();
    if (name === 'mine') loadMine();
    if (name === 'problems') loadProblems();
    if (name === 'setup') renderSetup();
  }

  /* --------------------------------------------------------- 初始化 */
  async function boot() {
    state.db = new DB({ log: log });
    log('info', '前端已启动，API = ' + state.db.cfg.api);
    renderSetup();
    if (!state.db.hasCredentials()) {
      // 公开部署（例如 GitHub Pages）里不带任何密钥：让使用者填自己的实例
      log('warn', '还没有配置云端凭据 → 请在「连接设置」里填入你的 TinyWebDB user/secret');
      toast('首次使用：请到「连接设置」填入你的 TinyWebDB 实例信息', 'bad');
      $('#health').textContent = '未配置云端凭据';
      $('#health').className = 'pill bad';
      showTab('setup');
      return;
    }

    // 会话内生成客户端密钥对：判题结果只有本浏览器能解
    var cachedPriv = SS.get('oj_client_priv');
    if (cachedPriv) {
      try {
        var jwk = JSON.parse(cachedPriv);
        state.clientKeys = { privateKey: await C.importPrivateJwk(jwk), publicKey: null };
        state.clientPubJwk = { kty: 'RSA', alg: C.ALG, use: 'enc', key_ops: ['encrypt'], n: jwk.n, e: jwk.e };
        state.clientKeys.publicKey = await C.importPublicJwk(state.clientPubJwk);
        log('info', '已恢复本会话的客户端密钥（指纹 ' + (await C.fingerprint(state.clientPubJwk)) + '）');
      } catch (e) {
        log('warn', '恢复客户端密钥失败，重新生成: ' + e.message);
        cachedPriv = null;
      }
    }
    if (!cachedPriv) {
      var kp = await C.generateKeyPair(2048);
      state.clientKeys = kp;
      state.clientPubJwk = await C.exportPublicJwk(kp.publicKey);
      SS.set('oj_client_priv', JSON.stringify(await C.exportPrivateJwk(kp.privateKey)));
      log('info', '已生成客户端密钥对（指纹 ' + (await C.fingerprint(state.clientPubJwk)) + '），用于接收加密结果');
    }

    state.session = LS.get('oj_session', null);
    var lastUser = LS.get('oj_last_user', '');
    if (lastUser) $('#login-user').value = lastUser;
    if (state.session) {
      // 已有会话：先自检 token 是否还有效，别让用户"看着登录了其实早过期"
      renderSession();
      showTab('problems');
      $('#session-state').textContent = '校验登录态…';
      rpc('whoami', {}, 12000).then(function (rep) {
        if (rep.ok) {
          state.session.user = rep.data.user.user;
          state.session.nick = rep.data.user.nick || state.session.user;
          state.session.solved = rep.data.user.solved || [];
          LS.set('oj_session', state.session);
          renderSession();
          $('#session-state').textContent = '';
          log('ok', '登录态有效：' + state.session.user);
        } else {
          log('warn', '登录态已失效：' + (rep.msg || ''));
          doLogout(true);
        }
      }).catch(function () { $('#session-state').textContent = ''; });
    }

    await refreshJudgeKey();
    await loadProblems();
    var health = $('#health');
    health.textContent = '检查中…';
    try {
      var n = await state.db.count();
      health.textContent = '云端可用 · 共 ' + n + ' 个标签';
      health.className = 'pill ok';
    } catch (e) {
      health.textContent = '云端不可用: ' + e.message;
      health.className = 'pill bad';
    }
  }

  async function refreshJudgeKey() {
    var pub = await state.db.getJson('oj:pubkey', null);
    if (!pub || !pub.n) {
      state.judgePubJwk = null;
      $('#judgekey').textContent = '未发布（判题机还没启动过）';
      $('#judgekey').className = 'pill bad';
      return;
    }
    state.judgePubJwk = pub;
    state.judgeFp = pub.fingerprint || await C.fingerprint(pub);
    $('#judgekey').textContent = '判题机公钥 ' + state.judgeFp;
    $('#judgekey').className = 'pill ok';
  }

  /* ------------------------------------------------------------- 命令总线 */
  async function rpc(op, args, timeoutMs) {
    var cid = newCid();
    await state.db.putJson('cmd:' + cid, {
      cid: cid, op: op, args: args || {},
      user: state.session ? state.session.user : '',
      token: state.session ? state.session.token : '',
      status: 'pending', ts: nowSec()
    });
    var t0 = Date.now(), limit = timeoutMs || 30000;
    while (Date.now() - t0 < limit) {
      await new Promise(function (r) { setTimeout(r, 1200); });
      var rep = await state.db.getJson('reply:' + cid, null);
      if (rep) return rep;
    }
    return { ok: false, msg: '超时：判题机没在运行吗？（cmd ' + cid + '）', data: {} };
  }

  /* ------------------------------------------------------------ 登录注册 */
  async function doLogin() {
    var user = $('#login-user').value.trim(), pass = $('#login-pass').value;
    if (!user || !pass) return toast('请输入用户名和密码', 'bad');
    log('info', '登录中…');
    var rep = await rpc('login', { user: user, pass: pass });
    if (!rep.ok) return toast(rep.msg || '登录失败', 'bad');
    state.session = { user: rep.data.user.user, token: rep.data.token, nick: rep.data.user.nick || rep.data.user.user };
    LS.set('oj_session', state.session);
    LS.set('oj_last_user', user);
    renderSession();
    toast('登录成功：' + state.session.nick, 'ok');
    showTab('problems');
  }

  async function doRegister() {
    var user = $('#login-user').value.trim(), pass = $('#login-pass').value;
    if (!user || !pass) return toast('请输入用户名和密码', 'bad');
    var rep = await rpc('register', { user: user, pass: pass, nick: user });
    if (!rep.ok) return toast(rep.msg || '注册失败', 'bad');
    toast('注册成功，已自动登录', 'ok');
    state.session = { user: rep.data.user.user, token: rep.data.token, nick: rep.data.user.nick || user };
    LS.set('oj_session', state.session);
    LS.set('oj_last_user', user);
    renderSession();
    showTab('problems');
  }

  function doLogout(silent) {
    state.session = null;
    LS.del('oj_session');
    renderSession();
    if (!silent) toast('已退出登录');
    else toast('登录已过期，请重新登录', 'bad');
    showTab('login');
  }

  function renderSession() {
    var bar = $('#session');
    if (state.session) {
      bar.innerHTML = '<b>' + esc(state.session.nick) + '</b> <span class="muted">(' + esc(state.session.user) + ')</span>'
        + ' <span id="session-state" class="muted small"></span>'
        + ' <button class="ghost" id="btn-logout">退出</button>';
      $('#btn-logout').onclick = function () { doLogout(false); };
    } else {
      bar.innerHTML = '<span class="muted">未登录</span>';
    }
  }

  /* -------------------------------------------------------------- 题目 */
  async function loadProblems() {
    var ids = await state.db.getJson('idx:problems', []);
    var rows = [];
    for (var i = 0; i < ids.length; i++) {
      var p = await state.db.getJson('prob:' + ids[i], null);
      if (p) rows.push(p);
    }
    state.problems = rows;
    var box = $('#problem-list');
    if (!rows.length) { box.innerHTML = '<p class="muted">云端还没有题目。管理员先执行：bash tools/oj.sh seed</p>'; return; }
    box.innerHTML = rows.map(function (p) {
      var solved = state.session && (state.session.solved || []).indexOf(p.pid) >= 0;
      return '<div class="card problem" data-pid="' + esc(p.pid) + '">'
        + '<div class="prow"><span class="pid">' + esc(p.pid) + '</span>'
        + '<span class="ptitle">' + esc(p.title) + '</span>'
        + (solved ? '<span class="badge ac">已通过</span>' : '')
        + '<span class="badge">' + esc(p.difficulty || '') + '</span></div>'
        + '<div class="muted small">时限 ' + (p.time_limit_ms / 1000) + 's · 内存 ' + Math.round((p.memory_limit_kb || 0) / 1024)
        + 'MB · ' + (p.case_count || 0) + ' 个测试点 · 满分 ' + (p.total_score || 100)
        + ' · rev ' + esc(p.rev || '-') + '</div></div>';
    }).join('');
    $$('.problem').forEach(function (el) {
      el.onclick = function () { openProblem(el.dataset.pid); };
    });
  }

  async function openProblem(pid) {
    var p = await state.db.getJson('prob:' + pid, null);
    if (!p) return toast('题目不存在: ' + pid, 'bad');
    state.current = p;
    $('#p-pid').textContent = p.pid;
    $('#p-title').textContent = p.title;
    $('#p-meta').textContent = '时限 ' + (p.time_limit_ms / 1000) + 's · 内存 ' + Math.round((p.memory_limit_kb || 0) / 1024)
      + 'MB · 输出上限 ' + Math.round((p.output_limit_kb || 0) / 1024) + 'MB · 比较方式 ' + (p.checker || 'tokens')
      + ' · rev ' + (p.rev || '-');
    $('#p-statement').textContent = p.statement_md || p.statement || '（无题面）';
    var samples = p.samples || [];
    $('#p-samples').innerHTML = samples.map(function (s, i) {
      return '<div class="sample"><div class="muted small">样例 ' + (i + 1) + '</div>'
        + '<pre>输入：\n' + esc(s.in) + '输出：\n' + esc(s.out) + '</pre></div>';
    }).join('');
    showTab('submit');
  }

  /* -------------------------------------------------------------- 提交 */
  async function doSubmit() {
    if (!state.session) return toast('请先登录', 'bad');
    if (!state.current) return toast('请先选择题目', 'bad');
    var code = $('#code').value;
    if (!code.trim()) return toast('代码不能为空', 'bad');
    if (!state.judgePubJwk) return toast('云端没有判题机公钥（先启动判题机）', 'bad');

    var pid = state.current.pid, sid = newSid();
    var langId = $('#lang').value;
    var panel = openResultPanel(sid, pid);
    // 先把源码在本地留一份：即使网络失败/判题机清掉云端密文，代码也不会丢
    SRC.put(sid, { pid: pid, lang: langId, code: code, ts: nowSec() });
    try {
      log('info', 'SID=' + sid + ' 使用判题机公钥 ' + state.judgeFp + ' 加密源码（' + code.length + ' 字符）…');
      var env = await C.seal(state.judgePubJwk, code, { to: state.judgeFp });
      var chunks = env.c.splice(0, env.c.length);
      // 分组成多个标签：每组 ≤ chunkChars，避免单值超限
      var perTag = Math.max(1, Math.floor(state.db.cfg.chunkChars / 345));
      var groups = [];
      for (var i = 0; i < chunks.length; i += perTag) groups.push(chunks.slice(i, i + perTag).join('\n'));
      for (var g = 0; g < groups.length; g++) await state.db.setRaw('code:' + sid + ':' + g, groups[g]);
      await state.db.putJson('code:' + sid, {
        chunked: true, n: groups.length, size: code.length, base: 'code:' + sid + ':',
        alg: env.alg, enc: env.enc, sha256: env.sha256, to: state.judgeFp,
        state: 'sealed', ts: nowSec()
      });
      log('ok', '密文已入库：' + groups.length + ' 个分片标签 code:' + sid + ':0…' + (groups.length - 1));

      await state.db.putJson('sub:' + sid, {
        sid: sid, user: state.session.user, pid: pid, lang: langId,
        status: 'pending', ts: nowSec(), judge: '', verdict: '', score: 0,
        time_ms: 0, memory_kb: 0, cases_passed: 0, case_count: 0, msg: '排队中',
        prob_rev: state.current.rev || '', attempt: 0, lease_token: '', lease_until: 0,
        rejudge: '', enc: 'RSA-OAEP-256', client_pubkey: state.clientPubJwk
      });
      await state.db.putJson('q:' + sid, {
        sid: sid, ts: nowSec(), pid: pid, lang: langId, user: state.session.user
      });
      log('ok', '已入队 q:' + sid + '，等待判题机 3 秒轮询取走…');

      watchResult(sid, panel);
    } catch (e) {
      log('err', '提交失败: ' + e.message);
      toast('提交失败: ' + e.message, 'bad');
    }
  }

  function openResultPanel(sid, pid) {
    var host = $('#watch-list');
    var el = document.createElement('div');
    el.className = 'card watch';
    el.id = 'watch-' + sid;
    el.innerHTML = '<div class="prow"><span class="pid">' + esc(sid) + '</span>'
      + '<span class="ptitle">' + esc(pid) + '</span><span class="badge" data-role="status">排队中</span></div>'
      + '<div class="muted small" data-role="code">code:' + esc(sid) + ' → 待判题机取码</div>'
      + '<div data-role="detail"></div>';
    host.prepend(el);
    return el;
  }

  function watchResult(sid, panel) {
    var timer = setInterval(function () { pollOnce(sid, panel); }, 1500);
    state.watch.push({ sid: sid, timer: timer });
    pollOnce(sid, panel);
  }

  async function pollOnce(sid, panel) {
    if (!panel) panel = $('#watch-' + sid);
    if (!panel) return;
    try {
      var sub = await state.db.getJson('sub:' + sid, null);
      var codeTag = await state.db.getJson('code:' + sid, null);
      var status = (sub && sub.status) || 'pending';
      var badge = panel.querySelector('[data-role="status"]');
      var codeLine = panel.querySelector('[data-role="code"]');
      badge.textContent = status + (sub && sub.verdict ? ' · ' + sub.verdict : '');
      badge.className = 'badge ' + (sub && sub.verdict === 'AC' ? 'ac' : (status === 'done' ? 'warn' : ''));
      if (codeTag && codeTag.state) {
        codeLine.textContent = 'code:' + sid + ' → ' + codeTag.state
          + (codeTag.verdict ? '（' + codeTag.verdict + '）' : '') + ' · 密文分片已由判题机清除';
      }
      if (status !== 'done' && status !== 'failed') return;

      clearInterval((state.watch.find(function (w) { return w.sid === sid; }) || {}).timer);
      var payload = await state.db.getJson('res:' + sid, null);
      var detail = panel.querySelector('[data-role="detail"]');
      if (!payload) { detail.innerHTML = '<p class="muted">还没有结果</p>'; return; }

      var full = payload, sigOk = null;
      if (payload.state === 'sealed' && payload.sealed_env) {
        var man = payload.sealed_env;
        var body = '';
        for (var i = 0; i < (man.n || 0); i++) body += (await state.db.getRaw('res:' + sid + ':' + i, '')) || '';
        var env = Object.assign({}, man, { c: body.split('\n').filter(function (x) { return x.trim(); }) });
        var text = await C.openSealed(state.clientKeys.privateKey, env);
        full = JSON.parse(text);
        if (man.sig && state.judgePubJwk) {
          sigOk = await C.verifySignature(state.judgePubJwk, text, man.sig);
        }
        log('ok', '结果已用本机私钥解密' + (sigOk === null ? '' : '，判题机签名校验：' + (sigOk ? '通过' : '失败！')));
      }
      renderResult(panel, sub, full, sigOk, payload);
    } catch (e) {
      log('err', '轮询 ' + sid + ' 出错: ' + e.message);
    }
  }

  function renderResult(panel, sub, full, sigOk, payload) {
    var detail = panel.querySelector('[data-role="detail"]');
    var v = full.verdict || (sub && sub.verdict) || '?';
    var cls = v === 'AC' ? 'ac' : (v === 'PAC' ? 'warn' : 'bad');
    var html = '<div class="verdict ' + cls + '">' + esc(v) + '</div>'
      + '<div class="muted small">分数 ' + esc(full.score) + ' · 用时 ' + esc(full.time_ms || sub.time_ms)
      + 'ms · 内存 ' + esc(full.memory_kb || sub.memory_kb) + 'KB'
      + (sigOk === null ? '' : ' · 签名 ' + (sigOk ? '<span class="ok">有效</span>' : '<span class="bad">无效</span>'))
      + '</div>';
    if (full.cases && full.cases.length) {
      html += '<table class="cases"><thead><tr><th>#</th><th>结果</th><th>用时</th><th>内存</th><th>信息</th></tr></thead><tbody>'
        + full.cases.map(function (c, i) {
          var extra = c.stderr
            ? '<details class="stderr"><summary>错误输出</summary><pre>' + esc(c.stderr) + '</pre></details>'
            : '';
          return '<tr><td>' + esc(c.i) + '</td><td class="' + (c.verdict === 'AC' ? 'ac' : 'bad') + '">' + esc(c.verdict)
            + '</td><td>' + esc(c.time_ms) + 'ms</td><td>' + esc(c.memory_kb) + 'KB</td><td class="small">'
            + esc(short(c.msg, 220)) + extra + '</td></tr>';
        }).join('') + '</tbody></table>';
    }
    if (full.compile_log) {
      html += '<details><summary>编译日志</summary><pre>' + esc(full.compile_log) + '</pre></details>';
    }
    // 我的代码：优先本地存档，其次服务端随结果加密回来的源码
    var sidKey = (sub && sub.sid) || (full && full.sid) || (payload && payload.sid) || '';
    var local = SRC.get(sidKey);
    var srcText = (local && local.code) || full.source || '';
    var srcFrom = (local && local.code) ? '本地存档' : (full.source ? '判题机加密回传' : '');
    if (srcText) {
      html += '<details class="src" open><summary>我的代码（' + esc(srcFrom) + '，' +
        srcText.length + ' 字符）<button class="ghost" data-role="copy">复制</button></summary>'
        + '<pre class="code">' + esc(srcText) + '</pre></details>';
    } else {
      html += '<p class="muted small">这台浏览器没有该提交的源码副本'
        + '（判题机按隐私设计已清除云端密文；换浏览器或清过缓存就会这样）。</p>';
    }
    detail.innerHTML = html;
    var copyBtn = detail.querySelector('[data-role="copy"]');
    if (copyBtn) {
      copyBtn.onclick = function (e) {
        e.preventDefault();
        navigator.clipboard.writeText(srcText).then(
          function () { toast('代码已复制', 'ok'); },
          function () { toast('复制失败，请手动选中', 'bad'); });
      };
    }
    toast('评测完成：' + v, v === 'AC' ? 'ok' : 'bad');
  }

  /* ------------------------------------------------------- 我的提交/榜单 */
  async function loadMine() {
    var box = $('#mine-list');
    if (!state.session) { box.innerHTML = '<p class="muted">请先登录</p>'; return; }
    box.innerHTML = '<p class="muted">查询中…</p>';
    var rep = await rpc('mysubs', { limit: 20 });
    if (!rep.ok) { box.innerHTML = '<p class="muted">' + esc(rep.msg) + '</p>'; return; }
    var subs = (rep.data && rep.data.subs) || [];
    if (!subs.length) { box.innerHTML = '<p class="muted">还没有提交</p>'; return; }
    box.innerHTML = subs.map(function (s) {
      return '<div class="card sub" data-sid="' + esc(s.sid) + '">'
        + '<div class="prow"><span class="pid">' + esc(s.sid) + '</span>'
        + '<span class="ptitle">' + esc(s.pid) + '</span>'
        + '<span class="badge ' + (s.verdict === 'AC' ? 'ac' : '') + '">' + esc(s.verdict || s.status) + '</span></div>'
        + '<div class="muted small">' + esc(s.lang) + ' · 分数 ' + esc(s.score) + ' · ' + esc(s.time_ms) + 'ms · ' + esc(short(s.msg, 60)) + '</div></div>';
    }).join('');
    $$('.sub').forEach(function (el) {
      el.onclick = function () {
        var panel = openResultPanel(el.dataset.sid, '');
        panel.querySelector('[data-role="status"]').textContent = '读取中';
        pollOnce(el.dataset.sid, panel);
      };
    });
  }

  async function loadRank() {
    var box = $('#rank-body');
    box.innerHTML = '<tr><td colspan="5" class="muted">查询中…</td></tr>';
    var rank = await state.db.getJson('rank', null);
    if (!rank || !rank.order) { box.innerHTML = '<tr><td colspan="5" class="muted">暂无榜单（判题机还没刷新）</td></tr>'; return; }
    box.innerHTML = rank.order.map(function (r) {
      return '<tr><td>' + esc(r.rank) + '</td><td>' + esc(r.nick || r.user) + '</td>'
        + '<td><b>' + esc(r.score) + '</b></td><td>' + esc(r.ac) + '</td><td>' + esc(r.submit) + '</td></tr>';
    }).join('');
  }

  async function loadJudgeStatus() {
    var box = $('#judge-status');
    box.textContent = '查询中…';
    var tags = await state.db.search('judge:', { count: 100, type: 'both' });
    var rows = Object.keys(tags).filter(function (k) { return k.indexOf('judge:') === 0; })
      .map(function (k) { try { return JSON.parse(tags[k]); } catch (e) { return null; } })
      .filter(Boolean);
    if (!rows.length) { box.textContent = '没有在线的判题机'; return; }
    box.innerHTML = rows.map(function (j) {
      return '<div class="card"><b>' + esc(j.id) + '</b> @ ' + esc(j.host)
        + '<div class="muted small">workers=' + esc(j.workers) + ' busy=' + esc(j.busy)
        + ' langs=' + esc((j.langs || []).join(',')) + ' 已判 ' + esc((j.stats || {}).judged)
        + ' · 心跳 ' + new Date((j.ts || 0) * 1000).toLocaleTimeString() + '</div></div>';
    }).join('');
  }

  /* ---------------------------------------------------------------- 绑定 */
  /* ------------------------------------------------------------ 连接设置 */
  function renderSetup() {
    var ok = state.db.hasCredentials();
    var box = $('#setup-status');
    if (!box) return;
    box.innerHTML = ok
      ? '<div class="prow"><span class="badge ac">已配置</span>'
        + '<span class="muted small">API ' + esc(state.db.cfg.api) + ' · user '
        + esc(state.db.cfg.user) + ' · secret ' + esc(String(state.db.cfg.secret).slice(0, 3)) + '***</span></div>'
      : '<div class="prow"><span class="badge warn">未配置</span>'
        + '<span class="muted small">填好下面的三项并保存，本页就能用了</span></div>';
    if ($('#cfg-api')) {
      if (!$('#cfg-api').value) $('#cfg-api').value = state.db.cfg.api || '';
      if (!$('#cfg-user').value && ok) $('#cfg-user').value = state.db.cfg.user || '';
    }
  }

  async function saveCredentials() {
    var api = $('#cfg-api').value.trim() || 'https://tinywebdb.appinventor.space/api';
    var user = $('#cfg-user').value.trim();
    var secret = $('#cfg-secret').value.trim();
    if (!user || !secret) return toast('user 和 secret 都要填', 'bad');
    state.db.saveCredentials(api, user, secret);
    log('ok', '凭据已保存在本机浏览器（api=' + api + ' user=' + user + '）');
    toast('已保存，正在测试连通性…', 'ok');
    var info = await state.db.ping();
    if (!info.ok) {
      toast('连不上：' + info.error, 'bad');
      $('#health').textContent = '云端不可用';
      $('#health').className = 'pill bad';
      return;
    }
    $('#health').textContent = '云端可用 · 共 ' + info.count + ' 个标签';
    $('#health').className = 'pill ok';
    toast('连接成功（' + info.count + ' 个标签）', 'ok');
    renderSetup();
    await refreshJudgeKey();
    await loadProblems();
    showTab('problems');
  }

  async function testCredentials() {
    var info = await state.db.ping();
    toast(info.ok ? ('连通正常，' + info.count + ' 个标签，' + info.ms + 'ms')
                  : ('连不上：' + info.error), info.ok ? 'ok' : 'bad');
  }

  function bind() {
    $$('.tab').forEach(function (t) { t.onclick = function () { showTab(t.dataset.tab); }; });
    $('#btn-login').onclick = doLogin;
    $('#btn-register').onclick = doRegister;
    $('#btn-submit').onclick = doSubmit;
    $('#btn-refresh-key').onclick = async function () { await refreshJudgeKey(); toast('已刷新判题机公钥 ' + state.judgeFp, 'ok'); };
    $('#btn-reload-problems').onclick = loadProblems;
    $('#btn-judge-status').onclick = loadJudgeStatus;
    $('#btn-clear-log').onclick = function () { $('#log').innerHTML = ''; };
    if ($('#btn-save-creds')) $('#btn-save-creds').onclick = saveCredentials;
    if ($('#btn-test-creds')) $('#btn-test-creds').onclick = testCredentials;
    if ($('#btn-clear-creds')) $('#btn-clear-creds').onclick = function () {
      state.db.clearCredentials();
      toast('已清除本机凭据，请重新填写', 'ok');
      $('#cfg-user').value = ''; $('#cfg-secret').value = '';
      renderSetup();
      showTab('setup');
    };
    $('#login-pass').addEventListener('keydown', function (e) { if (e.key === 'Enter') doLogin(); });
  }

  window.addEventListener('DOMContentLoaded', function () {
    if (!C || !C.available) {
      document.body.innerHTML = '<div class="wrap"><h1>浏览器不支持 Web Crypto</h1>'
        + '<p>请用现代浏览器（Chrome/Edge/Firefox）打开本页面，且不要用 <code>http://</code> 访问非 localhost 地址。</p></div>';
      return;
    }
    bind();
    boot().catch(function (e) { toast('初始化失败: ' + e.message, 'bad'); });
  });
})();
