# -*- coding: utf-8 -*-
"""领域层：把 TinyWebDB 的裸 KV 包装成 OJ 的题目/提交/用户/排行榜/命令总线。

标签 Schema 的唯一实现处（与 docs/PROTOCOL.md 严格一致）：
    oj:meta idx:problems rank ann:<n>
    prob:<PID> test:<PID>:<i> tin:<PID>:<i> tout:<PID>:<i>
    q:<SID> sub:<SID> code:<SID> res:<SID> lock:<SID> arc:<SID>
    usr:<user> sess:<token>
    cmd:<CID> reply:<CID>
    judge:<judge_id>
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import secrets
import threading
import time

from twdb import TinyWebDB, TwdbError, dumps, loads

SCHEMA = "oj-ojojoj/1.0"

STATUS_PENDING = "pending"
STATUS_JUDGING = "judging"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

VERDICTS = ("AC", "WA", "TLE", "MLE", "RE", "CE", "OLE", "PE", "PAC", "UD", "SKIP")


def now_ts():
    return int(time.time())


# ============================================================================
#  安全文本编解码（TinyWebDB 的硬约束，实测得出）
# ----------------------------------------------------------------------------
#  该 KV 的 get/search 返回是「{"tag": "<value>"}」这种手工拼的 JSON（全部实测确认）：
#    * 双引号       → 转义成 \"   合法 JSON，可以存
#    * 单引号       → 转义成 \'   **非法 JSON 转义**，get 直接解析失败
#    * 反斜杠       → 被吃掉      内容损坏
#    * 真换行/制表符 → 不转义      直接破坏 JSON，get 解析失败
#    * 控制字符     → 同上
#  所以所有进入 KV 的字符串都必须先做百分号转义（只转 % \ ' 和控制字符），
#  读出来再还原。这一层前端也要做同样的事（AI2 用 Uri.Decode 即可还原）。
# ============================================================================
_ENC_RE = re.compile(r"[%\\'\x00-\x1f\x7f]")
_HEX = "0123456789abcdefABCDEF"


def safe(text):
    """把任意文本变成 KV 安全的单行 ASCII 可见文本。"""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    return _ENC_RE.sub(lambda m: "%%%02X" % ord(m.group(0)), text)


def unsafe(text):
    """safe() 的逆运算；单遍扫描，正确处理 %250A 这类嵌套。"""
    if not isinstance(text, str) or "%" not in text:
        return text if isinstance(text, str) else ("" if text is None else str(text))
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "%" and i + 3 <= n:
            h = text[i + 1:i + 3]
            if len(h) == 2 and h[0] in _HEX and h[1] in _HEX:
                out.append(chr(int(h, 16)))
                i += 3
                continue
        out.append(c)
        i += 1
    return "".join(out)


def safe_obj(obj):
    """递归把 JSON 结构里所有字符串转义。"""
    if isinstance(obj, str):
        return safe(obj)
    if isinstance(obj, dict):
        return {safe_obj(k) if isinstance(k, str) else k: safe_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [safe_obj(v) for v in obj]
    return obj


def unsafe_obj(obj):
    """递归还原。"""
    if isinstance(obj, str):
        return unsafe(obj)
    if isinstance(obj, dict):
        return {unsafe_obj(k) if isinstance(k, str) else k: unsafe_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [unsafe_obj(v) for v in obj]
    return obj



def new_sid():
    """毫秒级唯一提交号（时间戳 + 随机），无需中央自增计数器。"""
    return "%d%03d" % (int(time.time()) % 1000000, random.randint(0, 999))


def new_cid():
    return "c%d%04d" % (int(time.time()) % 1000000, random.randint(0, 9999))


class Store(object):
    def __init__(self, db: TinyWebDB, cfg, logger=None):
        self.db = db
        self.cfg = cfg
        self._log = logger or (lambda lvl, msg: None)
        self.judge_id = cfg.getv("judge.id", "JUDGE-1")
        self.keypair = None
        self._pending_stats = []
        self._stats_lock = threading.Lock()

    # =========================================================== 通用读写
    def get_json(self, tag, default=None):
        raw = self.db.get_json(tag, None)
        if raw is None:
            return default
        return unsafe_obj(raw)

    def put_json(self, tag, obj):
        return self.db.put_json(tag, safe_obj(obj))

    def put_raw(self, tag, text):
        return self.db.update(tag, safe(text))

    def get_raw(self, tag, default=None):
        raw = self.db.get(tag, None)
        if raw is None:
            return default
        return unsafe(raw)

    def loads(self, raw, default=None):
        """解析云端 JSON 值并还原字符串（注意：这里调用的是模块级 loads）。"""
        obj = globals()["loads"](raw, None)
        if obj is None:
            return default
        return unsafe_obj(obj)

    def del_tag(self, tag):
        return self.db.delete(tag)

    # ============================================================== 题目
    @staticmethod
    def prob_tag(pid):
        return "prob:" + pid

    @staticmethod
    def test_tag(pid, i):
        return "test:%s:%d" % (pid, i)

    def get_problem(self, pid):
        return self.get_json(self.prob_tag(pid), None)

    def put_problem(self, prob, update_index=True):
        pid = prob["pid"]
        prob.setdefault("created", now_ts())
        prob.setdefault("visible", True)
        prob.setdefault("checker", self.cfg.getv("checker.default", "diff"))
        prob.setdefault("time_limit_ms", self.cfg.getv("limits.default_time_limit_ms", 1000))
        prob.setdefault("memory_limit_kb", self.cfg.getv("limits.default_memory_limit_kb", 262144))
        prob.setdefault("output_limit_kb", self.cfg.getv("limits.default_output_limit_kb", 65536))
        prob.setdefault("case_count", 0)
        prob.setdefault("total_score", 100)
        prob.setdefault("tags", [])
        prob.setdefault("difficulty", "easy")
        r = self.put_json(self.prob_tag(pid), prob)
        if update_index:
            ids = self.list_problem_ids()
            if pid not in ids:
                ids.append(pid)
                ids.sort()
                self.put_json("idx:problems", ids)
        return r

    def delete_problem(self, pid):
        self.del_tag(self.prob_tag(pid))
        for i in range(1, 200):
            t = self.test_tag(pid, i)
            if self.db.get(t, None) is None:
                break
            self.del_tag(t)
        ids = [x for x in self.list_problem_ids() if x != pid]
        self.put_json("idx:problems", ids)

    def list_problem_ids(self):
        ids = self.get_json("idx:problems", None)
        if isinstance(ids, list) and ids:
            return [str(x) for x in ids]
        return sorted(self.discover_problem_ids())

    def discover_problem_ids(self):
        tags = self.db.search_tags(tag="prob:", limit=100 * self.cfg.getv("api.search_max_pages", 20))
        return [t.split(":", 1)[1] for t in tags if t.startswith("prob:")]

    def list_problems(self, visible_only=True):
        out = []
        for pid in self.list_problem_ids():
            p = self.get_problem(pid)
            if not p:
                continue
            if visible_only and not p.get("visible", True):
                continue
            out.append(p)
        return out

    def get_tests(self, pid, case_count=None):
        """取回测试点列表，自动解析 in_ref / out_ref 引用式大测试数据。"""
        prob = self.get_problem(pid) or {}
        n = case_count or prob.get("case_count") or 0
        tests = []
        i = 1
        while True:
            if n and i > n:
                break
            t = self.get_json(self.test_tag(pid, i), None)
            if t is None and i > (n or 0):
                break
            if t is None:
                i += 1
                continue
            data = dict(t)
            if "in_ref" in data and data["in_ref"]:
                data["in"] = self.get_raw(data["in_ref"], "") or ""
            if "out_ref" in data and data["out_ref"]:
                data["out"] = self.get_raw(data["out_ref"], "") or ""
            tests.append(data)
            i += 1
            if i > 500:  # 硬上限，防御脏数据
                break
        return tests

    def put_test(self, pid, i, case, inline_max=200000):
        data = {"i": i, "score": int(case.get("score", 0))}
        tin, tout = case.get("in", ""), case.get("out", "")
        if len(tin) <= inline_max and len(tout) <= inline_max:
            data["in"] = tin
            data["out"] = tout
        else:
            itag, otag = "tin:%s:%d" % (pid, i), "tout:%s:%d" % (pid, i)
            self.put_raw(itag, tin)
            self.put_raw(otag, tout)
            data["in_ref"] = itag
            data["out_ref"] = otag
        if case.get("name"):
            data["name"] = case["name"]
        return self.put_json(self.test_tag(pid, i), data)

    # ==================================================== 题目本地缓存
    # 云端每次 get 都是一次 HTTP 往返（~0.2-0.6s），测试点更是逐点 get。
    # 因此题目与测试点全部走本地文件缓存；维护周期用 1 次 search 批量比对云端是否变更。
    def _cache_file(self):
        return os.path.join(self.cfg.path("cache"), "problems.json")

    def _cache_load(self):
        try:
            with open(self._cache_file(), "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _cache_save(self, data):
        path = self._cache_file()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as e:
            self._log("WARN", "写题目缓存失败: %r" % e)

    def cache_put(self, pid, prob, tests):
        data = self._cache_load()
        data[str(pid)] = {"ts": now_ts(), "prob": prob, "tests": tests}
        self._cache_save(data)
        if prob.get("rev"):
            self.snapshot_rev(pid, prob["rev"], prob, tests)

    # ---------------------------------------------------- 题目版本快照
    # 对齐 MiniJudge：内容摘要决定版本，更新题目不影响已经排队的提交。
    def _rev_dir(self):
        return os.path.join(self.cfg.path("cache"), "rev")

    def _rev_file(self, pid, rev):
        safe_rev = "".join(ch for ch in str(rev) if ch.isalnum() or ch in "-_")[:32]
        return os.path.join(self._rev_dir(), "%s-%s.json" % (pid, safe_rev))

    def snapshot_rev(self, pid, rev, prob=None, tests=None):
        if not rev:
            return False
        prob = prob if prob is not None else self.get_problem(pid)
        if not prob:
            return False
        tests = tests if tests is not None else self.get_tests(pid)
        path = self._rev_file(pid, rev)
        try:
            os.makedirs(self._rev_dir(), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"ts": now_ts(), "pid": pid, "rev": rev,
                           "prob": prob, "tests": tests}, f, ensure_ascii=False)
            os.replace(tmp, path)
            return True
        except OSError as e:
            self._log("WARN", "写版本快照失败 %s: %r" % (path, e))
            return False

    def get_problem_for_rev(self, pid, rev):
        """按提交时固定的 rev 取题面；缺快照时回退当前版本并告警。"""
        if rev:
            try:
                with open(self._rev_file(pid, rev), "r", encoding="utf-8") as f:
                    snap = json.load(f)
                if isinstance(snap, dict) and snap.get("prob"):
                    return snap["prob"], snap.get("tests") or []
            except (OSError, ValueError):
                pass
        prob = self.get_problem_cached(pid)
        if prob and rev and prob.get("rev") != rev:
            self._log("WARN", "题目 %s 缺少版本快照 rev=%s，回退当前版本 rev=%s"
                      % (pid, rev, prob.get("rev")))
        return prob, self.get_tests_cached(pid)

    def cache_drop(self, pid=None):
        data = self._cache_load()
        if pid is None:
            data = {}
        else:
            data.pop(str(pid), None)
        self._cache_save(data)

    def get_problem_cached(self, pid, ttl_s=None):
        """带 TTL + rev 指纹校验的题目缓存：本地命中就完全不发请求。"""
        entry = self._cache_load().get(str(pid))
        ttl = int(ttl_s if ttl_s is not None else self.cfg.getv("judge.prob_cache_ttl_s", 120))
        if isinstance(entry, dict) and entry.get("prob"):
            if now_ts() - int(entry.get("ts") or 0) < ttl:
                return entry["prob"]
            prob = self.get_problem(pid) or entry["prob"]
            if prob.get("rev") not in (None, entry["prob"].get("rev")):
                self._log("INFO", "题目 %s 已更新(rev %s -> %s)，刷新缓存"
                          % (pid, entry["prob"].get("rev"), prob.get("rev")))
                self.cache_put(pid, prob, self.get_tests(pid))
            else:
                entry["ts"] = now_ts()
                data = self._cache_load()
                data[str(pid)] = entry
                self._cache_save(data)
            return prob
        prob = self.get_problem(pid)
        if prob:
            self.cache_put(pid, prob, self.get_tests(pid))
        return prob

    def get_tests_cached(self, pid):
        entry = self._cache_load().get(str(pid))
        if isinstance(entry, dict) and entry.get("prob") and entry.get("tests") is not None:
            prob = self.get_problem_cached(pid)      # 触发 TTL/rev 校验
            entry = self._cache_load().get(str(pid)) or entry
            if entry.get("tests") is not None:
                return entry["tests"]
        prob = self.get_problem(pid)
        if not prob:
            return []
        tests = self.get_tests(pid)
        self.cache_put(pid, prob, tests)
        return tests

    def refresh_problem_cache(self, force=False):
        """1 次 search 拿全部题目标签，只对『变了的题』重新拉测试点。返回刷新数量。"""
        cache = self._cache_load()
        changed = 0
        pairs = self.db.search_pairs(tag="prob:", type_="both")
        seen = set()
        for tag, raw in pairs:
            prob = self.loads(raw, None)
            if not isinstance(prob, dict) or not prob.get("pid"):
                continue
            pid = str(prob["pid"])
            seen.add(pid)
            old = (cache.get(pid) or {}).get("prob") or {}
            same = (not force and old.get("rev") is not None
                    and old.get("rev") == prob.get("rev")) or (
                    not force and old.get("rev") is None
                    and old.get("case_count") == prob.get("case_count")
                    and old.get("total_score") == prob.get("total_score")
                    and old.get("title") == prob.get("title")
                    and old.get("time_limit_ms") == prob.get("time_limit_ms"))
            if not same:
                tests = self.get_tests(pid)
                cache[pid] = {"ts": now_ts(), "prob": prob, "tests": tests}
                changed += 1
        for pid in list(cache.keys()):
            if pid not in seen:
                cache.pop(pid, None)   # 云端删掉的题，本地也清掉
                changed += 1
        self._cache_save(cache)
        if changed:
            self._log("INFO", "题目缓存刷新 %d 题（云端共 %d 题）" % (changed, len(seen)))
        return changed

    def _write_parts(self, base_tag, text, limit=None):
        """只写分片，不写主标签（供密文结果等自定义清单使用）。"""
        limit = int(limit or self.cfg.getv("api.value_chunk_chars", 8000))
        text = text or ""
        parts = [text[i:i + limit] for i in range(0, len(text), limit)] or [""]
        for i, part in enumerate(parts):
            self.put_raw("%s:%d" % (base_tag, i), part)
        return len(parts)

    def _read_parts(self, base_tag, n):
        """读密文分片（每片都是安全编码文本，读出后反转义）。"""
        out = []
        for i in range(int(n or 0)):
            out.append(unsafe(self.db.get("%s:%d" % (base_tag, i), "") or ""))
        return "".join(out)

    def _drop_parts(self, base_tag, n):
        for i in range(int(n or 0)):
            self.del_tag("%s:%d" % (base_tag, i))

    def set_keypair(self, jwk):
        """注入判题机私钥（None 表示明文模式）。"""
        self.keypair = jwk
        return jwk

    def has_keypair(self):
        return bool(self.keypair)

    # ==================================================== 分片值 / 密文信封
    # 实测：云端单值 10000 字符可用、20000 字符会被服务端破坏。
    # 因此任何可能变大的值（密文、编译日志）都按安全上限切分到多个标签。
    def store_chunked(self, base_tag, text, extra=None, limit=None):
        """把长文本拆成 base_tag（清单） + base_tag:0/1/2…（分片）。返回清单。"""
        limit = int(limit or self.cfg.getv("api.value_chunk_chars", 8000))
        text = text or ""
        parts = [text[i:i + limit] for i in range(0, len(text), limit)] or [""]
        manifest = {"chunked": True, "n": len(parts), "size": len(text),
                    "base": base_tag + ":", "ts": now_ts()}
        if extra:
            manifest.update(extra)
        for i, part in enumerate(parts):
            self.put_raw("%s:%d" % (base_tag, i), part)
        self.put_raw(base_tag, dumps(manifest))
        return manifest

    def read_chunked(self, base_tag):
        """读清单 + 分片，返回 (manifest, text)。非分片值时 manifest 为 None。

        **顺序**：先 JSON.parse 云端原文（仍是安全编码态），再反转义。
        反过来做的话，%0A 会先变成真换行，JSON 里出现裸换行 → 解析必定失败。
        """
        encoded = self.db.get(base_tag, None)
        if encoded in (None, ""):
            return None, ""
        try:
            man = json.loads(encoded)
        except ValueError:
            return None, unsafe(encoded)          # 老格式：整段就是内容
        if not isinstance(man, dict) or not man.get("chunked"):
            return None, unsafe(encoded)
        man = unsafe_obj(man)
        parts = []
        for i in range(int(man.get("n") or 0)):
            parts.append(unsafe(self.db.get("%s:%d" % (base_tag, i), "") or ""))
        return man, "".join(parts)

    def drop_chunked(self, base_tag, manifest=None):
        """删除清单与全部分片（密文取走后必须清掉，避免明文/密文长期滞留云端）。"""
        if manifest is None:
            try:
                manifest = json.loads(self.get_raw(base_tag, "") or "{}")
            except ValueError:
                manifest = {}
        n = int((manifest or {}).get("n") or 0)
        for i in range(n):
            self.del_tag("%s:%d" % (base_tag, i))
        return self.del_tag(base_tag)

    # ------------------------------------------------------------ 公钥发布
    def publish_pubkey(self, jwk, fingerprint=""):
        payload = {"kty": "RSA", "alg": jwk.get("alg", "RSA-OAEP-256"),
                   "use": "enc", "n": jwk["n"], "e": jwk["e"],
                   "fingerprint": fingerprint or "", "ts": now_ts(),
                   "scheme": "RSA-OAEP(SHA-256,2048) 分块，前端用 crypto.subtle 即可"}
        self.put_json("oj:pubkey", payload)
        return payload

    def get_pubkey(self):
        return self.get_json("oj:pubkey", None)

    # ------------------------------------------------- 提交代码的密文信封
    # code:<SID>   = 清单 {"alg","enc","n","sha256","size","to"}
    # code:<SID>:i = 第 i 组 RSA 密文（base64url，换行分隔）
    # 取走解密后立刻覆盖成 {"state":"judging",...}，密文不再留在云端。
    def read_code_envelope(self, sid):
        man, blob = self.read_chunked(self.code_tag(sid))
        if not man:
            return None, ""
        if man.get("state") in ("judging", "done"):
            return None, ""                      # 已被取走或正在判
        chunks = [c for c in blob.split("\n") if c.strip()]
        if not chunks:
            return None, ""
        return {"alg": man.get("alg", "RSA-OAEP-256"),
                "enc": man.get("enc", "b64url-chunk-v1"),
                "n": len(chunks), "c": chunks,
                "sha256": man.get("sha256"),
                "size": man.get("size"), "to": man.get("to")}, ""

    def take_submission_code(self, sid, keypair=None):
        """取源码：加密提交则解密，明文提交则原样返回。

        同时按需求把云端 `code:<SID>` 覆盖成『判题中』，密文分片全部删除。
        返回 (源码文本, 信封信息/None, 错误信息)
        """
        man, blob = self.read_chunked(self.code_tag(sid))
        if man and man.get("state") in ("judging", "done"):
            return "", None, "代码已被取走（state=%s）" % man.get("state")
        if not man:
            # 明文提交（兼容老前端 / 未启用加密）
            return blob or "", None, ""
        chunks = [c for c in blob.split("\n") if c.strip()]
        env = {"alg": man.get("alg", "RSA-OAEP-256"), "enc": man.get("enc", "b64url-chunk-v1"),
               "n": len(chunks), "c": chunks, "sha256": man.get("sha256"),
               "size": man.get("size"), "to": man.get("to")}
        self.drop_chunked(self.code_tag(sid), man)
        self.mark_code_judging(sid)
        if not keypair:
            return "", env, "提交是加密的，但判题机没有私钥"
        try:
            import crypto as ojcrypto
            raw = ojcrypto.open_sealed(keypair, env)
            return raw.decode("utf-8"), env, ""
        except Exception as e:  # noqa: BLE001
            return "", env, "解密失败: %r" % e

    def mark_code_judging(self, sid, note=""):
        """按需求：代码取走后，云端该段代码立刻改成『判题中』。"""
        return self.put_json(self.code_tag(sid), {
            "state": "judging", "sid": str(sid), "judge": self.judge_id,
            "ts": now_ts(), "note": note or "代码已取走解密，正在判题"})

    def mark_code_done(self, sid, verdict=""):
        return self.put_json(self.code_tag(sid), {
            "state": "done", "sid": str(sid), "judge": self.judge_id,
            "verdict": verdict, "ts": now_ts(),
            "note": "判题完成，可查看结果"})

    # ============================================================== 提交
    @staticmethod
    def sub_tag(sid):
        return "sub:" + str(sid)

    @staticmethod
    def res_tag(sid):
        return "res:" + str(sid)

    @staticmethod
    def code_tag(sid):
        return "code:" + str(sid)

    @staticmethod
    def q_tag(sid):
        return "q:" + str(sid)

    @staticmethod
    def lock_tag(sid):
        return "lock:" + str(sid)

    @staticmethod
    def arc_tag(sid):
        return "arc:" + str(sid)

    def create_submission(self, user, pid, lang, code, sid=None, ts=None,
                          prob_rev=None, rejudge_batch=None):
        """前端提交三连写：code: / sub: / q:（顺序不可颠倒）。

        `prob_rev` 固定该次提交使用的题目版本（对齐 MiniJudge：更新题目不影响已排队提交）。
        """
        sid = str(sid or new_sid())
        ts = int(ts or now_ts())
        if prob_rev is None:
            prob = self.get_problem_cached(pid) or {}
            prob_rev = prob.get("rev", "")
        sub = {
            "sid": sid, "user": user, "pid": pid, "lang": lang,
            "status": STATUS_PENDING, "ts": ts, "judge": "",
            "verdict": "", "score": 0, "time_ms": 0, "memory_kb": 0,
            "cases_passed": 0, "case_count": 0, "msg": "排队中",
            "prob_rev": prob_rev or "", "attempt": 0,
            "lease_token": "", "lease_until": 0, "rejudge": rejudge_batch or "",
        }
        self.put_raw(self.code_tag(sid), code or "")
        self.put_json(self.sub_tag(sid), sub)
        self.put_json(self.q_tag(sid), {"sid": sid, "ts": ts, "pid": pid,
                                        "lang": lang, "user": user})
        return sub

    def get_sub(self, sid):
        return self.get_json(self.sub_tag(sid), None)

    def put_sub(self, sub):
        return self.put_json(self.sub_tag(sub["sid"]), sub)

    def get_code(self, sid):
        return self.get_raw(self.code_tag(sid), "")

    def get_result(self, sid):
        return self.get_json(self.res_tag(sid), None) or self.get_json(self.arc_tag(sid), None)

    def enqueue(self, sid, sub=None, candidate=None):
        sub = sub or self.get_sub(sid) or {"sid": sid}
        payload = {"sid": str(sid), "ts": int(sub.get("ts", now_ts())),
                   "pid": sub.get("pid", ""), "lang": sub.get("lang", ""),
                   "user": sub.get("user", "")}
        if candidate:
            payload["candidate"] = candidate      # 候选重判：绕过"已判过"去重
        return self.put_json(self.q_tag(sid), payload)

    def dequeue(self, sid):
        return self.del_tag(self.q_tag(sid))

    def queue_candidates(self):
        """热队列：只读 q:（有界、随时 <100），按 ts 升序返回。"""
        pairs = self.db.search_pairs(tag="q:", type_="both")
        out = []
        for tag, raw in pairs:
            v = self.loads(raw, None)
            if not isinstance(v, dict):
                v = {"sid": tag.split(":", 1)[1] if ":" in tag else tag}
            v.setdefault("sid", tag.split(":", 1)[1] if ":" in tag else tag)
            v.setdefault("ts", 0)
            out.append(v)
        out.sort(key=lambda x: (int(x.get("ts") or 0), str(x.get("sid"))))
        return out

    def unindexed_pending(self, seen=None):
        """兜底：扫 sub: 找 pending（防前端忘了写 q: 标签）。"""
        seen = seen or set()
        pairs = self.db.search_pairs(tag="sub:", type_="both")
        out = []
        for _, raw in pairs:
            s = self.loads(raw, None)
            if not isinstance(s, dict):
                continue
            if s.get("status") == STATUS_PENDING and str(s.get("sid")) not in seen:
                out.append(s)
        out.sort(key=lambda x: int(x.get("ts") or 0))
        return out

    def scan_by_status(self, status):
        pairs = self.db.search_pairs(tag="sub:", type_="both")
        out = []
        for _, raw in pairs:
            s = self.loads(raw, None)
            if isinstance(s, dict) and s.get("status") == status:
                out.append(s)
        return out

    def submissions_of(self, user, limit=20):
        pairs = self.db.search_pairs(tag="sub:", type_="both")
        out = []
        for _, raw in pairs:
            s = self.loads(raw, None)
            if isinstance(s, dict) and s.get("user") == user:
                out.append(s)
        out.sort(key=lambda x: int(x.get("ts") or 0), reverse=True)
        return out[:limit]

    # ======================================================== 任务租约
    # 对齐 MiniJudge 的 lease-v1：租约带 token 与到期时间；写回结果前必须校验租约，
    # 到期视为执行器失联（JE + 有限重试），陈旧结果一律丢弃。
    @staticmethod
    def cres_tag(sid):
        return "cres:" + str(sid)

    def lease_ok(self, sub, token):
        if not isinstance(sub, dict) or not token:
            return False
        return (sub.get("lease_token") == token
                and int(sub.get("lease_until") or 0) > now_ts()
                and sub.get("judge") == self.judge_id)

    def acquire_lease(self, sid, judge_id=None, ttl_s=None, jitter_ms=None,
                      assume_free=False, candidate=False):
        """领取租约：一次写入（状态+token+到期+attempt）→ 抖动 → 回读校验。

        返回 token 表示领取成功；None 表示被别的判题机占据或校验失败。
        candidate=True 时只动租约与候选状态，**不改参赛者视图**。
        """
        judge_id = judge_id or self.judge_id
        ttl = int(ttl_s or self.cfg.getv("judge.lease_seconds",
                                         self.cfg.getv("judge.lock_ttl_s", 180)))
        lo, hi = (jitter_ms or self.cfg.getv("judge.lock_jitter_ms", [150, 400]))
        sub = self.get_sub(sid)
        if not sub:
            return None
        if not assume_free:
            cur_judge, until = sub.get("judge"), int(sub.get("lease_until") or 0)
            if until > now_ts() and cur_judge and cur_judge != judge_id:
                return None
        token = secrets.token_hex(8)
        sub.update({"judge": judge_id, "lease_token": token,
                    "lease_until": now_ts() + ttl,
                    "attempt": int(sub.get("attempt", 0) or 0) + 1})
        if candidate:
            sub["candidate_status"] = "running"
        else:
            sub.update({"status": STATUS_JUDGING, "msg": "评测中"})
        if not self.put_sub(sub):
            return None
        time.sleep(random.uniform(lo, hi) / 1000.0)
        back = self.get_sub(sid)
        if isinstance(back, dict) and back.get("lease_token") == token:
            return token
        return None

    def renew_lease(self, sid, token, seconds=None):
        sub = self.get_sub(sid)
        if not self.lease_ok(sub, token):
            return False
        sub["lease_until"] = now_ts() + int(seconds or self.cfg.getv("judge.lease_seconds", 180))
        return self.put_sub(sub)

    def release_lease(self, sid, token):
        sub = self.get_sub(sid)
        if self.lease_ok(sub, token):
            sub.update({"lease_token": "", "lease_until": 0})
            if sub.get("status") == STATUS_JUDGING:
                sub["status"] = STATUS_PENDING
            return self.put_sub(sub)
        return False

    # ---- 旧接口名兼容（CLI/文档里可能还在用 lock 的说法）
    def acquire_lock(self, sid, judge_id=None, **kw):
        return self.acquire_lease(sid, judge_id=judge_id, **kw)

    def release_lock(self, sid, nonce=None):
        return self.release_lease(sid, nonce)

    def lock_info(self, sid):
        sub = self.get_sub(sid)
        if not isinstance(sub, dict):
            return None
        ttl = int(self.cfg.getv("judge.lease_seconds", 180))
        return {"judge": sub.get("judge"),
                "ts": int(sub.get("lease_until") or 0) - ttl,
                "nonce": sub.get("lease_token"),
                "lease_until": sub.get("lease_until")}

    def finish(self, sid, verdict, score, cases, compile_log="", time_ms=0,
               memory_kb=0, msg="", checker=None, token=None, candidate=False,
               client_pubkey=None, source=None):
        """先写 res: 详情，再翻 sub: 状态位 —— 前端只会看到一致的状态。

        任务租约（对齐 MiniJudge）：写完结果前校验租约仍属于自己，
        否则本次结果作废（陈旧结果丢弃），避免两个判题机互相覆盖。
        """
        sub = self.get_sub(sid) or {"sid": str(sid)}
        if token is not None and not self.lease_ok(sub, token):
            self._log("WARN", "提交 %s 的租约已失效，丢弃本次结果（%s）" % (sid, verdict))
            return None
        case_count = len(cases)
        passed = sum(1 for c in cases if c.get("verdict") == "AC")
        res = {"sid": str(sid), "verdict": verdict, "score": int(score),
               "cases": cases,
               "compile_log": compile_log[:self.cfg.getv("limits.compile_log_max_bytes", 8192)],
               "checker": checker or "", "ts": now_ts(),
               "attempt": int(sub.get("attempt", 0) or 0),
               "prob_rev": sub.get("prob_rev", ""),
               "candidate": bool(candidate)}
        if candidate:
            # 候选重判：只写候选结果，不动参赛者视图（由 apply/cancel 决定）
            self.put_json(self.cres_tag(sid), res)
            sub.update({"candidate_status": "done", "candidate_verdict": verdict,
                        "candidate_score": int(score),
                        "lease_token": "", "lease_until": 0})
            self.put_sub(sub)
            self.dequeue(sid)
            self.mark_code_done(sid, verdict)
            return sub
        # 结果回传：客户端给了公钥就封起来（只有它的私钥能看），否则明文
        payload = res
        if self.keypair and client_pubkey:
            payload = self.seal_result(sid, res, client_pubkey, source=source)
        self.put_json(self.res_tag(sid), payload)
        sub.update({"status": STATUS_DONE, "verdict": verdict, "score": int(score),
                    "time_ms": int(time_ms), "memory_kb": int(memory_kb),
                    "cases_passed": passed, "case_count": case_count,
                    "msg": msg or verdict, "judge": self.judge_id,
                    "lease_token": "", "lease_until": 0,
                    "result_sealed": bool(payload is not res),
                    "finished": now_ts()})
        self.put_sub(sub)
        self.dequeue(sid)
        self.mark_code_done(sid, verdict)
        self._bump_user_stats(sub)
        return sub

    def seal_result(self, sid, res, client_pubkey, source=None):
        """用客户端公钥加密完整结果（含编译日志、逐点信息），并附判题机签名。

        返回可写入 `res:<SID>` 的对象；密文分片放在 `res:<SID>:i`。
        源码也会一并封进密文里（只有提交者本人能解），这样换浏览器后
        仍能在「我的提交」里看到当初交的代码；明文提交则**不含源码**，避免泄露。
        """
        import crypto as ojcrypto
        body = dict(res)
        if source is not None and self.cfg.getv("crypto.include_source", True):
            body["source"] = source
            body["source_lang"] = res.get("lang") or ""
        plain = dumps(body)
        env = ojcrypto.seal(client_pubkey, plain)
        try:
            env["sig"] = ojcrypto.sign(self.keypair, plain.encode("utf-8"))
            env["judge_fp"] = ojcrypto.fingerprint(ojcrypto.public_jwk(self.keypair))
        except Exception as e:  # noqa: BLE001
            self._log("WARN", "结果签名失败: %r" % e)
        body = "\n".join(env.pop("c"))
        n = self._write_parts(self.res_tag(sid), body)
        env.update({"n": n, "sealed": True, "chunked": True})
        return {"sid": str(sid), "verdict": res.get("verdict"),
                "score": int(res.get("score") or 0), "ts": res.get("ts") or now_ts(),
                "state": "sealed", "sealed_env": env,
                "public": {"verdict": res.get("verdict"), "score": res.get("score"),
                           "cases_passed": sum(1 for c in res.get("cases", [])
                                               if c.get("verdict") == "AC"),
                           "case_count": len(res.get("cases", [])),
                           "msg": "结果已加密，请用提交时的私钥解密"}}

    def open_result(self, sid):
        """判题机侧读取（含解密）某个提交的结果，用于 inspect/重判。"""
        payload = self.get_json(self.res_tag(sid), None)
        if not isinstance(payload, dict):
            return None
        env = payload.get("sealed_env")
        if not env or not self.keypair:
            return payload
        try:
            import crypto as ojcrypto
            body = self._read_parts(self.res_tag(sid), env.get("n"))
            sealed = dict(env)
            sealed["c"] = [c for c in body.split("\n") if c.strip()]
            plain = ojcrypto.open_sealed(self.keypair, sealed)
            out = json.loads(plain)
            if env.get("sig"):
                out["_signature_valid"] = ojcrypto.verify(
                    ojcrypto.public_jwk(self.keypair), plain, env["sig"])
            return out
        except Exception as e:  # noqa: BLE001
            self._log("WARN", "结果解密失败 sid=%s: %r" % (sid, e))
            return payload

    def fail_submission(self, sid, reason, verdict="JE", token=None, retry=True,
                        candidate=False):
        """判题机侧故障（JE）：按 attempt 有限重试（对齐 MiniJudge MAX_ATTEMPTS=3）。

        candidate=True 时只影响候选状态，参赛者视图保持不变。
        """
        sub = self.get_sub(sid) or {"sid": str(sid)}
        if token is not None and not self.lease_ok(sub, token):
            self._log("WARN", "提交 %s 租约失效，丢弃故障上报" % sid)
            return None
        attempt = int(sub.get("attempt", 0) or 0)
        max_attempts = int(self.cfg.getv("limits.retry_max_attempts", 3))
        if candidate:
            if retry and attempt < max_attempts:
                sub.update({"candidate_status": "queued", "lease_token": "", "lease_until": 0})
                self.put_sub(sub)
                self.enqueue(sid, sub, candidate=sub.get("rejudge"))
            else:
                sub.update({"candidate_status": "error", "candidate_msg": reason,
                            "lease_token": "", "lease_until": 0})
                self.put_sub(sub)
                self.dequeue(sid)
            return sub
        if retry and attempt < max_attempts:
            sub.update({"status": STATUS_PENDING, "msg": "判题机故障重试中(%d/%d): %s"
                        % (attempt + 1, max_attempts, reason),
                        "judge": self.judge_id, "lease_token": "", "lease_until": 0})
            self.put_sub(sub)
            self.enqueue(sid, sub)
            return sub
        sub.update({"status": STATUS_FAILED, "verdict": verdict, "msg": reason,
                    "finished": now_ts(), "judge": self.judge_id,
                    "lease_token": "", "lease_until": 0})
        self.put_sub(sub)
        self.put_json(self.res_tag(sid), {"sid": str(sid), "verdict": verdict,
                                          "score": 0, "cases": [],
                                          "compile_log": "", "msg": reason,
                                          "attempt": attempt, "ts": now_ts()})
        self.dequeue(sid)
        self._bump_user_stats(sub)
        return sub

    def has_pending_stats(self):
        with self._stats_lock:
            return bool(self._pending_stats)

    def _bump_user_stats(self, sub):
        """默认批量延迟：判题热路径不为每个提交多花 2 次 HTTP，由维护周期统一落库。"""
        if self.cfg.getv("judge.batch_user_stats", True):
            with self._stats_lock:
                self._pending_stats.append({"user": sub.get("user"), "pid": sub.get("pid"),
                                            "verdict": sub.get("verdict"),
                                            "ts": int(sub.get("finished") or now_ts()),
                                            "score": int(sub.get("score") or 0)})
            return
        self._apply_user_stats([sub])

    def flush_user_stats(self):
        """把攒下的提交统计按用户聚合落库：每个用户只 get+put 一次。

        计分模型（两套并行，互不影响）：
          * 分数制：`best[pid]` 记录该题历史最好分，总分 = 各题最好分之和；`solved` 只记满分题
          * ACM 赛制：`first_ac[pid]` = 首次 AC 的时间戳，`tries[pid]` = 首次 AC **之前**的失败次数
            （首次 AC 之后的失败不再计入罚时，符合 ACM 规则）
        """
        with self._stats_lock:
            pending, self._pending_stats = self._pending_stats, []
        if not pending:
            return 0
        grouped = {}
        for it in pending:
            grouped.setdefault(it.get("user"), []).append(it)
        done = 0
        for user, items in grouped.items():
            u = self.get_user(user)
            if not u:
                continue
            solved = list(u.get("solved") or [])
            best = dict(u.get("best") or {})
            first_ac = dict(u.get("first_ac") or {})
            tries = dict(u.get("tries") or {})
            for it in items:
                u["submit_count"] = int(u.get("submit_count", 0)) + 1
                pid, verdict = it.get("pid"), it.get("verdict")
                score = int(it.get("score") or 0)
                ts = int(it.get("ts") or now_ts())
                # 记录该用户最早一次提交的时间（ACM 计时起点需要它）
                prev = int(u.get("first_sub") or 0)
                if not prev or ts < prev:
                    u["first_sub"] = ts
                if pid:
                    if score > int(best.get(pid, 0) or 0):
                        best[pid] = score
                    if verdict == "AC":
                        u["ac_count"] = int(u.get("ac_count", 0)) + 1
                        if pid not in solved:
                            solved.append(pid)
                        first_ac.setdefault(pid, int(it.get("ts") or now_ts()))
                    elif pid not in solved:
                        # 还没 AC 就失败 → 记一次罚时（AC 之后再错不算）
                        tries[pid] = int(tries.get(pid, 0)) + 1
                u["last_ts"] = now_ts()
            u["solved"] = solved
            u["best"] = best
            u["first_ac"] = first_ac
            u["tries"] = tries
            u["score"] = sum(int(v or 0) for v in best.values())
            self.put_json("usr:" + str(user), u)
            done += 1
        return done

    def _apply_user_stats(self, subs):
        """非批量模式下的即时统计（同样遵循 best-per-problem 计分 + ACM 罚时）。"""
        for sub in subs:
            u = self.get_user(sub.get("user"))
            if not u:
                continue
            solved = list(u.get("solved") or [])
            best = dict(u.get("best") or {})
            first_ac = dict(u.get("first_ac") or {})
            tries = dict(u.get("tries") or {})
            pid, score = sub.get("pid"), int(sub.get("score") or 0)
            u["submit_count"] = int(u.get("submit_count", 0)) + 1
            if pid:
                if score > int(best.get(pid, 0) or 0):
                    best[pid] = score
                if sub.get("verdict") == "AC":
                    u["ac_count"] = int(u.get("ac_count", 0)) + 1
                    if pid not in solved:
                        solved.append(pid)
                    first_ac.setdefault(pid, int(sub.get("finished") or now_ts()))
                elif pid not in solved:
                    tries[pid] = int(tries.get(pid, 0)) + 1
            u["solved"], u["best"], u["first_ac"] = solved, best, first_ac
            u["tries"] = tries
            u["score"] = sum(int(v or 0) for v in best.values())
            u["last_ts"] = now_ts()
            self.put_json("usr:" + u["user"], u)

    # =========================================================== 用户/会话
    def _hash(self, pwd, salt):
        return hashlib.sha256((salt + ":" + pwd).encode("utf-8")).hexdigest()

    def get_user(self, user):
        if not user:
            return None
        return self.get_json("usr:" + user, None)

    def list_users(self):
        out = []
        for tag, raw in self.db.search_pairs(tag="usr:", type_="both"):
            u = self.loads(raw, None)
            if isinstance(u, dict):
                u.setdefault("user", tag.split(":", 1)[1])
                out.append(u)
        out.sort(key=lambda x: (-int(x.get("score", 0) or 0), str(x.get("user"))))
        return out

    def create_user(self, user, pwd, nick=None, is_admin=False):
        user = (user or "").strip()
        if not user or len(user) > 24 or ":" in user:
            return False, "用户名非法（1-24 字符，不能含冒号）"
        if len(pwd or "") < int(self.cfg.getv("auth.password_min_len", 4)):
            return False, "密码太短"
        if self.get_user(user):
            return False, "用户已存在"
        salt = secrets.token_hex(int(self.cfg.getv("auth.salt_len", 12)) // 2)
        u = {"user": user, "nick": nick or user, "salt": salt,
             "pwd": self._hash(pwd, salt), "created": now_ts(),
             "is_admin": bool(is_admin), "submit_count": 0, "ac_count": 0,
             "score": 0, "solved": []}
        self.put_json("usr:" + user, u)
        return True, u

    def verify_user(self, user, pwd):
        u = self.get_user(user)
        if not u:
            return None, "用户不存在"
        if self._hash(pwd or "", u.get("salt", "")) != u.get("pwd"):
            return None, "密码错误"
        return u, ""

    def new_session(self, user, ttl_h=None):
        ttl = int(ttl_h or self.cfg.getv("judge.session_ttl_h", 72))
        token = secrets.token_hex(16)
        self.put_json("sess:" + token, {"token": token, "user": user,
                                        "ts": now_ts(),
                                        "expire": now_ts() + ttl * 3600})
        return token

    def get_session(self, token):
        if not token:
            return None
        s = self.get_json("sess:" + token, None)
        if not s:
            return None
        if int(s.get("expire", 0)) < now_ts():
            self.del_tag("sess:" + token)
            return None
        return s

    def drop_session(self, token):
        return self.del_tag("sess:" + token)

    def cleanup_sessions(self):
        n = 0
        for tag, raw in self.db.search_pairs(tag="sess:", type_="both"):
            s = self.loads(raw, None)
            if not isinstance(s, dict) or int(s.get("expire", 0)) < now_ts():
                self.del_tag(tag)
                n += 1
        return n

    # ============================================================ 排行榜
    def rebuild_rank(self):
        """构建排行榜快照。

        * 分数制（兼容旧用法）：按总分 → AC 数 → 提交次数排序
        * ACM 赛制（前端主用）：按 通过题数 ↓ → 罚时 ↑ → 最后过题时间 ↑ 排序
          罚时 = Σ(每题首次 AC 距比赛开始的分钟数 + 20 分钟 × 该题首次 AC 前的失败次数)
        """
        users = self.list_users()
        pids = self.list_problem_ids()

        # 罚时参数：rank.contest_start 为空则自动取所有"首次 AC"里最早的时间
        start_cfg = self.cfg.getv("rank.contest_start", "")
        contest_start = 0
        if isinstance(start_cfg, (int, float)) and start_cfg:
            contest_start = int(start_cfg)
        elif isinstance(start_cfg, str) and start_cfg.strip():
            try:
                contest_start = int(start_cfg.strip())
            except ValueError:
                try:
                    import datetime as _dt
                    contest_start = int(_dt.datetime.fromisoformat(start_cfg.strip()).timestamp())
                except Exception:  # noqa: BLE001
                    contest_start = 0
        penalty_min = int(self.cfg.getv("rank.penalty_min", 20))
        if not contest_start:
            # 优先用"最早一次提交"当开赛时间（否则第一个 AC 的人永远是 0 分钟，看不出用时）
            first_subs = [int(u.get("first_sub") or 0) for u in users if u.get("first_sub")]
            all_first = [int(t) for u in users for t in (u.get("first_ac") or {}).values()]
            contest_start = min(first_subs) if first_subs else (min(all_first) if all_first else now_ts())

        order = []
        for u in users:
            # 只把真正提交过的人放进榜（过滤掉注册了但没做题的账号）
            if int(u.get("submit_count", 0) or 0) <= 0:
                continue
            first_ac = dict(u.get("first_ac") or {})
            tries = dict(u.get("tries") or {})
            cells = {}
            penalty = 0
            for pid, ts in first_ac.items():
                mins = max(0, int((int(ts) - contest_start) // 60))
                fails = int(tries.get(pid, 0) or 0)
                penalty += mins + penalty_min * fails
                cells[pid] = {"v": "ac", "t": mins, "f": fails}
            for pid, fails in tries.items():
                if pid not in first_ac:
                    cells[pid] = {"v": "try", "f": int(fails or 0)}
            order.append({"user": u.get("user"), "nick": u.get("nick", u.get("user")),
                          "score": int(u.get("score", 0) or 0),
                          "ac": int(u.get("ac_count", 0) or 0),
                          "submit": int(u.get("submit_count", 0) or 0),
                          "solved": len(first_ac),
                          "penalty": penalty,
                          "last_ac": max([int(t) for t in first_ac.values()] or [0]),
                          "cells": cells,
                          "last_ts": int(u.get("last_ts", 0) or 0)})
        acm = sorted(order, key=lambda x: (-x["solved"], x["penalty"], x["last_ac"], x["user"] or ""))
        for i, row in enumerate(acm, 1):
            row["rank"] = i
        by_score = sorted(order, key=lambda x: (-x["score"], -x["ac"], x["submit"], x["user"] or ""))
        snapshot = {"ts": now_ts(), "mode": "acm", "contest_start": contest_start,
                    "penalty_min": penalty_min, "problems": pids,
                    "total": len(order), "order": acm[:100],
                    "order_by_score": [{"user": r["user"], "nick": r["nick"], "score": r["score"],
                                        "rank": i} for i, r in enumerate(by_score[:100], 1)]}
        self.put_json("rank", snapshot)
        return snapshot

    # ========================================================= 命令总线
    def list_pending_cmds(self, limit=50):
        pairs = self.db.search_pairs(tag="cmd:", type_="both")
        out = []
        for _, raw in pairs:
            c = self.loads(raw, None)
            if isinstance(c, dict) and c.get("status", "pending") == "pending":
                out.append(c)
        out.sort(key=lambda x: int(x.get("ts") or 0))
        return out[:limit]

    def get_cmd(self, cid):
        return self.get_json("cmd:" + str(cid), None)

    def put_cmd(self, cid, op, args=None, user=None, token=None):
        c = {"cid": str(cid), "op": op, "args": args or {}, "user": user or "",
             "token": token or "", "status": "pending", "ts": now_ts()}
        self.put_json("cmd:" + str(cid), c)
        return c

    def reply(self, cid, ok, data=None, msg=""):
        payload = {"ok": bool(ok), "data": data if data is not None else {},
                   "msg": msg or ("ok" if ok else "error"), "ts": now_ts()}
        self.put_json("reply:" + str(cid), payload)
        c = self.get_cmd(cid)
        if isinstance(c, dict):
            c["status"] = "done" if ok else "error"
            c["handled_ts"] = now_ts()
            self.put_json("cmd:" + str(cid), c)
        return payload

    # ============================================================ 运行时
    def heartbeat(self, info):
        return self.put_json("judge:" + self.judge_id,
                             dict(info, id=self.judge_id, ts=now_ts()))

    def offline(self):
        self.put_json("judge:" + self.judge_id,
                      {"id": self.judge_id, "ts": 0, "offline": True,
                       "host": os.environ.get("COMPUTERNAME", "host")})

    def judges_online(self, ttl=None):
        ttl = ttl or int(self.cfg.getv("judge.heartbeat_interval_s", 15)) * 4
        out = []
        for tag, raw in self.db.search_pairs(tag="judge:", type_="both"):
            j = self.loads(raw, None)
            if isinstance(j, dict) and (now_ts() - int(j.get("ts") or 0)) <= ttl:
                out.append(j)
        return out

    # ==================================================== 多机共判：集群视图
    def cluster_snapshot(self, ttl=None):
        """返回在线判题机列表（含各自余力），用于计算"我该抢多少"。

        每条：{id, host, workers, busy, free, langs, load_pct, weighted_free, ts}
        weighted_free = 空闲槽位 × CPU 余量惩罚，用来做按能力分摊。
        """
        ttl = ttl or int(self.cfg.getv("judge.cluster_ttl_s", 45))
        now = now_ts()
        rows = []
        for j in self.judges_online(ttl):
            workers = max(1, int(j.get("workers") or 1))
            busy = max(0, int(j.get("busy") or 0))
            free = max(0, workers - busy)
            load = float(j.get("load_pct") or 0) / 100.0
            # CPU 越忙，越不该抢新活；下限 0.15 避免完全停手
            penalty = max(0.15, 1.0 - load)
            rows.append({"id": j.get("id"), "host": j.get("host"), "workers": workers,
                         "busy": busy, "free": free, "langs": j.get("langs") or [],
                         "load_pct": int(load * 100),
                         "weighted_free": round(free * penalty, 3),
                         "queue": int(j.get("queue") or 0),
                         "paused": bool(j.get("paused")),
                         "share": j.get("share"),
                         "share_mode": j.get("share_mode", ""),
                         "judged": int((j.get("stats") or {}).get("judged") or 0),
                         "ts": int(j.get("ts") or 0), "age_s": now - int(j.get("ts") or 0)})
        rows.sort(key=lambda r: str(r.get("id")))
        return rows

    def claim_share(self, judge_id=None, own_free=1, own_load_pct=0, cluster=None):
        """算"这个任务我该不该抢"的概率：自己余力 / 集群余力。

        没有别人在线（或快照拿不到）时返回 1.0（独占模式，不影响单机使用）。
        """
        judge_id = judge_id or self.judge_id
        cluster = cluster if cluster is not None else self.cluster_snapshot()
        others = [r for r in cluster if r.get("id") != judge_id and not r.get("paused")]
        me = [r for r in cluster if r.get("id") == judge_id]
        my_load = own_load_pct if me and not me[0].get("load_pct") else \
            (me[0].get("load_pct") if me else own_load_pct)
        my_penalty = max(0.15, 1.0 - float(my_load or 0) / 100.0)
        my_weight = max(0.0, own_free) * my_penalty
        other_weight = sum(max(0.0, r.get("weighted_free") or 0) for r in others)
        total = my_weight + other_weight
        if total <= 0 or not others:
            return 1.0
        p = my_weight / total
        lo = float(self.cfg.getv("judge.claim_min_prob", 0.08))
        return max(lo, min(1.0, p))

    def cluster_summary(self, cluster=None):
        cluster = cluster if cluster is not None else self.cluster_snapshot()
        return {"judges": len(cluster),
                "workers": sum(r["workers"] for r in cluster),
                "free": sum(r["free"] for r in cluster),
                "busy": sum(r["busy"] for r in cluster),
                "langs": sorted({l for r in cluster for l in (r.get("langs") or [])}),
                "rows": cluster}

    def write_meta(self, extra=None):
        meta = {"schema": SCHEMA, "system": "OJ-OJOJOJ",
                "updated": now_ts(), "judge_id": self.judge_id,
                "online_judges": [j.get("id") for j in self.judges_online()],
                "limits": self.cfg.getv("limits", {})}
        if extra:
            meta.update(extra)
        return self.put_json("oj:meta", meta)

    def set_ann(self, title, body, n=None):
        n = n or int(time.time())
        self.put_json("ann:%d" % n, {"n": n, "title": title, "body": body, "ts": now_ts()})
        self.put_json("ann:latest", {"n": n, "title": title, "body": body, "ts": now_ts()})
        return n

    # ========================================================== 维护任务
    def expire_own_leases(self, judge_id=None):
        """启动时把自己上次运行遗留的租约作废（对齐 MiniJudge：遗留任务按租约恢复）。

        只碰自己 judge_id 的记录，不会抢别的判题机正在跑的任务。
        """
        jid = judge_id or self.judge_id
        n = 0
        for sub in self.scan_by_status(STATUS_JUDGING):
            if sub.get("judge") == jid and int(sub.get("lease_until") or 0) > 0:
                sub["lease_until"] = 0
                self.put_sub(sub)
                n += 1
        return n

    def recover_stale(self, ttl_s=None):
        """租约到期恢复（对齐 MiniJudge lease-expired）：执行器失联的任务形成 JE 并重试。"""
        n = 0
        for sub in self.scan_by_status(STATUS_JUDGING):
            sid = sub.get("sid")
            until = int(sub.get("lease_until") or 0)
            if until and until > now_ts():
                continue                      # 租约还在有效期内，别抢
            reason = "判题机失联（租约到期）"
            res = self.fail_submission(sid, reason, verdict="JE", retry=True)
            if res is not None:
                n += 1
                self._log("WARN", "提交 %s 租约到期 → %s" % (sid, res.get("msg", reason)))
        return n

    # ==================================================== 候选重判批次
    # 对齐 MiniJudge：重判先产出候选结果（cres:），由 apply/cancel 决定是否发布。
    @staticmethod
    def rej_tag(bid):
        return "rej:" + str(bid)

    def create_rejudge_batch(self, sids, by="cli", note=""):
        bid = "R%d%03d" % (int(time.time()) % 1000000, random.randint(0, 999))
        for sid in sids:
            sub = self.get_sub(sid)
            if not sub:
                continue
            # 关键：不动 status/verdict/score（参赛者视图保持不变），只标记候选
            sub.update({"rejudge": bid, "candidate_status": "queued",
                        "candidate_verdict": "", "candidate_score": 0})
            self.put_sub(sub)
            self.enqueue(sid, sub, candidate=bid)
        self.put_json(self.rej_tag(bid), {"batch": bid, "status": "running",
                                          "sids": list(sids), "by": by,
                                          "note": note, "created": now_ts()})
        return bid

    def get_rejudge_batch(self, bid):
        return self.get_json(self.rej_tag(bid), None)

    def list_rejudge_batches(self):
        out = []
        for _, raw in self.db.search_pairs(tag="rej:", type_="both"):
            b = self.loads(raw, None)
            if isinstance(b, dict):
                out.append(b)
        out.sort(key=lambda x: int(x.get("created") or 0), reverse=True)
        return out

    def apply_rejudge(self, bid):
        """把候选结果发布成正式结果。"""
        batch = self.get_rejudge_batch(bid)
        if not batch:
            return 0, "批次不存在: %s" % bid
        n = 0
        for sid in batch.get("sids", []):
            cres = self.get_json(self.cres_tag(sid), None)
            if not isinstance(cres, dict):
                continue
            sub = self.get_sub(sid)
            if not sub:
                continue
            self.put_json(self.res_tag(sid), cres)
            sub.update({"status": STATUS_DONE, "verdict": cres.get("verdict"),
                        "score": int(cres.get("score") or 0),
                        "cases_passed": sum(1 for c in cres.get("cases", [])
                                            if c.get("verdict") == "AC"),
                        "case_count": len(cres.get("cases", [])),
                        "msg": "重判发布: %s" % cres.get("verdict"),
                        "rejudge": "", "candidate_status": "applied",
                        "finished": now_ts()})
            self.put_sub(sub)
            self.del_tag(self.cres_tag(sid))
            n += 1
        batch.update({"status": "applied", "applied": now_ts(), "applied_count": n})
        self.put_json(self.rej_tag(bid), batch)
        return n, ""

    def cancel_rejudge(self, bid):
        batch = self.get_rejudge_batch(bid)
        if not batch:
            return 0, "批次不存在: %s" % bid
        n = 0
        for sid in batch.get("sids", []):
            if self.del_tag(self.cres_tag(sid)):
                n += 1
            sub = self.get_sub(sid)
            if sub:
                sub.update({"rejudge": "", "candidate_status": "cancelled"})
                self.put_sub(sub)
        batch.update({"status": "cancelled", "cancelled": now_ts()})
        self.put_json(self.rej_tag(bid), batch)
        return n, ""

    # ======================================================= 备份 / 恢复
    def export_all(self, include=None, exclude_prefixes=("sess:", "lock:", "q:")):
        """把云端全部标签导出成 {tag: value}（可按前缀过滤），用于备份。"""
        out = {}
        for tag, raw in self.db.search_pairs(tag=include or "", type_="both"):
            if any(tag.startswith(p) for p in exclude_prefixes):
                continue
            out[tag] = raw
        return out

    def import_all(self, data, overwrite=True, only_missing=False):
        """把备份写回云端；返回 (写入数, 跳过数)。"""
        wrote = skipped = 0
        for tag, value in (data or {}).items():
            if only_missing and self.db.get(tag, None) is not None:
                skipped += 1
                continue
            if not overwrite and self.db.get(tag, None) is not None:
                skipped += 1
                continue
            if self.db.update(tag, value):
                wrote += 1
            else:
                skipped += 1
        return wrote, skipped

    def backup_to_file(self, path, note=""):
        data = self.export_all()
        payload = {"system": "OJ-OJOJOJ", "schema": SCHEMA, "ts": now_ts(),
                   "judge": self.judge_id, "note": note, "count": len(data),
                   "tags": data}
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        return len(data)

    def restore_from_file(self, path, only_missing=False):
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        tags = payload.get("tags") if isinstance(payload, dict) else None
        if not isinstance(tags, dict):
            raise ValueError("备份文件格式不正确（缺少 tags）")
        return self.import_all(tags, only_missing=only_missing)

    def archive(self, ttl_h=None, keep_last=60):
        """归档：done 且超过 TTL 的提交瘦身到 arc:，删掉 sub:/code:/res:，保持热命名空间有界。"""
        ttl = int(ttl_h if ttl_h is not None else self.cfg.getv("judge.archive_ttl_h", 24))
        cutoff = now_ts() - ttl * 3600
        done = [s for s in self.scan_by_status(STATUS_DONE)]
        done.sort(key=lambda x: int(x.get("ts") or 0), reverse=True)
        victims = [s for s in done[keep_last:] if int(s.get("ts") or 0) < cutoff]
        n = 0
        for s in victims:
            sid = s.get("sid")
            if not sid:
                continue
            res = self.get_result(sid)
            slim = {"sid": sid, "user": s.get("user"), "pid": s.get("pid"),
                    "lang": s.get("lang"), "verdict": s.get("verdict"),
                    "score": s.get("score", 0), "ts": s.get("ts"),
                    "cases_passed": s.get("cases_passed", 0),
                    "case_count": s.get("case_count", 0),
                    "archived": now_ts(),
                    "cases": (res or {}).get("cases", []) if self.cfg.getv("judge.archive_keep_cases", False) else []}
            self.put_json(self.arc_tag(sid), slim)
            self.del_tag(self.res_tag(sid))
            self.del_tag(self.code_tag(sid))
            self.del_tag(self.sub_tag(sid))
            self.del_tag(self.q_tag(sid))
            n += 1
        return n
