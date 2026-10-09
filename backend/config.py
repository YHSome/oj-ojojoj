# -*- coding: utf-8 -*-
"""配置加载：config/oj_config.json（入库） + config/oj_config.local.json（不入库，放密钥）。

  * 公开仓库里只保留占位符，真实的 user/secret/admin_key/路径写进 local 文件
  * 找不到 paths.root 时自动回落到仓库目录，便于别人 clone 到任意位置
  * 支持 --set a.b.c=value 覆盖
"""
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(REPO_ROOT, "config", "oj_config.json")
LOCAL_CONFIG_NAME = "oj_config.local.json"
PATH_KEYS = ("data", "problems", "work", "cache", "state", "logs", "tmp",
             "toolchain_dirs", "python")


class Config(dict):
    """点号访问的配置对象：cfg['judge.workers'] / cfg.get_path('logs')"""

    def __init__(self, data=None, path=None):
        super(Config, self).__init__(data or {})
        self.source = path          # 配置文件路径（注意：不要占用 path() 方法名）

    # ---- 点号读写 ----------------------------------------------------
    def _walk(self, key, create=False):
        parts = key.split(".")
        node = self
        for p in parts[:-1]:
            if p not in node or not isinstance(node[p], dict):
                if not create:
                    return None, None
                node[p] = {}
            node = node[p]
        return node, parts[-1]

    def getv(self, key, default=None):
        node, last = self._walk(key)
        if node is None:
            return default
        return node.get(last, default)

    def setv(self, key, value):
        node, last = self._walk(key, create=True)
        node[last] = value
        return value

    def path(self, name):
        p = self.getv("paths." + name, None)
        if p is None:
            raise KeyError("paths.%s 未配置" % name)
        return p

    def lang_table(self):
        return {k: v for k, v in (self.getv("languages", {}) or {}).items()
                if isinstance(v, dict) and v.get("enabled", True)}


def _coerce(text):
    t = text.strip()
    low = t.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none"):
        return None
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    return text


def _deep_merge(base, extra):
    """递归合并：local 配置覆盖 base，列表整体替换。"""
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def local_config_path(cfg_path=None):
    return os.path.join(os.path.dirname(cfg_path or DEFAULT_CONFIG), LOCAL_CONFIG_NAME)


PATH_DEFAULTS = {
    "data": "data",
    "problems": "data/problems",
    "work": "data/work",
    "cache": "data/cache",
    "state": "data/state",
    "logs": "logs",
    "tmp": "data/tmp",
}


def _fix_portable_paths(cfg):
    """把路径补成可用的绝对路径：空值/相对值一律基于仓库目录（clone 到任何位置都能跑）。

    公开仓库里的 oj_config.json 只有占位符和空路径，真实路径由
    config/oj_config.local.json 覆盖；没有 local 文件时就走这里的默认值。
    """
    root = cfg.getv("paths.root", "") or ""
    if not (isinstance(root, str) and root.strip() and os.path.isdir(root)):
        root = REPO_ROOT
        cfg.setv("paths.root", root)
    for name, rel in PATH_DEFAULTS.items():
        cur = cfg.getv("paths." + name, "")
        if not (isinstance(cur, str) and cur.strip()):
            cfg.setv("paths." + name, os.path.join(root, *rel.split("/")))
        elif not os.path.isabs(cur):
            cfg.setv("paths." + name, os.path.join(root, cur))
    dirs = cfg.getv("paths.toolchain_dirs", []) or []
    cfg.setv("paths.toolchain_dirs",
             [d if os.path.isabs(d) else os.path.join(root, d) for d in dirs if d])
    if not cfg.getv("paths.python"):
        cfg.setv("paths.python", sys.executable)
    if not cfg.getv("crypto.private_key"):
        cfg.setv("crypto.private_key", os.path.join(cfg.getv("paths.state"), "judge_key.json"))
    return True


def load(path=None, overrides=None, ensure_dirs=True):
    path = path or os.environ.get("OJ_CONFIG") or DEFAULT_CONFIG
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    local_path = local_config_path(path)
    if os.path.isfile(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                _deep_merge(data, json.load(f))
        except ValueError as e:
            raise SystemExit("%s 不是合法 JSON: %s" % (local_path, e))
    cfg = Config(data, path)
    cfg.local_path = local_path if os.path.isfile(local_path) else None
    _fix_portable_paths(cfg)
    for item in (overrides or []):
        if "=" not in item:
            raise SystemExit("--set 需要 k=v 形式: %r" % item)
        k, v = item.split("=", 1)
        cfg.setv(k.strip(), _coerce(v))
    if ensure_dirs:
        for name in ("data", "problems", "work", "cache", "state", "logs", "tmp"):
            try:
                os.makedirs(cfg.path(name), exist_ok=True)
            except OSError:
                pass
    return cfg


def load_quiet(path=None):
    try:
        return load(path, ensure_dirs=False)
    except Exception:
        return Config({}, None)


if __name__ == "__main__":
    c = load(sys.argv[1] if len(sys.argv) > 1 else None)
    print(json.dumps(c, ensure_ascii=False, indent=2))
