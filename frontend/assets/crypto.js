/* ============================================================================
 *  OJCrypto —— 浏览器端非对称加密（Web Crypto API，无任何第三方库）
 *
 *  设计：代码先用 RSA-OAEP(SHA-256, 2048) 分块加密再进 TinyWebDB，
 *        只有持有私钥的判题机才能解密；判题结果同样用客户端公钥加密回传。
 *        纯非对称，不引入对称密钥，前后端算法严格对齐、可互测。
 *
 *  同一份代码在浏览器和 Node 里都能跑（Node 19+ 自带 globalThis.crypto）。
 * ==========================================================================*/
(function (root) {
  'use strict';

  var W = (typeof globalThis !== 'undefined' && globalThis.crypto && globalThis.crypto.subtle)
    ? globalThis.crypto
    : (typeof require === 'function' ? require('crypto').webcrypto : null);

  var ALG = 'RSA-OAEP-256';
  var ENC = 'b64url-chunk-v1';
  var KEY_USAGE = { name: 'RSA-OAEP', hash: 'SHA-256' };
  var MAX_CHUNK_BYTES = 190;          // 2048 位 / SHA-256：k - 2*hLen - 2

  /* ---------------------------------------------------------------- 编码 */
  function bytesToB64u(bytes) {
    var bin = '';
    var view = new Uint8Array(bytes);
    for (var i = 0; i < view.length; i++) bin += String.fromCharCode(view[i]);
    return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function b64uToBytes(text) {
    var t = String(text || '').replace(/-/g, '+').replace(/_/g, '/');
    while (t.length % 4) t += '=';
    var bin = atob(t);
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function utf8Bytes(text) { return new TextEncoder().encode(text); }

  function bytesToUtf8(bytes) { return new TextDecoder('utf-8').decode(bytes); }

  async function sha256Hex(bytes) {
    var digest = await W.subtle.digest('SHA-256', bytes);
    var out = '';
    new Uint8Array(digest).forEach(function (b) { out += ('0' + b.toString(16)).slice(-2); });
    return out;
  }

  /* ---------------------------------------------------------------- 密钥 */
  async function generateKeyPair(bits) {
    return W.subtle.generateKey(
      { name: 'RSA-OAEP', modulusLength: bits || 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' },
      true, ['encrypt', 'decrypt']);
  }

  async function exportPublicJwk(key) {
    var jwk = await W.subtle.exportKey('jwk', key);
    return { kty: 'RSA', alg: ALG, use: 'enc', key_ops: ['encrypt'], n: jwk.n, e: jwk.e };
  }

  async function exportPrivateJwk(key) {
    var jwk = await W.subtle.exportKey('jwk', key);
    jwk.alg = ALG; jwk.use = 'enc'; jwk.key_ops = ['decrypt'];
    return jwk;
  }

  async function importPublicJwk(jwk) {
    return W.subtle.importKey('jwk', normalise(jwk, false), KEY_USAGE, true, ['encrypt']);
  }

  async function importPrivateJwk(jwk) {
    return W.subtle.importKey('jwk', normalise(jwk, true), KEY_USAGE, true, ['decrypt']);
  }

  function normalise(jwk, priv) {
    var out = { kty: 'RSA', n: jwk.n, e: jwk.e };
    if (priv) {
      ['d', 'p', 'q', 'dp', 'dq', 'qi'].forEach(function (f) {
        if (jwk[f]) out[f] = jwk[f];
      });
    }
    return out;
  }

  async function fingerprint(jwk) {
    return (await sha256Hex(b64uToBytes(jwk.n))).slice(0, 16);
  }

  /* ------------------------------------------------------ 分块加解密 */
  function maxChunkBytes() { return MAX_CHUNK_BYTES; }

  async function seal(publicKey, text, extra) {
    if (typeof publicKey === 'object' && publicKey.n) publicKey = await importPublicJwk(publicKey);
    var data = (typeof text === 'string') ? utf8Bytes(text) : new Uint8Array(text);
    var chunks = [];
    for (var off = 0; off < Math.max(data.length, 1); off += MAX_CHUNK_BYTES) {
      var part = data.subarray(off, off + MAX_CHUNK_BYTES);
      var ct = await W.subtle.encrypt({ name: 'RSA-OAEP' }, publicKey, part);
      chunks.push(bytesToB64u(ct));
    }
    var env = {
      alg: ALG, enc: ENC, n: chunks.length, c: chunks,
      sha256: await sha256Hex(data), size: data.length
    };
    if (extra) Object.keys(extra).forEach(function (k) { env[k] = extra[k]; });
    return env;
  }

  async function openSealed(privateKey, envelope) {
    if (typeof privateKey === 'object' && privateKey.d && !privateKey.usages) {
      privateKey = await importPrivateJwk(privateKey);
    }
    if (!envelope || !envelope.c) throw new Error('信封格式不正确');
    if (envelope.alg && envelope.alg !== ALG && envelope.alg !== 'RSA-OAEP') {
      throw new Error('不支持的信封算法: ' + envelope.alg);
    }
    var total = 0, i;
    var parts = [];
    for (i = 0; i < envelope.c.length; i++) {
      var pt = await W.subtle.decrypt({ name: 'RSA-OAEP' }, privateKey, b64uToBytes(envelope.c[i]));
      parts.push(new Uint8Array(pt));
      total += pt.byteLength;
    }
    var merged = new Uint8Array(total), pos = 0;
    for (i = 0; i < parts.length; i++) { merged.set(parts[i], pos); pos += parts[i].length; }
    if (envelope.sha256 && (await sha256Hex(merged)) !== envelope.sha256) {
      throw new Error('解密后校验失败（数据损坏）');
    }
    return bytesToUtf8(merged);
  }

  /* ------------------------------------------------------------ 验签 */
  async function verifySignature(publicKey, text, signatureB64u) {
    if (typeof publicKey === 'object' && publicKey.n && !publicKey.usages) {
      publicKey = await W.subtle.importKey('jwk',
        { kty: 'RSA', n: publicKey.n, e: publicKey.e, alg: 'RS256' },
        { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, true, ['verify']);
    }
    var data = (typeof text === 'string') ? utf8Bytes(text) : new Uint8Array(text);
    return W.subtle.verify({ name: 'RSASSA-PKCS1-v1_5' }, publicKey, b64uToBytes(signatureB64u), data);
  }

  var API = {
    available: !!W,
    ALG: ALG,
    ENC: ENC,
    maxChunkBytes: maxChunkBytes,
    generateKeyPair: generateKeyPair,
    exportPublicJwk: exportPublicJwk,
    exportPrivateJwk: exportPrivateJwk,
    importPublicJwk: importPublicJwk,
    importPrivateJwk: importPrivateJwk,
    fingerprint: fingerprint,
    seal: seal,
    openSealed: openSealed,
    verifySignature: verifySignature,
    sha256Hex: sha256Hex,
    bytesToB64u: bytesToB64u,
    b64uToBytes: b64uToBytes,
    utf8Bytes: utf8Bytes,
    bytesToUtf8: bytesToUtf8
  };

  root.OJCrypto = API;
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
})(typeof globalThis !== 'undefined' ? globalThis : this);
