# -*- coding: utf-8 -*-
"""TinyWebDB REST 客户端（OJ-OJOJOJ 专用）

云端只有 action=update/get/delete/count/search 五个动作，本模块是其健壮封装：

* POST form-urlencoded 到 <base>，必带 user / secret / action
* 实测语义固化（见 docs/ARCHITECTURE.md §2）：
    - search 必须显式传 count，否则默认 1 条
    - search 的 tag 为「子串包含」匹配
    - search 返回顺序不可依赖
    - 单次最多 100 条，用 no 分页
* 指数退避重试 + 全局最小请求间隔（对社区服务礼貌且抗抖动）
* 值一律字符串；get_json/put_json 负责 JSON 编解码
"""
from __future__ import annotations

import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

__all__ = ["TinyWebDB", "TwdbError", "TwdbNetworkError"]


class TwdbError(Exception):
    """协议层错误（返回不是预期 JSON、update 未被确认等）。"""


class TwdbNetworkError(TwdbError):
    """网络/HTTP 层错误（可重试）。"""


class TinyWebDB(object):
    def __init__(self, base, user, secret, timeout_s=15.0, retries=5,
                 min_interval_s=0.3, logger=None, page_size=100, max_pages=20):
        self.base = base.rstrip("/")
        self.user = user
        self.secret = secret
        self.timeout_s = float(timeout_s)
        self.retries = int(retries)
        self.min_interval_s = float(min_interval_s)
        self.page_size = int(page_size)
        self.max_pages = int(max_pages)
        self._log = logger

        self._rl_lock = threading.Lock()
        self._next_ok = 0.0
        self._penalty_until = 0.0      # 被 503/429 打回后的静默期
        self._penalty_level = 0
        self._stats_lock = threading.Lock()
        self.stats = {"requests": 0, "errors": 0, "retries": 0, "throttled": 0,
                      "bytes_in": 0, "seconds": 0.0}

    # ------------------------------------------------------------------ 日志
    def _logline(self, level, msg):
        if self._log:
            try:
                self._log(level, msg)
                return
            except Exception:
                pass
        if level in ("WARN", "ERROR"):
            print("[twdb][%s] %s" % (level, msg))

    # -------------------------------------------------------------- 限速器
    def _throttle(self):
        with self._rl_lock:
            now = time.time()
            wait = max(self._next_ok, self._penalty_until) - now
            if wait > 0:
                time.sleep(min(wait, 30.0))
            base = max(0.05, self.min_interval_s)
            self._next_ok = max(time.time(), self._next_ok) + base

    def _penalize(self, why):
        """服务打回 503/429 时指数静默：这是社区公共小服务，必须自觉退避。"""
        with self._rl_lock:
            self._penalty_level = min(self._penalty_level + 1, 6)
            secs = min(2 ** self._penalty_level, 30)
            self._penalty_until = time.time() + secs
            self.min_interval_s = min(1.5, max(0.3, self.min_interval_s) * 1.4)
            with self._stats_lock:
                self.stats["throttled"] += 1
        self._logline("WARN", "服务端限流(%s)：静默 %ss，间隔提升到 %.2fs"
                      % (why, secs, self.min_interval_s))

    def _reward(self):
        """连续成功则缓慢恢复速度。"""
        with self._rl_lock:
            if self._penalty_level > 0:
                self._penalty_level -= 1
            self.min_interval_s = max(0.3, self.min_interval_s * 0.85)

    # ------------------------------------------------------------ 核心请求
    def call(self, action, **params):
        """执行一次 API 调用，返回解析后的 Python 对象（可能是 dict / None）。"""
        form = {"user": self.user, "secret": self.secret, "action": action}
        for k, v in params.items():
            if v is None:
                continue
            if isinstance(v, bool):
                v = "true" if v else "false"
            form[k] = str(v)
        body = urllib.parse.urlencode(form).encode("utf-8")

        attempt = 0
        last_err = None
        while attempt <= self.retries:
            attempt += 1
            self._throttle()
            t0 = time.time()
            try:
                req = urllib.request.Request(
                    self.base, data=body,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "User-Agent": "OJ-Judge/1.0 (+D:\\OJ)",
                        "Accept": "application/json",
                    },
                    method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    raw = resp.read()
                dt = time.time() - t0
                with self._stats_lock:
                    self.stats["requests"] += 1
                    self.stats["bytes_in"] += len(raw)
                    self.stats["seconds"] += dt
                if attempt > 1 or self._penalty_level:
                    self._reward()
                return self._parse(raw, action)
            except urllib.error.HTTPError as e:
                last_err = TwdbNetworkError("HTTP %s on %s" % (e.code, action))
                if e.code in (429, 502, 503, 504):
                    self._penalize("HTTP %s" % e.code)
                elif 400 <= e.code < 500:
                    raise last_err  # 客户端错误不重试
            except urllib.error.URLError as e:
                last_err = TwdbNetworkError("URLError on %s: %s" % (action, e.reason))
            except TwdbNetworkError as e:
                last_err = e
            except Exception as e:  # noqa: BLE001
                last_err = TwdbError("unexpected on %s: %r" % (action, e))

            with self._stats_lock:
                self.stats["errors"] += 1
                self.stats["retries"] += 1
            if attempt > self.retries:
                break
            backoff = min(20.0, (0.5 * (2 ** (attempt - 1)))) * (0.7 + 0.6 * random.random())
            self._logline("WARN", "%s 失败(%s)，%.1fs 后重试 %d/%d"
                          % (action, last_err, backoff, attempt, self.retries))
            time.sleep(backoff)
        raise last_err or TwdbError("call failed: %s" % action)

    @staticmethod
    def _parse(raw, action):
        text = (raw or b"").decode("utf-8", "replace").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except ValueError:
            raise TwdbError("非 JSON 响应 (action=%s): %r" % (action, text[:160]))

    # ------------------------------------------------------------ 基础动作
    def update(self, tag, value):
        """写入标签，返回 True 表示服务端确认 success。"""
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise TypeError("value 必须是 str，复合结构请用 put_json")
        res = self.call("update", tag=tag, value=value)
        ok = isinstance(res, dict) and str(res.get("status", "")).lower() == "success"
        if not ok:
            self._logline("WARN", "update(%s) 未确认: %r" % (tag, res))
        return ok

    def get(self, tag, default=None):
        """读取标签原始字符串；不存在返回 default。

        注意：云端 delete 是"软删除"——search/count 里没了，但 get 会返回字符串 "null"。
        这里统一把字面量 "null" 当成不存在，避免上层误判"标签还在"。
        """
        res = self.call("get", tag=tag)
        if res is None:
            return default
        val = None
        found = False
        if isinstance(res, dict):
            if tag in res:
                val, found = res[tag], True
            elif not res:
                return default
            elif len(res) == 1:
                val, found = list(res.values())[0], True
            else:
                return default
        elif isinstance(res, list):
            return default
        else:
            val, found = res, True
        if not found or val is None or val == "null":
            return default
        return val

    def delete(self, tag):
        try:
            self.call("delete", tag=tag)
            return True
        except TwdbError as e:
            self._logline("WARN", "delete(%s) 失败: %s" % (tag, e))
            return False

    def count(self):
        res = self.call("count")
        if isinstance(res, dict):
            try:
                return int(res.get("count", 0))
            except (TypeError, ValueError):
                return 0
        return 0

    def search(self, tag="", no=1, count=None, type_="both"):
        """单次查询。返回 dict，形如：
           type=both -> {tag: value}
           type=tag  -> {"__tags__": [tag, ...]}
           type=value-> {"__values__": [value, ...]}
        """
        count = self.page_size if count is None else int(count)
        count = max(1, min(100, count))  # 实测上限 100
        res = self.call("search", tag=tag or "", no=int(no), count=count, type=type_)
        if res is None:
            return {}
        if isinstance(res, list):
            return {"__tags__": res} if type_ == "tag" else {}
        if not isinstance(res, dict):
            return {}
        # 归一化 type=tag / type=value 的返回
        if len(res) == 1:
            only_key = next(iter(res))
            only_val = res[only_key]
            if only_key == "tag" and isinstance(only_val, list):
                return {"__tags__": only_val}
            if only_key == "value" and isinstance(only_val, list):
                return {"__values__": only_val}
        return {k: v for k, v in res.items() if not k.startswith("__")}

    # --------------------------------------------------------- 分页/高级查询
    def search_pairs(self, tag="", limit=None, type_="both"):
        """分页枚举，返回 [(tag, value), ...]。

        容错：只要**有一个** value 含有破坏 JSON 的字符，整页 search 都会解析失败。
        此时自动退化为 type=tag 枚举标签名，再逐个 get（坏标签跳过），保证枚举不中断。
        """
        limit = limit or (self.page_size * self.max_pages)
        out = []
        no = 1
        for _ in range(self.max_pages):
            try:
                page = self.search(tag=tag, no=no, count=self.page_size, type_=type_)
            except TwdbError as e:
                self._logline("WARN", "search(tag=%r) 解析失败(%s)，改用 type=tag 逐条兜底" % (tag, e))
                return self._search_pairs_fallback(tag, limit)
            if not page:
                break
            if "__tags__" in page:
                items = [(t, None) for t in page["__tags__"]]
            elif "__values__" in page:
                items = [(None, v) for v in page["__values__"]]
            else:
                items = list(page.items())
            if not items:
                break
            out.extend(items)
            if len(items) < self.page_size or len(out) >= limit:
                break
            no += self.page_size
        return out[:limit]

    def _search_pairs_fallback(self, tag="", limit=None):
        """单条读取兜底：坏标签不会拖垮整个枚举。"""
        limit = limit or (self.page_size * self.max_pages)
        out = []
        try:
            tags = self.search_tags(tag=tag, limit=limit)
        except TwdbError:
            return out
        for t in tags:
            try:
                v = self.get(t, None)
            except TwdbError:
                self._logline("WARN", "跳过坏标签 %s（value 破坏了云端 JSON）" % t)
                continue
            out.append((t, v))
        return out

    def search_tags(self, tag="", limit=None):
        return [t for t, _ in self.search_pairs(tag=tag, limit=limit, type_="tag")]

    def search_map(self, tag="", limit=None):
        """{tag: value}，重复 tag 以后者覆盖。"""
        return dict(self.search_pairs(tag=tag, limit=limit, type_="both"))

    # ------------------------------------------------------------- JSON 层
    def get_json(self, tag, default=None):
        raw = self.get(tag, None)
        if raw is None or raw == "":
            return default
        if isinstance(raw, (dict, list)):
            return raw
        try:
            return json.loads(raw)
        except ValueError:
            return default

    def put_json(self, tag, obj):
        return self.update(tag, dumps(obj))

    # ---------------------------------------------------------------- 工具
    def ping(self):
        t0 = time.time()
        try:
            n = self.count()
            return {"ok": True, "count": n, "ms": int((time.time() - t0) * 1000)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e), "ms": int((time.time() - t0) * 1000)}

    def snapshot_stats(self):
        with self._stats_lock:
            return dict(self.stats)


def dumps(obj):
    """紧凑 JSON，保留中文（省流量、App Inventor 直接可读）。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def loads(text, default=None):
    if text is None or text == "":
        return default
    if isinstance(text, (dict, list)):
        return text
    try:
        return json.loads(text)
    except ValueError:
        return default


# ------------------------------------------------------------------ 自测
if __name__ == "__main__":
    import sys
    base = sys.argv[1] if len(sys.argv) > 1 else "https://tinywebdb.appinventor.space/api"
    db = TinyWebDB(base, "YOUR_USER", "YOUR_SECRET")
    print("ping  :", db.ping())
    print("probs :", db.search(tag="prob:", count=100, type_="tag"))
    print("get   :", db.get("prob:P1001"))
