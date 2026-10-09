# -*- coding: utf-8 -*-
"""Python <-> 浏览器(WebCrypto) 非对称加密互通测试。

  1) Node(WebCrypto) 生成客户端密钥并加密代码 → Python 用其私钥解密
  2) Python(判题机) 加密结果 → Node 解密 + 验签
两者都通过才算前后端加密链路可用。
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import crypto as C

NODE = os.environ.get("OJ_NODE", r"C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe")
JS = os.path.join(ROOT, "tools", "test_crypto_interop.js")
WORK = os.path.join(ROOT, "data", "state")

SAMPLE = """#include <bits/stdc++.h>
int main(){
    long long a, b;            // 中文注释也要能原样往返
    if (scanf("%lld %lld", &a, &b) != 2) return 0;
    printf("%lld\\n", a + b);  // 反斜杠与"引号"都在
    return 0;
}
"""


def run_node(args):
    r = subprocess.run([NODE, JS] + args, capture_output=True, text=True, encoding="utf-8")
    out = (r.stdout or "") + (r.stderr or "")
    print(out.strip())
    return r.returncode, out


def main():
    if not os.path.isfile(NODE):
        print("找不到 node: %s（用 OJ_NODE 指定）" % NODE)
        return 1
    os.makedirs(WORK, exist_ok=True)
    src = os.path.join(WORK, "interop_code.txt")
    with open(src, "w", encoding="utf-8", newline="\n") as f:
        f.write(SAMPLE)

    print("=== 1) Node(WebCrypto) 加密 → Python 解密 ===")
    rc, _ = run_node(["encrypt", src])
    if rc != 0:
        return 1
    payload = json.load(open(src + ".js-envelope.json", encoding="utf-8"))

    # Node 的公钥/私钥都是标准 JWK，Python 直接吃
    client_priv = payload["priv"]
    plain = C.open_sealed(client_priv, payload["env"]).decode("utf-8")
    ok1 = (plain == SAMPLE)
    print("[py] 解密 %d 字节，明文一致: %s" % (len(plain.encode("utf-8")), ok1))
    if not ok1:
        print("  期望前 80 字: %r" % SAMPLE[:80])
        print("  实得前 80 字: %r" % plain[:80])
        return 1

    print("\n=== 2) Python(判题机) 加密结果 → Node 解密 + 验签 ===")
    judge = C.generate_keypair(2048)
    judge_pub = C.public_jwk(judge)
    result_text = json.dumps({"sid": "519000001", "verdict": "WA", "score": 0,
                              "cases": [{"i": 1, "verdict": "WA", "msg": "第 1 个 token 不同"}],
                              "compile_log": "main.cpp:2: error: 'this' 不能用在非成员函数"},
                             ensure_ascii=False)
    env = C.seal(payload["pub"], result_text, extra={"kind": "result"})
    sig = C.sign(judge, result_text.encode("utf-8"))
    body = {"priv": client_priv, "env": env,
            "expect_sha256": __import__("hashlib").sha256(result_text.encode("utf-8")).hexdigest(),
            "judge_pub": judge_pub, "signature": sig,
            "signed_text": result_text}
    tmp = os.path.join(WORK, "interop_result.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False)
    rc, _ = run_node(["decrypt", tmp])
    if rc != 0:
        return 1

    print("\n互通测试通过：前端加密→后端解密，后端加密+签名→前端解密+验签，双向都成立。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
