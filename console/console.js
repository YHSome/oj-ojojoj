/* ============================================================================
 *  判题机中控台
 *  与后端 tools/console.py 的 /api/* 通信；所有写操作都带 X-OJ-Console 头。
 * ==========================================================================*/
(function () {
  'use strict';

  var TOKEN = new URLSearchParams(location.search).get('token') || '';
  var state = { status: null, timer: null, logTimer: null, busy: false };

  function $(s) { return document.querySelector(s); }
  function $$(s) { return Array.prototype.slice.call(document.querySelectorAll(s)); }
  function esc(s) {
    return String(s === undefined || s === null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function toast(msg, kind) {
    var el = $('#toast');
    el.className = 'toast show ' + (kind || '');
    el.textContent = msg;
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.className = 'toast'; }, 4200);
  }

  async function api(path, body) {
    var opt = {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'X-OJ-Console': '1' }
    };
    if (TOKEN) opt.headers['X-OJ-Token'] = TOKEN;
    if (body !== undefined) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    var resp = await fetch(path, opt);
    var text = await resp.text();
    var data;
    try { data = JSON.parse(text); } catch (e) { throw new Error('中控台返回异常: ' + text.slice(0, 120)); }
    if (!resp.ok && data && data.msg) throw new Error(data.msg);
    return data;
  }

  /* --------------------------------------------------------------- 渲染 */
  function renderStatus(st) {
    state.status = st;
    var dot = $('#dot'), text = $('#state-text'), meta = $('#state-meta');
    var running = st.running, paused = st.paused;
    dot.className = 'dot ' + (running ? (paused ? 'warn' : 'on') : 'off');
    text.textContent = running ? (paused ? '判题机运行中（已暂停接单）' : '判题机运行中')
      : '判题机已停止';
    meta.textContent = running
      ? ('pid ' + st.pid + ' · ' + st.judge_id + ' · 启动于 ' + (st.started || '-') + ' · 主机 ' + (st.host || '-'))
      : '点右侧按钮即可启动；启动后会用配置里的 workers 数接单';

    $('#btn-toggle').textContent = running ? '停止判题机' : '启动判题机';
    $('#btn-toggle').className = 'big ' + (running ? 'danger' : 'primary');
    $('#btn-pause').disabled = !running;
    $('#btn-resume').disabled = !running;
    $('#btn-reload').disabled = !running;

    $('#m-id').textContent = st.judge_id || '-';
    $('#m-pid').textContent = st.pid || '-';
    $('#m-workers').textContent = (st.workers === undefined ? (state.status.editable || [])
      .filter(function (e) { return e.key === 'judge.workers'; }).map(function (e) { return e.value; })[0] : st.workers)
      + ' / ' + (st.busy === undefined || st.busy === null ? '?' : st.busy);
    var cloud = st.cloud || {};
    $('#m-queue').textContent = cloud.queue === undefined ? '-' : cloud.queue;
    $('#m-tags').textContent = cloud.ok ? (cloud.count + '（' + cloud.ms + 'ms）') : '不可达';
    $('#m-langs').textContent = (st.langs || []).join(', ') || '无！';

    var c = $('#cloud');
    c.textContent = cloud.ok ? ('云端正常 · ' + cloud.count + ' 标签') : ('云端异常: ' + (cloud.error || '?'));
    c.className = 'pill ' + (cloud.ok ? 'ok' : 'bad');
    $('#cfg-path').textContent = st.config_path || '';

    renderParams(st.editable || []);
  }

  function renderParams(rows) {
    var host = $('#params');
    if (host.dataset.rendered === '1' && host.childElementCount === rows.length) {
      // 只刷新数值，避免打断正在输入的光标
      rows.forEach(function (r) {
        var el = host.querySelector('[data-key="' + r.key + '"]');
        if (el && document.activeElement !== el) el.value = formatVal(r);
      });
      return;
    }
    host.innerHTML = rows.map(function (r) {
      var flag = /需重启/.test(r.desc) ? ' <span class="tag warn">需重启</span>' : '';
      if (r.type === 'bool') {
        return '<div class="param"><label class="plabel" title="' + esc(r.desc) + '">' + esc(r.key) + flag + '</label>'
          + '<input type="checkbox" data-key="' + esc(r.key) + '" data-type="bool"'
          + (r.value ? ' checked' : '') + '><span class="pdesc">' + esc(r.desc) + '</span></div>';
      }
      return '<div class="param"><label class="plabel" title="' + esc(r.desc) + '">' + esc(r.key) + flag + '</label>'
        + '<input data-key="' + esc(r.key) + '" data-type="' + esc(r.type) + '" value="' + esc(formatVal(r)) + '">'
        + '<span class="pdesc">' + esc(r.desc) + '</span></div>';
    }).join('');
    host.dataset.rendered = '1';
  }

  function formatVal(r) {
    return r.value === null || r.value === undefined ? '' : String(r.value);
  }

  function collectParams() {
    var values = {};
    $$('#params [data-key]').forEach(function (el) {
      values[el.dataset.key] = el.dataset.type === 'bool' ? (el.checked ? 'true' : 'false') : el.value;
    });
    return values;
  }

  function renderActions(list) {
    var host = $('#actions');
    if (host.childElementCount) return;
    host.innerHTML = list.map(function (a) {
      return '<button class="act" data-action="' + esc(a.id) + '">' + esc(a.label) + '</button>';
    }).join('');
    $$('#actions .act').forEach(function (b) {
      b.onclick = function () { runAction(b.dataset.action, b); };
    });
  }

  function showOutput(title, res) {
    var box = $('#out');
    var head = '\u25b6 ' + title + (res.code !== undefined ? '  (exit ' + res.code + ')' : '') + '\n';
    box.textContent = head + (res.out || '') + (res.err ? '\n--- stderr ---\n' + res.err : '');
    box.scrollTop = 0;
  }

  /* --------------------------------------------------------------- 操作 */
  async function refresh() {
    if (state.busy) return;
    try {
      var st = await api('/api/status');
      renderStatus(st);
      renderActions(st.actions || []);
      if (state.timer === null) state.timer = setInterval(refresh, 4000);
      if (state.logTimer === null) state.logTimer = setInterval(function () {
        if ($('#auto-log').checked) loadLog();
      }, 4000);
    } catch (e) {
      toast('读取状态失败: ' + e.message, 'bad');
    }
  }

  async function loadLog() {
    try {
      var r = await api('/api/log?lines=200');
      var box = $('#log');
      var near = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
      box.textContent = (r.lines || []).join('\n') || '（暂无日志）';
      if (near) box.scrollTop = box.scrollHeight;
    } catch (e) { /* 静默 */ }
  }

  async function withBusy(fn) {
    state.busy = true;
    try { return await fn(); } finally { state.busy = false; }
  }

  async function toggleJudge() {
    var running = state.status && state.status.running;
    await withBusy(async function () {
      var btn = $('#btn-toggle');
      btn.disabled = true;
      btn.textContent = running ? '正在优雅停止…' : '正在启动…';
      try {
        var r = running ? await api('/api/stop', {}) : await api('/api/start', {});
        toast(r.msg, r.ok ? 'ok' : 'bad');
      } catch (e) {
        toast(e.message, 'bad');
      }
      btn.disabled = false;
      await refresh();
      loadLog();
    });
  }

  async function runAction(action, btn) {
    if (btn) { btn.disabled = true; btn.classList.add('running'); }
    try {
      var r = await api('/api/action', { action: action });
      showOutput(r.label || action, r);
      toast((r.label || action) + (r.ok ? ' 完成' : ' 失败'), r.ok ? 'ok' : 'bad');
      if (['seed', 'keygen', 'gc', 'archive', 'rank', 'backup'].indexOf(action) >= 0) refresh();
    } catch (e) {
      showOutput(action, { err: e.message });
      toast(e.message, 'bad');
    } finally {
      if (btn) { btn.disabled = false; btn.classList.remove('running'); }
    }
  }

  function bind() {
    $('#btn-toggle').onclick = toggleJudge;
    $('#btn-restart').onclick = async function () {
      await withBusy(async function () {
        toast('正在重启…');
        var r = await api('/api/restart', {});
        toast(r.msg, r.ok ? 'ok' : 'bad');
        await refresh();
      });
    };
    $('#btn-pause').onclick = async function () {
      var r = await api('/api/pause', {}); toast(r.msg, r.ok ? 'ok' : 'bad'); refresh();
    };
    $('#btn-resume').onclick = async function () {
      var r = await api('/api/resume', {}); toast(r.msg, r.ok ? 'ok' : 'bad'); refresh();
    };
    $('#btn-reload').onclick = async function () {
      var r = await api('/api/reload', {}); toast(r.msg, r.ok ? 'ok' : 'bad'); loadLog();
    };
    $('#btn-save').onclick = async function () {
      try {
        var r = await api('/api/save_config', { values: collectParams() });
        toast(r.msg, r.ok ? 'ok' : 'bad');
        showOutput('保存配置', { out: (r.changed || []).join('\n') || r.msg, code: r.ok ? 0 : 1 });
        $('#params').dataset.rendered = '';
        refresh();
      } catch (e) { toast(e.message, 'bad'); }
    };
    $('#btn-reset').onclick = function () { $('#params').dataset.rendered = ''; refresh(); };
    $('#btn-clear-out').onclick = function () { $('#out').textContent = '（执行动作后这里显示输出）'; };
    $('#btn-log-now').onclick = loadLog;
    $('#btn-qsubmit').onclick = async function () {
      var b = $('#btn-qsubmit');
      b.disabled = true;
      try {
        var r = await api('/api/quick_submit', {
          user: $('#qs-user').value, pid: $('#qs-pid').value, sample: $('#qs-sample').value
        });
        showOutput('明文提交日志', r);
        toast(r.ok ? '提交并判题完成，见输出区' : '提交失败', r.ok ? 'ok' : 'bad');
      } catch (e) { toast(e.message, 'bad'); }
      finally { b.disabled = false; }
    };
    setInterval(function () {
      $('#clock').textContent = new Date().toLocaleTimeString();
    }, 1000);
  }

  window.addEventListener('DOMContentLoaded', function () {
    bind();
    refresh().then(loadLog);
  });
})();
