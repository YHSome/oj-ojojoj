/* ============================================================================
 *  前后端加密互测（Node 的 WebCrypto 与浏览器是同一套 API）
 *
 *    node tools/test_crypto_interop.js <阶段> <文件>
 *      phase=encrypt : 生成密钥对，加密 code.txt，输出 {pub, priv, env}
 *      phase=decrypt : 用 Python 生成的私钥解密 {env}，并验签
 * ==========================================================================*/
const fs = require('fs');
const path = require('path');
const C = require(path.join(__dirname, '..', 'frontend', 'assets', 'crypto.js'));

(async () => {
  if (!C.available) { console.error('WebCrypto 不可用'); process.exit(1); }
  const phase = process.argv[2] || 'encrypt';
  const file = process.argv[3];

  if (phase === 'encrypt') {
    const code = fs.readFileSync(file, 'utf8');
    const kp = await C.generateKeyPair(2048);
    const pub = await C.exportPublicJwk(kp.publicKey);
    const priv = await C.exportPrivateJwk(kp.privateKey);
    const env = await C.seal(kp.publicKey, code);
    const out = {
      pub: pub, priv: priv, env: env,
      fingerprint: await C.fingerprint(pub),
      code_sha256: await C.sha256Hex(C.utf8Bytes(code)),
      code_bytes: C.utf8Bytes(code).length
    };
    fs.writeFileSync(file + '.js-envelope.json', JSON.stringify(out));
    console.log('[node] 已加密 ' + out.code_bytes + ' 字节，分块 ' + env.n + '，指纹 ' + out.fingerprint);
    return;
  }

  if (phase === 'decrypt') {
    const payload = JSON.parse(fs.readFileSync(file, 'utf8'));
    const privKey = await C.importPrivateJwk(payload.priv);
    const text = await C.openSealed(privKey, payload.env);
    const sha = await C.sha256Hex(C.utf8Bytes(text));
    console.log('[node] 解密 ' + C.utf8Bytes(text).length + ' 字节，sha256=' + sha);
    console.log('[node] 与期望一致: ' + (sha === payload.expect_sha256));
    if (payload.judge_pub && payload.signature) {
      const ok = await C.verifySignature(payload.judge_pub, payload.signed_text, payload.signature);
      console.log('[node] 判题机签名有效: ' + ok);
    }
    process.exit(sha === payload.expect_sha256 ? 0 : 1);
  }

  console.error('未知阶段: ' + phase);
  process.exit(2);
})().catch(e => { console.error('[node] 失败:', e); process.exit(1); });
