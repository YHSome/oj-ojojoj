# -*- coding: utf-8 -*-
"""修复 github.com 的 DNS 污染：往 hosts 里钉一个可用 IP（自动备份，可还原）。

  python tools/fix_github_hosts.py            # 修复
  python tools/fix_github_hosts.py --revert   # 还原（删掉本工具加的段落）
  python tools/fix_github_hosts.py --show     # 只看当前状态
"""
import argparse
import os
import shutil
import socket
import ssl
import subprocess
import sys
import time

HOSTS = r"C:\Windows\System32\drivers\etc\hosts"
MARK_BEGIN = "# === OJ github hosts fix (begin) ==="
MARK_END = "# === OJ github hosts fix (end) ==="

# 实测可用（api.github.com/meta 官方网段内，这里按延迟排序）
CANDIDATES = ["20.205.243.166", "140.82.113.3", "140.82.112.3", "140.82.121.4"]
DOMAINS = ["github.com", "www.github.com"]

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def probe(ip, host="github.com", timeout=7):
    """TCP + TLS(SNI=host) + GET / ，返回 (ok, 描述)"""
    t0 = time.time()
    try:
        s = socket.create_connection((ip, 443), timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return False, "TCP 失败: %s" % str(e)[:40]
    try:
        ss = ctx.wrap_socket(s, server_hostname=host)
        ss.sendall(("GET / HTTP/1.1\r\nHost: %s\r\nUser-Agent: oj-diag\r\n"
                    "Connection: close\r\n\r\n" % host).encode())
        data = b""
        while len(data) < 200:
            chunk = ss.recv(200)
            if not chunk:
                break
            data += chunk
        ss.close()
        code = data.split(b"\r\n", 1)[0].decode("latin1", "replace")
        return code.startswith("HTTP/1.1 200") or code.startswith("HTTP/1.1 301"), \
            "%s %dms" % (code, int((time.time() - t0) * 1000))
    except Exception as e:  # noqa: BLE001
        return False, "TLS/HTTP 失败: %s" % str(e)[:50]


def read_hosts():
    try:
        with open(HOSTS, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError as e:
        print("读不了 hosts：%r" % e)
        return None


def dns_now(host):
    try:
        return sorted({i[4][0] for i in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})
    except Exception as e:  # noqa: BLE001
        return ["解析失败: %r" % e]


def current_status():
    print("当前 DNS 解析：")
    for d in DOMAINS:
        print("  %-16s %s" % (d, ", ".join(dns_now(d))))
    text = read_hosts()
    if text is None:
        return
    inside = MARK_BEGIN in text
    print("hosts 中是否已有本工具的段落：%s" % ("是" if inside else "否"))
    if inside:
        seg = text.split(MARK_BEGIN, 1)[1].split(MARK_END, 1)[0]
        for line in seg.strip().splitlines():
            print("   " + line)


def pick_ip():
    print("挑选可用 IP：")
    for ip in CANDIDATES:
        ok, desc = probe(ip)
        print("  %-16s %s %s" % (ip, "✔" if ok else "✘", desc))
        if ok:
            return ip
    return None


def flush_dns():
    for cmd in (["ipconfig", "/flushdns"], ["ipconfig", "/registerdns"]):
        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
        except Exception:  # noqa: BLE001
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--ip", default=None, help="手工指定 IP")
    a = ap.parse_args()

    if a.show:
        current_status()
        return 0

    text = read_hosts()
    if text is None:
        return 1

    if a.revert:
        if MARK_BEGIN not in text:
            print("hosts 里没有本工具的段落，无需还原")
            return 0
        head = text.split(MARK_BEGIN)[0]
        tail = text.split(MARK_END, 1)[1] if MARK_END in text else ""
        bak = os.path.join(os.path.dirname(HOSTS), "hosts.ojbak-%s" % time.strftime("%Y%m%d-%H%M%S"))
        try:
            shutil.copy2(HOSTS, bak)
        except OSError:
            bak = os.path.join(os.environ.get("TEMP", "."), "hosts.ojbak")
            shutil.copy2(HOSTS, bak)
        with open(HOSTS, "w", encoding="utf-8") as f:
            f.write(head + tail.lstrip("\n"))
        flush_dns()
        print("已还原 hosts（备份：%s）" % bak)
        current_status()
        return 0

    ip = a.ip or pick_ip()
    if not ip:
        print("\n没有可用 IP：说明是针对性阻断，请改用镜像（gh-proxy.com 实测可用）")
        return 2

    # 备份
    bak = os.path.join(os.path.dirname(HOSTS), "hosts.ojbak-%s" % time.strftime("%Y%m%d-%H%M%S"))
    try:
        shutil.copy2(HOSTS, bak)
        print("\n已备份 hosts -> %s" % bak)
    except OSError as e:
        bak = os.path.join("D:\\OJ\\data\\state", "hosts.ojbak")
        try:
            os.makedirs(os.path.dirname(bak), exist_ok=True)
            shutil.copy2(HOSTS, bak)
            print("\n已备份 hosts -> %s" % bak)
        except OSError:
            print("\n备份失败（%r），仍继续……" % e)

    block = [MARK_BEGIN]
    for d in DOMAINS:
        block.append("%-16s %s" % (ip, d))
    block.append(MARK_END)
    block_text = "\n".join(block) + "\n"

    try:
        if MARK_BEGIN in text:      # 已存在：替换段落
            head, rest = text.split(MARK_BEGIN, 1)
            tail = rest.split(MARK_END, 1)[1] if MARK_END in rest else ""
            new = head + block_text + tail.lstrip("\n")
        else:
            new = text.rstrip("\n") + "\n\n" + block_text
        with open(HOSTS, "w", encoding="utf-8") as f:
            f.write(new)
    except PermissionError as e:
        print("写 hosts 被拒绝：%r" % e)
        print("请用管理员身份的记事本手动把这行加进去：")
        print("  %s github.com" % ip)
        return 3
    except OSError as e:
        print("写 hosts 失败：%r" % e)
        return 3

    print("已写入 hosts：")
    for d in DOMAINS:
        print("  %-16s %s" % (ip, d))
    flush_dns()
    time.sleep(1)

    print("\n验证：")
    for d in DOMAINS:
        ok, desc = probe(ip, d)
        print("  https://%-16s %s %s" % (d, "✔" if ok else "✘", desc))
    print("\n还原命令： python tools/fix_github_hosts.py --revert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
