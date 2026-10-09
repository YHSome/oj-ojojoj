# -*- coding: utf-8 -*-
"""纯标准库 RSA 非对称加密：RSA-OAEP(SHA-256) 分块加密 + RSASSA-PKCS1-v1_5 签名。

为什么要自己写：本机没有 `cryptography` 依赖，而 TinyWebDB 是明文 KV，
前端提交的代码必须先用**非对称加密**封起来（只有判题机持有私钥）。
纯 Python 的 pow() 对大整数模幂足够快（2048 位一次约 1~3 ms）。

对外接口（前后端一致，前端用浏览器 WebCrypto 的 RSA-OAEP/SHA-256 即可互通）：
  * generate_keypair(bits)          -> 私钥 JWK（含公钥字段）
  * public_jwk(priv)                -> 只含公钥的 JWK（发布到云端 oj:pubkey）
  * oaep_encrypt(jwk, data) / oaep_decrypt(jwk, em)
  * seal(jwk, data)                 -> {"alg","enc","n","c":[b64url,...]}   分块密文信封
  * open_sealed(jwk, envelope)      -> bytes
  * sign(jwk, data) / verify(jwk, data, sig)
  * fingerprint(jwk)                -> 公钥指纹（用于校验"结果发给谁"）
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets

ALG = "RSA-OAEP-256"
ENC = "b64url-chunk-v1"
HLEN = 32                      # SHA-256
SHA256_DIGESTINFO = bytes.fromhex("3031300d060960864801650304020105000420")


# ------------------------------------------------------------------ 工具
def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def b64u_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def i2osp(x: int, length: int) -> bytes:
    return x.to_bytes(length, "big")


def os2ip(b: bytes) -> int:
    return int.from_bytes(b, "big")


def mgf1(seed: bytes, length: int, hash_name="sha256") -> bytes:
    hlen = hashlib.new(hash_name).digest_size
    out = b""
    counter = 0
    while len(out) < length:
        out += hashlib.new(hash_name, seed + counter.to_bytes(4, "big")).digest()
        counter += 1
    return out[:length]


def xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


# ------------------------------------------------------------ OAEP 填充
def oaep_encode(message: bytes, k: int, label: bytes = b"", hash_name="sha256") -> bytes:
    hlen = hashlib.new(hash_name).digest_size
    if len(message) > k - 2 * hlen - 2:
        raise ValueError("明文过长（%d > %d）" % (len(message), k - 2 * hlen - 2))
    lhash = hashlib.new(hash_name, label).digest()
    ps = b"\x00" * (k - len(message) - 2 * hlen - 2)
    db = lhash + ps + b"\x01" + message
    seed = secrets.token_bytes(hlen)
    db_mask = mgf1(seed, k - hlen - 1, hash_name)
    masked_db = xor_bytes(db, db_mask)
    seed_mask = mgf1(masked_db, hlen, hash_name)
    masked_seed = xor_bytes(seed, seed_mask)
    return b"\x00" + masked_seed + masked_db


def oaep_decode(em: bytes, k: int, label: bytes = b"", hash_name="sha256") -> bytes:
    hlen = hashlib.new(hash_name).digest_size
    if len(em) != k or em[0] != 0:
        raise ValueError("OAEP 解码失败：格式错误")
    masked_seed, masked_db = em[1:1 + hlen], em[1 + hlen:]
    seed = xor_bytes(masked_seed, mgf1(masked_db, hlen, hash_name))
    db = xor_bytes(masked_db, mgf1(seed, k - hlen - 1, hash_name))
    lhash = hashlib.new(hash_name, label).digest()
    if not hmac.compare_digest(db[:hlen], lhash):
        raise ValueError("OAEP 解码失败：label 哈希不匹配")
    i = hlen
    while i < len(db) and db[i] == 0:
        i += 1
    if i >= len(db) or db[i] != 1:
        raise ValueError("OAEP 解码失败：缺少分隔符")
    return db[i + 1:]


# --------------------------------------------------------------- 密钥
def _miller_rabin(n: int, rounds: int = 40) -> bool:
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    for _ in range(rounds):
        a = secrets.randbelow(n - 3) + 2
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _gen_prime(bits: int) -> int:
    while True:
        candidate = secrets.randbits(bits) | (1 << (bits - 1)) | 1
        if _miller_rabin(candidate):
            return candidate


def generate_keypair(bits: int = 2048) -> dict:
    """生成 RSA 密钥对，返回私钥 JWK（含公钥字段）。"""
    e = 65537
    half = bits // 2
    while True:
        p = _gen_prime(half)
        q = _gen_prime(bits - half)
        if p == q:
            continue
        n = p * q
        if n.bit_length() != bits:
            continue
        phi = (p - 1) * (q - 1)
        if phi % e == 0:
            continue
        d = pow(e, -1, phi)
        break
    if p < q:
        p, q = q, p
    return {
        "kty": "RSA", "alg": ALG, "use": "enc", "key_ops": ["decrypt"],
        "n": b64u(i2osp(n, bits // 8)), "e": b64u(i2osp(e, 3)),
        "d": b64u(i2osp(d, bits // 8)),
        "p": b64u(i2osp(p, half)), "q": b64u(i2osp(q, bits - half)),
        "dp": b64u(i2osp(d % (p - 1), half)), "dq": b64u(i2osp(d % (q - 1), bits - half)),
        "qi": b64u(i2osp(pow(q, -1, p), half)),
    }


def public_jwk(priv: dict) -> dict:
    return {"kty": "RSA", "alg": priv.get("alg", ALG), "use": "enc",
            "key_ops": ["encrypt"], "n": priv["n"], "e": priv["e"]}


def _n_e(jwk: dict):
    return os2ip(b64u_decode(jwk["n"])), os2ip(b64u_decode(jwk["e"]))


def key_size(jwk: dict) -> int:
    return len(b64u_decode(jwk["n"]))


def fingerprint(jwk: dict) -> str:
    n = b64u_decode(jwk["n"])
    return hashlib.sha256(n).hexdigest()[:16]


# ------------------------------------------------------- 加解密（分块）
def oaep_encrypt(jwk: dict, data: bytes) -> bytes:
    n, e = _n_e(jwk)
    k = key_size(jwk)
    em = oaep_encode(data, k)
    return i2osp(pow(os2ip(em), e, n), k)


def oaep_decrypt(jwk: dict, ciphertext: bytes) -> bytes:
    if "d" not in jwk:
        raise ValueError("需要私钥才能解密")
    n, _ = _n_e(jwk)
    d = os2ip(b64u_decode(jwk["d"]))
    p = os2ip(b64u_decode(jwk["p"]))
    q = os2ip(b64u_decode(jwk["q"]))
    dp = os2ip(b64u_decode(jwk["dp"]))
    dq = os2ip(b64u_decode(jwk["dq"]))
    qi = os2ip(b64u_decode(jwk["qi"]))
    c = os2ip(ciphertext)
    if len(ciphertext) != key_size(jwk):
        raise ValueError("密文长度与密钥不匹配")
    # CRT 加速（约 3 倍）
    m1 = pow(c % p, dp, p)
    m2 = pow(c % q, dq, q)
    h = (qi * (m1 - m2)) % p
    m = (m2 + h * q) % n
    return oaep_decode(i2osp(m, key_size(jwk)), key_size(jwk))


def max_chunk(jwk: dict) -> int:
    return key_size(jwk) - 2 * HLEN - 2


def seal(jwk: dict, data: bytes, extra=None) -> dict:
    """分块 RSA-OAEP 封装任意长度的数据（纯非对称，无对称密钥）。"""
    if isinstance(data, str):
        data = data.encode("utf-8")
    size = max_chunk(jwk)
    parts = [data[i:i + size] for i in range(0, len(data), size)] or [b""]
    chunks = [b64u(oaep_encrypt(jwk, part)) for part in parts]
    env = {"alg": ALG, "enc": ENC, "n": len(chunks), "c": chunks,
           "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
           "to": fingerprint(jwk)}
    if extra:
        env.update(extra)
    return env


def open_sealed(jwk: dict, envelope: dict) -> bytes:
    if not isinstance(envelope, dict) or "c" not in envelope:
        raise ValueError("信封格式不正确")
    alg = envelope.get("alg")
    if alg and alg != ALG:
        raise ValueError("不支持的信封算法: %s" % alg)
    data = b"".join(oaep_decrypt(jwk, b64u_decode(c)) for c in envelope["c"])
    want = envelope.get("sha256")
    if want and hashlib.sha256(data).hexdigest() != want:
        raise ValueError("解密后校验失败（数据损坏）")
    return data


# ---------------------------------------------------------- 签名 / 验签
def sign(jwk: dict, data: bytes) -> str:
    """RSASSA-PKCS1-v1_5 + SHA-256（与浏览器 crypto.subtle.verify 互通）。"""
    n, e = _n_e(jwk)
    d = os2ip(b64u_decode(jwk["d"]))
    k = key_size(jwk)
    digest = hashlib.sha256(data).digest()
    t = SHA256_DIGESTINFO + digest
    ps = b"\xff" * (k - len(t) - 3)
    em = b"\x00\x01" + ps + b"\x00" + t
    return b64u(i2osp(pow(os2ip(em), d, n), k))


def verify(jwk: dict, data: bytes, signature_b64: str) -> bool:
    try:
        n, e = _n_e(jwk)
        k = key_size(jwk)
        em = i2osp(pow(os2ip(b64u_decode(signature_b64)), e, n), k)
        digest = hashlib.sha256(data).digest()
        t = SHA256_DIGESTINFO + digest
        ps = b"\xff" * (k - len(t) - 3)
        return hmac.compare_digest(em, b"\x00\x01" + ps + b"\x00" + t)
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------ 密钥管理
def load_or_create_keypair(path: str, bits: int = 2048, logger=None) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            jwk = json.load(f)
        if jwk.get("kty") == "RSA" and "d" in jwk:
            return jwk
    except (OSError, ValueError):
        pass
    if logger:
        logger("INFO", "首次运行：正在生成 %d 位 RSA 密钥对（纯 Python，需要几秒）…" % bits)
    jwk = generate_keypair(bits)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(jwk, f, indent=1)
    os.replace(tmp, path)
    if logger:
        logger("INFO", "密钥已保存到 %s（公钥指纹 %s）" % (path, fingerprint(jwk)))
    return jwk


# ---------------------------------------------------------------- 自测
if __name__ == "__main__":
    import sys
    import time

    t0 = time.time()
    priv = generate_keypair(2048)
    print("密钥生成 %.1fs  指纹=%s" % (time.time() - t0, fingerprint(priv)))
    pub = public_jwk(priv)

    for msg in [b"", b"hi", b"A" * 190, b"B" * 191, os.urandom(5000)]:
        t1 = time.time()
        env = seal(pub, msg)
        back = open_sealed(priv, env)
        assert back == msg, "roundtrip failed len=%d" % len(msg)
        print("  往返 ok 长度=%-5d 分块=%-3d 用时=%.2fs" % (len(msg), env["n"], time.time() - t1))

    sig = sign(priv, b"verdict:AC")
    print("签名验签:", verify(pub, b"verdict:AC", sig), verify(pub, b"verdict:WA", sig))

    # 用另一把钥匙解密应当失败
    other = generate_keypair(2048)
    try:
        open_sealed(other, seal(pub, b"secret"))
        print("错误：别的私钥竟然解开了")
    except Exception as e:  # noqa: BLE001
        print("错误私钥解密被拒绝:", type(e).__name__)

    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as f:
            json.dump({"priv": priv, "pub": pub}, f)
        print("已导出测试密钥到", sys.argv[1])
