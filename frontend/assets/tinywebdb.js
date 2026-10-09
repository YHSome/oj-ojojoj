/* ============================================================================
 *  tinywebdb.js —— TinyWebDB 纯前端客户端（浏览器直连，无需后端代理）
 *
 *  实测要点（全部写进代码，不改就会踩坑）：
 *   1. CORS 开放（Access-Control-Allow-Origin: *），可以直连；但**不能加自定义请求头**，
 *      否则会触发预检而服务端没有 Access-Control-Allow-Headers → 请求失败。
 *      因此只用 application/x-www-form-urlencoded 的"简单请求"。
 *   2. search 必须显式传 count（默认只返回 1 条），单次上限 100，返回顺序不可依赖。
 *   3. 值里不能出现真换行/单引号/反斜杠（会破坏服务端 JSON）→ SafeText 转义。
 *   4. 单值 10000 字符可用、20000 字符会被服务端破坏 → 长内容必须分片。
 *   5. 会返回 503 限流 → 指数退避重试。
 * ==========================================================================*/
(function (root) {
  'use strict';

  /* 凭据优先级：assets/config.js（不入库） > 这里的占位默认值。
     公开仓库里不含任何真实 user/secret，避免把自己的云端写权限发到网上。 */
  var LOCAL_CFG = (root.OJ_CONFIG && typeof root.OJ_CONFIG === 'object') ? root.OJ_CONFIG : {};

  var DEFAULTS = {
    api: LOCAL_CFG.api || 'https://tinywebdb.appinventor.space/api',
    user: LOCAL_CFG.user || 'YOUR_USER',
    secret: LOCAL_CFG.secret || 'YOUR_SECRET',
    minGapMs: LOCAL_CFG.minGapMs || 150,   // 本客户端两次请求的最小间隔（对社区服务礼貌一点）
    retries: LOCAL_CFG.retries || 4,
    chunkChars: LOCAL_CFG.chunkChars || 8000,  // 单值分片上限（保守取 8000 < 实测 10000）
    log: function () {}
  };

  var SAFE_RE = /[%\\'\x00-\x1f\x7f]/g;
  var HEX = '0123456789abcdefABCDEF';

  function safe(text) {
    if (text === null || text === undefined) return '';
    return String(text).replace(SAFE_RE, function (ch) {
      return '%' + ch.charCodeAt(0).toString(16).toUpperCase().padStart(2, '0');
    });
  }

  function unsafe(text) {
    if (typeof text !== 'string' || text.indexOf('%') < 0) return text;
    var out = '', i = 0, n = text.length;
    while (i < n) {
      var c = text[i];
      if (c === '%' && i + 3 <= n) {
        var h = text.substr(i + 1, 2);
        if (HEX.indexOf(h[0]) >= 0 && HEX.indexOf(h[1]) >= 0) {
          out += String.fromCharCode(parseInt(h, 16));
          i += 3;
          continue;
        }
      }
      out += c;
      i += 1;
    }
    return out;
  }

  function safeObj(obj) {
    if (typeof obj === 'string') return safe(obj);
    if (Array.isArray(obj)) return obj.map(safeObj);
    if (obj && typeof obj === 'object') {
      var out = {};
      Object.keys(obj).forEach(function (k) { out[safe(k)] = safeObj(obj[k]); });
      return out;
    }
    return obj;
  }

  function unsafeObj(obj) {
    if (typeof obj === 'string') return unsafe(obj);
    if (Array.isArray(obj)) return obj.map(unsafeObj);
    if (obj && typeof obj === 'object') {
      var out = {};
      Object.keys(obj).forEach(function (k) { out[unsafe(k)] = unsafeObj(obj[k]); });
      return out;
    }
    return obj;
  }

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  /* ------------------------------------------------------------------ DB */
  function DB(options) {
    this.cfg = Object.assign({}, DEFAULTS, options || {});
    this._next = 0;
    this.stats = { calls: 0, retries: 0, errors: 0 };
  }

  DB.prototype._throttle = async function () {
    var now = Date.now();
    var wait = this._next - now;
    if (wait > 0) await sleep(wait);
    this._next = Math.max(Date.now(), this._next) + this.cfg.minGapMs;
  };

  DB.prototype.call = async function (action, params) {
    var body = new URLSearchParams();
    body.set('user', this.cfg.user);
    body.set('secret', this.cfg.secret);
    body.set('action', action);
    Object.keys(params || {}).forEach(function (k) {
      if (params[k] !== undefined && params[k] !== null) body.set(k, String(params[k]));
    });

    var attempt = 0, lastErr = null;
    while (attempt <= this.cfg.retries) {
      attempt += 1;
      await this._throttle();
      try {
        this.stats.calls += 1;
        var resp = await fetch(this.cfg.api, {
          method: 'POST',
          // 只用 form-urlencoded：这是 CORS 安全列表内的"简单请求"，不会触发预检
          headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
          body: body.toString()
        });
        if (resp.status === 503 || resp.status === 429 || resp.status >= 500) {
          throw new Error('HTTP ' + resp.status);
        }
        var text = (await resp.text()).trim();
        if (!text) return null;
        try {
          return JSON.parse(text);
        } catch (e) {
          throw new Error('服务端返回不是 JSON（值里可能含换行/单引号）: ' + text.slice(0, 120));
        }
      } catch (err) {
        lastErr = err;
        this.stats.errors += 1;
        if (attempt > this.cfg.retries) break;
        this.stats.retries += 1;
        var backoff = Math.min(8000, 400 * Math.pow(2, attempt - 1)) * (0.7 + Math.random() * 0.6);
        this.cfg.log('warn', '请求失败(' + err.message + ')，' + Math.round(backoff) + 'ms 后重试 ' + attempt + '/' + this.cfg.retries);
        await sleep(backoff);
      }
    }
    throw lastErr || new Error('请求失败: ' + action);
  };

  DB.prototype.getRaw = async function (tag, def) {
    var val = await this._getEncoded(tag, null);
    if (val === null || val === undefined) return def === undefined ? null : def;
    if (typeof val !== 'string') return JSON.stringify(val);   // 服务端把数组解析后返回
    return unsafe(val);      // 与后端 get_raw 对称：读出后还原安全文本层
  };

  /* 取"云端原文"（仍是安全编码态）。JSON 值必须先解析再反转义，
     否则 %0A 还原成真换行后 JSON.parse 会直接失败（题面就踩过这个坑）。 */
  DB.prototype._getEncoded = async function (tag, def) {
    var res = await this.call('get', { tag: tag });
    var missing = def === undefined ? null : def;
    if (!res || typeof res !== 'object') return missing;
    var val = null, found = false;
    if (Object.prototype.hasOwnProperty.call(res, tag)) { val = res[tag]; found = true; }
    else {
      var keys = Object.keys(res);
      if (!keys.length) return missing;
      val = res[keys[0]]; found = true;
    }
    // 云端 delete 是软删除：search 里没了，但 get 会返回字符串 "null"
    if (!found || val === null || val === 'null') return missing;
    return val;
  };

  DB.prototype.setRaw = async function (tag, value) {
    var res = await this.call('update', { tag: tag, value: value === null || value === undefined ? '' : String(value) });
    return !!(res && String(res.status).toLowerCase() === 'success');
  };

  DB.prototype.del = function (tag) { return this.call('delete', { tag: tag }); };

  DB.prototype.count = async function () {
    var res = await this.call('count', {});
    return res && res.count !== undefined ? parseInt(res.count, 10) : 0;
  };

  DB.prototype.search = async function (tag, opts) {
    opts = opts || {};
    var res = await this.call('search', {
      tag: tag || '', no: opts.no || 1, count: Math.min(opts.count || 100, 100),
      type: opts.type || 'both'
    });
    if (!res || typeof res !== 'object') return {};
    if (Array.isArray(res)) return { __tags__: res };
    if (typeof res.tag === 'object' && res.tag && res.tag.length !== undefined && Object.keys(res).length === 1) {
      return { __tags__: res.tag };
    }
    return res;
  };

  /* ------------------------------------------------- JSON + 分片读写 */
  DB.prototype.getJson = async function (tag, def) {
    var missing = def === undefined ? null : def;
    var encoded = await this._getEncoded(tag, null);
    if (encoded === null || encoded === undefined || encoded === '') return missing;
    // 坑 1：云端会把「JSON 数组」直接解析成数组返回（对象则仍是字符串）。
    //       这时不能再 JSON.parse（数组会被强转成 "a,b,c" 而报错）。
    if (typeof encoded !== 'string') return unsafeObj(encoded);
    try {
      // 坑 2：顺序必须是「先 JSON.parse 再反转义」：先反转义会把 %0A 变成真换行，
      //       而 JSON 字符串里不允许裸换行，解析必定失败（题面/编译日志都含换行）。
      return unsafeObj(JSON.parse(encoded));
    } catch (e) {
      this.cfg.log('warn', 'getJson(' + tag + ') 解析失败: ' + e.message);
      return missing;
    }
  };

  DB.prototype.putJson = function (tag, obj) {
    return this.setRaw(tag, JSON.stringify(safeObj(obj)));
  };

  /* 长内容分片：tag = 清单，tag:0/1/2… = 分片（与后端 store.store_chunked 完全一致） */
  DB.prototype.putChunked = async function (baseTag, text, extra) {
    var limit = this.cfg.chunkChars, t = text || '';
    var parts = [];
    for (var i = 0; i < Math.max(t.length, 1); i += limit) parts.push(t.substr(i, limit));
    var manifest = Object.assign({
      chunked: true, n: parts.length, size: t.length, base: baseTag + ':',
      ts: Math.floor(Date.now() / 1000)
    }, extra || {});
    for (var j = 0; j < parts.length; j++) {
      await this.setRaw(baseTag + ':' + j, parts[j]);
    }
    await this.setRaw(baseTag, JSON.stringify(manifest));
    return manifest;
  };

  DB.prototype.getChunked = async function (baseTag) {
    var encoded = await this._getEncoded(baseTag, '');
    if (!encoded) return [null, ''];
    if (typeof encoded !== 'string') return [unsafeObj(encoded), ''];
    var man = null;
    try { man = unsafeObj(JSON.parse(encoded)); } catch (e) { return [null, unsafe(encoded)]; }
    if (!man || !man.chunked) return [null, unsafe(encoded)];
    var out = '';
    for (var i = 0; i < (man.n || 0); i++) {
      var part = await this._getEncoded(baseTag + ':' + i, '');
      out += (typeof part === 'string' ? unsafe(part) : '');
    }
    return [man, out];
  };

  DB.prototype.dropChunked = async function (baseTag, n) {
    for (var i = 0; i < (n || 0); i++) await this.del(baseTag + ':' + i);
    await this.del(baseTag);
  };

  root.OJDB = DB;
  root.OJText = { safe: safe, unsafe: unsafe, safeObj: safeObj, unsafeObj: unsafeObj };
})(typeof globalThis !== 'undefined' ? globalThis : this);
