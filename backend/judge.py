# -*- coding: utf-8 -*-
"""评测核心：编译矩阵 + 逐点执行 + 评测机 + 判分。

对齐 MiniJudge（https://github.com/Mkrari/MiniJudge）的判题语义：
  * 判定白名单：AC WA TLE MLE RE CE OLE JE（JE = 判题机自身故障，交由上层重试）
  * 比较器：tokens（默认，C locale 空白分词）/ exact（逐字节）/ float（绝对+相对容差）/ custom(spj)
  * 语言目录带 time_factor：解释器/JVM 语言按 2 倍墙钟时间
  * 每个测试点在**独立目录**里运行，程序不能靠上一个测试点留下的文件传递状态
  * stdout 有上限（OLE）；stderr 截断保存

单点判定优先级：执行期故障（TLE/MLE/OLE/RE）> 比较结果 > AC
总分：全过 = AC（满分）；部分通过 = PAC；全不过 = 首个失败点的判定。
"""
from __future__ import annotations

import os
import shutil
import sys

import runner
from runner import OK, TLE, MLE, RE, OLE, INTERNAL

AC, WA, TLE_V, MLE_V, RE_V, CE, OLE_V, PE, PAC, UD, SKIP, JE = (
    "AC", "WA", "TLE", "MLE", "RE", "CE", "OLE", "PE", "PAC", "UD", "SKIP", "JE")

# MiniJudge 的终态白名单
TERMINAL = {"AC", "WA", "TLE", "MLE", "RE", "CE", "OLE", "JE"}

_RUN_STATUS = {TLE: TLE_V, MLE: MLE_V, RE: RE_V, OLE: OLE_V, INTERNAL: JE}


# ============================================================== 比较器
def normalize(text, ignore_trailing_ws=True, ignore_trailing_newline=True):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if ignore_trailing_ws:
        text = "\n".join(line.rstrip() for line in text.split("\n"))
    if ignore_trailing_newline:
        text = text.rstrip("\n")
    return text


def compare_tokens(out_text, ans_text, cfg=None):
    """MiniJudge 默认策略 tokens：按 C locale 空白切分后逐 token 比较。"""
    a, b = out_text.split(), ans_text.split()
    if a == b:
        return AC, ""
    if len(a) != len(b):
        return WA, "token 个数不同: 期望 %d 实际 %d" % (len(b), len(a))
    for i, (x, y) in enumerate(zip(a, b), 1):
        if x != y:
            return WA, "第 %d 个 token 不同: 期望 %r 实际 %r" % (i, y[:40], x[:40])
    return WA, "输出不一致"


def compare_exact(out_text, ans_text, cfg=None):
    a = out_text.replace("\r\n", "\n").replace("\r", "\n")
    b = ans_text.replace("\r\n", "\n").replace("\r", "\n")
    return (AC, "") if a == b else (WA, "与标准输出不完全一致（exact 严判）")


def compare_float(out_text, ans_text, cfg=None):
    """float：绝对容差 + 相对容差（对齐 float_absolute_tolerance / float_relative_tolerance）。"""
    cfg = cfg if isinstance(cfg, dict) else {}
    eps = float(cfg.get("float_eps", cfg.get("absolute_tolerance", 1e-6)) or 0)
    rel = float(cfg.get("float_relative_eps", cfg.get("relative_tolerance", 0)) or 0)
    toks_a, toks_b = out_text.split(), ans_text.split()
    if len(toks_a) != len(toks_b):
        return WA, "token 个数不同: 期望 %d 实际 %d" % (len(toks_b), len(toks_a))
    for i, (x, y) in enumerate(zip(toks_a, toks_b), 1):
        try:
            fx, fy = float(x), float(y)
        except ValueError:
            if x != y:
                return WA, "第 %d 个 token 不同: %r vs %r" % (i, y, x)
            continue
        if abs(fx - fy) <= eps or (rel > 0 and abs(fx - fy) <= rel * max(1.0, abs(fy))):
            continue
        return WA, "第 %d 个数误差超限: 期望 %.10g 实际 %.10g" % (i, fy, fx)
    return AC, ""


CHECKERS = {"tokens": compare_tokens, "exact": compare_exact, "float": compare_float}
# 兼容旧名与 MiniJudge 名：diff->tokens、strict->exact、custom/icpc->spj
CHECKER_ALIAS = {"diff": "tokens", "cmp": "tokens", "token": "tokens",
                 "strict": "exact", "spj": "custom", "special": "custom",
                 "icpc": "custom"}


def canonical_checker(name):
    name = (name or "tokens").strip().lower()
    return CHECKER_ALIAS.get(name, name)


def compare_spj(checker_path, in_path, out_path, ans_path, cwd, timeout_ms=10000,
                env=None, env_replace=False):
    """自定义校验器（MiniJudge 的 custom）：python checker.py <in> <out> <ans>，退出 0=AC 1=WA 其它=JE。"""
    py = sys.executable
    so = os.path.join(cwd, "__spj.out")
    se = os.path.join(cwd, "__spj.err")
    r = runner.run_process([py, checker_path, in_path, out_path, ans_path],
                           cwd=cwd, stdin_path=os.devnull,
                           stdout_path=so, stderr_path=se,
                           time_limit_ms=timeout_ms, env=env, env_replace=env_replace)
    msg = read_text(so, 400).strip() or read_text(se, 400).strip()
    if r.status != OK:
        return JE, "校验器异常(%s): %s" % (r.status, msg[:200])
    if r.exit_code == 0:
        return AC, msg[:200]
    if r.exit_code == 1:
        return WA, msg[:200] or "校验器判 WA"
    return JE, "校验器退出码 %s: %s" % (r.exit_code, msg[:200])


# 常见错误提示（对教学友好：把最有用的那行挑出来 + 给一句人话解释）
HINTS = [
    ("TypeError: 'builtin_function_or_method' object is not iterable",
     "常见原因：input / read 这类函数忘了加括号。应写 input().split() 而不是 input.split"),
    ("TypeError: 'builtin_function_or_method' object is not subscriptable",
     "常见原因：函数忘了加括号就取下标，例如 input[0] 应为 input()[0]"),
    ("name 'input' is not defined", "Python2 写法？本项目按 Python 3 运行，用 input() 而不是 raw_input()"),
    ("NameError: name", "变量名拼错或未定义（注意大小写；map/len 等内置名不要当变量用）"),
    ("IndexError: list index out of range", "数组越界：检查下标是否从 0 开始、是否读满了 n 个元素"),
    ("ZeroDivisionError", "除数为 0：注意特判 b == 0 之类的边界"),
    ("ValueError: not enough values to unpack", "读入的数据个数和左边变量个数不一致（检查分隔符/换行）"),
    ("ValueError: invalid literal for int()", "读到了非数字：检查输入格式，用 input().split() 拆开"),
    ("RecursionError", "递归太深：改成迭代或加记忆化"),
    ("MemoryError", "内存不足：数据结构开太大了"),
    ("Segmentation fault", "C/C++ 段错误：数组越界 / 空指针 / 递归爆栈"),
    ("std::bad_alloc", "内存分配失败：开的空间超过内存限制或规模算错"),
    ("stack overflow", "递归层数过深导致爆栈"),
    ("double free", "重复释放内存 / 指针已失效"),
]


def hint_for(text):
    """从 stderr 里挑一句最有用的提示。"""
    low = (text or "").lower()
    for needle, hint in HINTS:
        if needle.lower() in low:
            return hint
    return ""


# 对外（选手可见）的判定文案：**不含标准答案、不含期望/实际对比**，
# 避免选手用"输出钓鱼"的方式试出隐藏测试点的答案。
PUBLIC_TEXT = {
    AC: "通过",
    WA: "答案错误",
    PE: "输出格式错误",
    TLE_V: "运行超时",
    MLE_V: "内存超限",
    RE_V: "运行错误",
    CE: "编译错误",
    OLE_V: "输出超限",
    PAC: "部分通过",
    JE: "判题机内部错误",
    SKIP: "跳过（题目数据缺失）",
}
# 这些判定天然不含答案信息，明细可以照常给出（时间/内存/退出码/自己的编译错误）
DETAIL_SAFE = {TLE_V, MLE_V, RE_V, CE, OLE_V, JE, SKIP}


def public_msg(verdict, detail, allow_detail, allow_stderr=True, stderr_text=""):
    """把内部比较结果转成对选手安全的文案。"""
    base = PUBLIC_TEXT.get(verdict, verdict)
    if verdict in DETAIL_SAFE:
        parts = [detail or base]
        if verdict == RE_V and allow_stderr and stderr_text:
            parts.append(stderr_text)
        return " | ".join(p for p in parts if p)
    if allow_detail:
        return " | ".join(p for p in (base, detail) if p)
    return base


def stderr_tail(path, lines=5, width=200):
    """取 stderr 末尾几行拼成一行摘要（比只看最后一行信息量大得多）。"""
    text = read_text(path).strip()
    if not text:
        return ""
    rows = [r.strip() for r in text.splitlines() if r.strip()]
    tail = rows[-lines:] if len(rows) > lines else rows
    return " ⏎ ".join(r[:width] for r in tail)


def scrub_paths(text, workdir=None):
    """把判题机本地路径洗成选手视角的名字（别泄露主机目录结构）。"""
    if not text:
        return text
    out = text
    if workdir:
        for variant in (workdir + os.sep, workdir + "/", workdir):
            out = out.replace(variant, "")
    out = out.replace(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "<judge>")
    return out


class Judge(object):
    def __init__(self, cfg, logger=None):
        self.cfg = cfg
        self._log = logger or (lambda lvl, msg: None)
        self.limits = cfg.getv("limits", {}) or {}
        self.langs = cfg.lang_table()
        self.alias = {str(k).lower(): v for k, v in (cfg.getv("languages_alias", {}) or {}).items()}
        # 语言运行时的可执行入口（python 用本机解释器，其余在 PATH/工具链目录找）
        self.python_exe = cfg.getv("paths.python", None) or sys.executable
        runner.set_toolchain_dirs(cfg.getv("paths.toolchain_dirs", []) or [])
        self.lang_status = {}
        self._probe_languages()

    # ------------------------------------------------------------ 语言自检
    def resolve_lang(self, lang):
        """MiniJudge 用 cpp17/c17/python3/java21，本项目用 cpp/c/py/java，二者都接受。"""
        key = str(lang or "").strip().lower()
        if key in self.langs:
            return key
        return self.alias.get(key, key)

    def time_factor(self, lang):
        return max(1, int((self.langs.get(self.resolve_lang(lang), {}) or {}).get("time_factor", 1)))

    def _probe_languages(self):
        """只检查每条命令的『程序名』（第一个 token，且不以 - 或 { 开头）。"""
        for key, lc in self.langs.items():
            missing = []
            for phase in ("compile", "run"):
                cmd = lc.get(phase) or []
                exe = None
                for tok in cmd:
                    if tok.startswith("{") or tok.startswith("-"):
                        continue
                    exe = tok
                    break
                if not exe:
                    continue
                if exe == "python":
                    if not os.path.isfile(self.python_exe) and runner.which("python") is None:
                        missing.append("python")
                elif runner.which(exe) is None:
                    missing.append(exe)
            self.lang_status[key] = missing
            if missing:
                self._log("WARN", "语言 %s 缺少可执行文件: %s（该语言提交将判 CE/跳过）"
                          % (key, ", ".join(missing)))

    def available_langs(self):
        return {k: v for k, v in self.langs.items() if not self.lang_status.get(k)}

    # ---------------------------------------------------------------- 工具
    def _fmt(self, cmd, mapping):
        """把模板里的 {exe}/{src}/{outdir} 展开，并把裸命令名解析为绝对路径。"""
        out = []
        for tok in cmd:
            s = str(tok)
            for k, v in mapping.items():
                s = s.replace("{%s}" % k, str(v))
            if s == "python":
                s = self.python_exe
            elif "{" not in s and os.sep not in s and "/" not in s:
                found = runner.which(s)
                if found:
                    s = found
            out.append(s)
        return out

    # -------------------------------------------------------------- 主流程
    def judge_submission(self, sub, code, problem, tests, workdir):
        """返回 (verdict, score, cases, compile_log, max_time_ms, max_mem_kb, msg, checker)"""
        if os.path.isdir(workdir):
            shutil.rmtree(workdir, ignore_errors=True)
        os.makedirs(workdir, exist_ok=True)

        lang = self.resolve_lang(sub.get("lang"))
        checker = canonical_checker(problem.get("checker") or self.cfg.getv("checker.default", "tokens"))
        t_base = int(problem.get("time_limit_ms") or self.limits.get("default_time_limit_ms", 1000))
        m_limit = int(problem.get("memory_limit_kb") or self.limits.get("default_memory_limit_kb", 262144))
        o_limit = int(problem.get("output_limit_kb") or self.limits.get("default_output_limit_kb", 8192))
        total_score = int(problem.get("total_score") or 100)
        err_limit = int(self.limits.get("stderr_limit_kb", 64))

        if lang not in self.langs:
            return (CE, 0, [], "不支持的语言: %s（可用: %s）" % (
                sub.get("lang"), ",".join(sorted(self.langs))), 0, 0, "语言不支持", checker)
        if self.lang_status.get(lang):
            return (CE, 0, [], "判题机缺少 %s 运行时: %s" % (lang, ", ".join(self.lang_status[lang])),
                    0, 0, "环境缺失", checker)
        if not tests:
            return (SKIP, 0, [], "", 0, 0, "题目无测试数据", checker)

        lc = self.langs[lang]
        t_limit = t_base * self.time_factor(lang)      # 解释器/JVM 语言放宽墙钟
        ext = lc.get("ext", lang)
        src = os.path.join(workdir, "Main." + ext if lang == "java" else "main." + ext)
        exe = os.path.join(workdir, "main.exe" if os.name == "nt" else "main")
        with open(src, "w", encoding="utf-8", newline="\n") as f:
            f.write(code)

        mapping = {"exe": exe, "src": src, "outdir": workdir, "workdir": workdir}
        env = self._toolchain_env()
        compile_ms = 0
        compile_log = ""
        if not lc.get("interpreted") and lc.get("compile"):
            cmd = self._fmt(lc["compile"], mapping)
            ok, compile_log, compile_ms = runner.compile_program(
                cmd, cwd=workdir,          # 一定要在选手的工作目录里编译
                timeout_ms=int(self.limits.get("compile_timeout_ms", 15000)),
                log_max=int(self.limits.get("compile_log_max_bytes", 8192)),
                env=env, env_replace=True,
                job_object=bool(self.limits.get("isolate", {}).get("compile_job_object", False)))
            if not ok:
                return (CE, 0, [], compile_log or "编译失败", 0, 0, "编译错误", checker)

        run_cmd = self._fmt(lc["run"], mapping)
        cases = []
        notes = []
        score = 0
        max_ms = 0
        max_kb = 0
        first_fail = None
        all_ok = True

        for idx, t in enumerate(tests, 1):
            # 每个测试点独立目录：程序无法靠上个测试点留下的文件作弊/传状态
            case_dir = os.path.join(workdir, "case%02d" % idx)
            os.makedirs(case_dir, exist_ok=True)
            in_path = os.path.join(case_dir, "input.txt")
            ans_path = os.path.join(case_dir, "answer.txt")
            out_path = os.path.join(case_dir, "stdout.txt")
            err_path = os.path.join(case_dir, "stderr.txt")
            write_text(in_path, t.get("in", ""))
            write_text(ans_path, t.get("out", ""))

            r = runner.run_process(run_cmd, cwd=case_dir,
                                   stdin_path=in_path, stdout_path=out_path,
                                   stderr_path=err_path,
                                   time_limit_ms=t_limit,
                                   memory_limit_kb=m_limit,
                                   output_limit_kb=o_limit,
                                   env=env, env_replace=True,
                                   kill_grace_ms=int(self.limits.get("kill_grace_ms", 500)),
                                   job_object=bool(self.limits.get("isolate", {}).get("job_object", True)),
                                   active_process_limit=int(self.limits.get("isolate", {}).get("active_process_limit", 8)),
                                   mem_sample_ms=int(self.limits.get("mem_sample_ms", 20)))
            max_ms = max(max_ms, r.time_ms or 0)
            max_kb = max(max_kb, r.memory_kb or 0)

            if r.status == OK:
                out_text = read_text(out_path)
                if r.time_ms and r.time_ms > t_limit:
                    v, msg = TLE_V, "运行 %dms 超过时限 %dms" % (r.time_ms, t_limit)
                elif checker == "custom":
                    checker_path = problem.get("checker_path") or os.path.join(
                        self.cfg.path("problems"), str(problem.get("pid")), "checker.py")
                    v, msg = compare_spj(checker_path, in_path, out_path, ans_path, case_dir,
                                         env=env, env_replace=True)
                else:
                    v, msg = CHECKERS.get(checker, compare_tokens)(
                        out_text, t.get("out", ""), self._checker_cfg(problem))
            else:
                v = _RUN_STATUS.get(r.status, JE)
                msg = r.detail or r.status
                tail = stderr_tail(err_path)
                if tail:
                    msg = "%s | %s" % (msg, tail)
                    hint = hint_for(tail)
                    if hint:
                        msg = "%s | 提示: %s" % (msg, hint)

            case_score = int(t.get("score", 0) or 0)
            if v == AC:
                score += case_score
            else:
                all_ok = False
                if first_fail is None:
                    first_fail = v

            # ---- 内部明细（只写判题机本地，不进云端、不给选手）
            allow_detail = bool(self.cfg.getv("judge.public_case_detail", False))
            allow_stderr = bool(self.cfg.getv("judge.public_stderr", True))
            raw_detail = msg or v
            raw_err = scrub_paths(truncate(read_text(err_path), err_limit * 1024)[:2048], workdir)
            public = public_msg(v, scrub_paths(raw_detail, workdir), allow_detail,
                                allow_stderr, scrub_paths(stderr_tail(err_path), workdir))
            if v not in (AC,) and (not allow_detail):
                # 明细留在本地，管理员可复盘；选手侧只看到判定
                self._log("DEBUG", "case %d/%d %s 明细: %s" % (idx, len(tests), v, raw_detail[:300]))
                notes.append("case %d 判定=%s\n  明细: %s\n" % (idx, v, raw_detail))

            cases.append({"i": idx, "verdict": v, "time_ms": r.time_ms or 0,
                          "memory_kb": r.memory_kb or 0, "score": case_score if v == AC else 0,
                          "msg": public[:600],
                          "stderr": (raw_err if (allow_stderr and v == RE_V) else "")[:2048]})

        if notes:
            try:
                with open(os.path.join(workdir, "__judge_detail.txt"), "w",
                          encoding="utf-8") as f:
                    f.write("# 判题机内部明细（不发给选手，仅供管理员复盘）\n")
                    f.write("".join(notes))
            except OSError:
                pass

        if all_ok:
            verdict, final_score = AC, max(score, 0) or total_score
            msg = "全部通过 %d/%d 点" % (len(cases), len(cases))
        elif score > 0:
            verdict, final_score = PAC, score
            msg = "部分通过 %d/%d 点，得分 %d" % (sum(1 for c in cases if c["verdict"] == AC), len(cases), score)
        else:
            verdict, final_score = first_fail or WA, 0
            msg = "首个失败点: %s" % verdict
        if compile_ms:
            msg += " | 编译 %dms" % compile_ms
        return (verdict, final_score, cases, scrub_paths(compile_log, workdir),
                max_ms, max_kb, msg, checker)

    def _checker_cfg(self, problem):
        """把题目里的浮点容差字段合并成比较器配置。"""
        cfg = dict(self.cfg.getv("checker", {}) or {})
        for src, dst in (("float_absolute_tolerance", "float_eps"),
                         ("float_eps", "float_eps"),
                         ("float_relative_tolerance", "float_relative_eps"),
                         ("float_relative_eps", "float_relative_eps")):
            if problem.get(src) is not None:
                cfg[dst] = problem[src]
        return cfg

    def _toolchain_env(self):
        """构造**干净且完整**的子进程环境（判题必须确定性，且不能被宿主环境污染）。
        """
        keep = ("SystemRoot", "SystemDrive", "windir", "COMSPEC", "PATHEXT",
                "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER",
                "OS", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH",
                "ProgramData", "ProgramFiles", "ProgramFiles(x86)", "ALLUSERSPROFILE",
                "PUBLIC", "PYTHONIOENCODING", "PYTHONUTF8")
        env = {k: os.environ[k] for k in keep if k in os.environ}
        for name, value in (("PYTHONIOENCODING", "utf-8"), ("PYTHONUTF8", "1")):
            env.setdefault(name, value)

        dirs = [d for d in (self.cfg.getv("paths.toolchain_dirs", []) or []) if d]
        sysroot = env.get("SystemRoot", r"C:\Windows")
        dirs += [os.path.join(sysroot, "system32"), sysroot,
                 os.path.join(sysroot, "System32", "Wbem")]
        # 只保留 Windows 形态的宿主 PATH 项（跳过 /c/... 这类 MSYS 路径）
        for item in os.environ.get("PATH", "").split(os.pathsep):
            item = item.strip().strip('"')
            if not item or item.startswith("/"):
                continue
            if len(item) > 1 and item[1] == ":":      # 形如 D:\dir
                dirs.append(item)
        seen, clean = set(), []
        for d in dirs:
            key = d.lower().rstrip("\\")
            if key and key not in seen:
                seen.add(key)
                clean.append(d)
        env["PATH"] = os.pathsep.join(clean)

        tmp = self.cfg.getv("paths.tmp", None)
        if tmp:
            try:
                os.makedirs(tmp, exist_ok=True)
            except OSError:
                pass
            env["TMP"] = env["TEMP"] = env["TMPDIR"] = tmp
        return env


# ------------------------------------------------------------------ IO 小工具
def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text if text is not None else "")


def read_text(path, limit=None):
    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            return f.read() if limit is None else f.read(limit)
    except OSError:
        return ""


def truncate(text, max_bytes):
    return text.encode("utf-8", "replace")[:max_bytes].decode("utf-8", "replace")
