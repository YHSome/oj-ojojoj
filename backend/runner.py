# -*- coding: utf-8 -*-
"""沙箱执行器：在 Windows / POSIX 上安全地跑选手程序。

设计要点
--------
* stdout/stderr 直接重定向到**文件**，不用管道 —— 彻底避免父进程不读管道导致选手程序阻塞。
* 墙钟超时：软限 = time_limit，硬限 = time_limit*2 + grace，超时杀整棵进程树。
* Windows：用 Job Object 施加
      JOB_OBJECT_LIMIT_PROCESS_MEMORY   （内存上限）
      JOB_OBJECT_LIMIT_ACTIVE_PROCESS=1 （抑制 fork 炸弹）
      JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE（父进程消失时清理孤儿）
  峰值内存取 PeakJobMemoryUsed；Job Object 不可用时退化为 20ms 采样 WorkingSet。
* POSIX：resource.setrlimit(RLIMIT_AS / RLIMIT_CPU) + 进程组 kill。
* 所有平台都有：输出大小上限检查（OLE 判定依据）。

返回 RunResult(status, exit_code, time_ms, memory_kb, stdout_size, stderr_head, killed_by)
status ∈ {ok, tle, mle, re, ole, internal}
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

IS_WIN = os.name == "nt"

OK, TLE, MLE, RE, OLE, INTERNAL = "ok", "tle", "mle", "re", "ole", "internal"


class RunResult(object):
    __slots__ = ("status", "exit_code", "time_ms", "memory_kb",
                 "stdout_size", "stderr_head", "killed_by", "detail", "pid")

    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s))

    def as_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}

    def __repr__(self):
        return ("RunResult(status=%s, exit=%s, time=%sms, mem=%skb, out=%sB)"
                % (self.status, self.exit_code, self.time_ms, self.memory_kb, self.stdout_size))


# =========================================================== Windows Job Object
if IS_WIN:
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    JOB_OBJECT_BASIC_LIMIT_INFORMATION = 2
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001
    PROCESS_QUERY_INFORMATION = 0x0400
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    CREATE_NO_WINDOW = 0x08000000

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong)]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t)]

    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _k32.SetInformationJobObject.restype = wintypes.BOOL
    _k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                             wintypes.LPVOID, wintypes.DWORD]
    _k32.QueryInformationJobObject.restype = wintypes.BOOL
    _k32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                               wintypes.LPVOID, wintypes.DWORD,
                                               ctypes.POINTER(wintypes.DWORD)]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.AssignProcessToJobObject.restype = wintypes.BOOL
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.TerminateJobObject.restype = wintypes.BOOL
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.CloseHandle.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]

    try:
        _psapi = ctypes.WinDLL("psapi", use_last_error=True)
        _psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,
                                                ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                                                wintypes.DWORD]
    except OSError:
        _psapi = None
else:
    _k32 = None
    _psapi = None


class JobGuard(object):
    """把子进程放进 Job Object 以施加内存/进程数限制；失败时静默降级。"""

    def __init__(self, memory_limit_kb=None, active_process_limit=1, kill_on_close=True):
        self.handle = None
        self.ok = False
        self.reason = ""
        if not IS_WIN:
            self.reason = "not windows"
            return
        try:
            self.handle = _k32.CreateJobObjectW(None, None)
            if not self.handle:
                raise OSError("CreateJobObject failed")
            flags = 0
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            if memory_limit_kb:
                info.ProcessMemoryLimit = int(memory_limit_kb) * 1024
                flags |= JOB_OBJECT_LIMIT_PROCESS_MEMORY
            if active_process_limit:
                info.BasicLimitInformation.ActiveProcessLimit = int(active_process_limit)
                flags |= JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            if kill_on_close:
                flags |= JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            info.BasicLimitInformation.LimitFlags = flags
            if not _k32.SetInformationJobObject(
                    self.handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                    ctypes.byref(info), ctypes.sizeof(info)):
                raise OSError("SetInformationJobObject failed (err=%d)" % ctypes.get_last_error())
            self.ok = True
        except Exception as e:  # noqa: BLE001
            self.reason = str(e)
            self.close()

    def attach(self, pid):
        if not self.ok:
            return False
        try:
            h = _k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE | PROCESS_QUERY_INFORMATION,
                                 False, int(pid))
            if not h:
                return False
            try:
                return bool(_k32.AssignProcessToJobObject(self.handle, h))
            finally:
                _k32.CloseHandle(h)
        except Exception:  # noqa: BLE001
            return False

    def peak_memory_kb(self):
        if not self.ok:
            return 0
        try:
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            ret = wintypes.DWORD(0)
            if _k32.QueryInformationJobObject(self.handle,
                                              JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                              ctypes.byref(info), ctypes.sizeof(info),
                                              ctypes.byref(ret)):
                return int(info.PeakJobMemoryUsed // 1024)
        except Exception:  # noqa: BLE001
            pass
        return 0

    def kill_all(self):
        if self.ok and self.handle:
            try:
                _k32.TerminateJobObject(self.handle, 1)
            except Exception:  # noqa: BLE001
                pass

    def close(self):
        if self.handle:
            try:
                _k32.CloseHandle(self.handle)
            except Exception:  # noqa: BLE001
                pass
            self.handle = None
        self.ok = False


def _proc_memory_kb(pid):
    """Windows 上取进程峰值 WorkingSet（psapi 不可用时返回 0）。"""
    if not IS_WIN or _psapi is None:
        return 0
    try:
        h = _k32.OpenProcess(0x0400 | 0x0010, False, int(pid))  # QUERY_INFORMATION|VM_READ
        if not h:
            return 0
        try:
            pmc = PROCESS_MEMORY_COUNTERS()
            pmc.cb = ctypes.sizeof(pmc)
            if _psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
                return int(pmc.PeakWorkingSetSize // 1024)
        finally:
            _k32.CloseHandle(h)
    except Exception:  # noqa: BLE001
        pass
    return 0


# ================================================================= 主执行入口
def run_process(cmd, cwd, stdin_path, stdout_path, stderr_path,
                time_limit_ms=1000, memory_limit_kb=None, output_limit_kb=None,
                env=None, kill_grace_ms=500, job_object=True,
                active_process_limit=1, mem_sample_ms=20, env_replace=False):
    """执行 cmd，返回 RunResult。cmd 为 argv 列表。

    env_replace=True 表示 env 就是子进程的**完整**环境（判题时用，避免父进程的
    MSYS/开发环境变量（PATH 形如 /c/...、TMPDIR=/tmp）污染编译器，实测会导致
    gcc 无法 CreateProcess 自己的 cc1plus）。
    """
    cmd = [str(c) for c in cmd]
    t0 = time.time()
    if env is None:
        full_env = None
    elif env_replace:
        full_env = {str(k): str(v) for k, v in env.items()}
    else:
        full_env = dict(os.environ)
        full_env.update({k: str(v) for k, v in env.items()})

    creationflags = 0
    preexec = None
    if IS_WIN:
        creationflags = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    else:
        preexec = os.setsid

    guard = JobGuard(memory_limit_kb, active_process_limit,
                     True) if (IS_WIN and job_object) else None

    try:
        with open(stdin_path, "rb") as f_in, open(stdout_path, "wb") as f_out, \
                open(stderr_path, "wb") as f_err:
            try:
                proc = subprocess.Popen(cmd, cwd=cwd, stdin=f_in, stdout=f_out,
                                        stderr=f_err, env=full_env,
                                        creationflags=creationflags, preexec_fn=preexec,
                                        close_fds=(not IS_WIN))
            except (OSError, ValueError) as e:
                return RunResult(status=INTERNAL, exit_code=None, time_ms=0,
                                 memory_kb=0, stdout_size=0, stderr_head=str(e),
                                 killed_by="spawn", detail="无法启动: %s" % e, pid=None)

            pid = proc.pid
            attached = False
            if guard is not None:
                attached = guard.attach(pid)

            peak = {"kb": 0}
            flags = {"output_exceeded": False, "mem_exceeded": False}
            stop_sample = threading.Event()

            def sampler():
                """边跑边看的资源监控（对齐 MiniJudge 的文件监控思路）：

                * 峰值内存：Job Object 峰值优先，退化到 psapi 采样
                * 输出上限：一旦超出立刻杀进程树并标记 OLE（不必等程序自己结束）
                """
                limit_bytes = int(output_limit_kb) * 1024 if output_limit_kb else 0
                while not stop_sample.is_set():
                    if guard is not None and guard.ok:
                        m = guard.peak_memory_kb()
                    else:
                        m = _proc_memory_kb(pid)
                    if m > peak["kb"]:
                        peak["kb"] = m
                        if memory_limit_kb and m >= int(memory_limit_kb):
                            flags["mem_exceeded"] = True
                    if limit_bytes and _size(stdout_path) > limit_bytes:
                        flags["output_exceeded"] = True
                        _kill_tree(proc, guard)
                        return
                    stop_sample.wait(max(1, int(mem_sample_ms)) / 1000.0)

            th = threading.Thread(target=sampler, daemon=True)
            th.start()

            hard_ms = int(time_limit_ms) * 2 + kill_grace_ms
            hard_s = hard_ms / 1000.0
            killed_by = None
            try:
                rc = proc.wait(timeout=hard_s)
            except subprocess.TimeoutExpired:
                killed_by = "wall"
                _kill_tree(proc, guard)
                try:
                    rc = proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    rc = None
            elapsed_ms = int((time.time() - t0) * 1000)
            stop_sample.set()
            th.join(timeout=0.5)

            if guard is not None and guard.ok:
                peak["kb"] = max(peak["kb"], guard.peak_memory_kb())

            out_size = _size(stdout_path)
            err_head = _head(stderr_path, 2048)

            # 判定顺序（对齐 MiniJudge）：输出超限 > 内存超限 > 运行错误
            status = OK
            if flags["output_exceeded"] or (output_limit_kb and out_size > int(output_limit_kb) * 1024):
                status = OLE
            elif memory_limit_kb and peak["kb"] >= int(memory_limit_kb) * 0.995:
                status = MLE
            elif killed_by:
                status = TLE
            elif rc is not None and rc != 0:
                status = RE
            elif memory_limit_kb and peak["kb"] > int(memory_limit_kb):
                status = MLE

            detail = ""
            if status == MLE:
                detail = "内存 %d KB 达到限制 %d KB" % (peak["kb"], int(memory_limit_kb))
            elif status == OLE:
                detail = "输出 %s 字节超过限制 %d KB" % (out_size, int(output_limit_kb))
            elif status == TLE:
                detail = "运行超过时限 %d ms 被强制终止" % int(time_limit_ms)
            elif status == RE:
                detail = "运行错误（退出码 %s）" % rc

            return RunResult(status=status, exit_code=rc, time_ms=elapsed_ms,
                             memory_kb=int(peak["kb"]), stdout_size=out_size,
                             stderr_head=err_head, killed_by=killed_by,
                             detail=detail, pid=pid)
    except Exception as e:  # noqa: BLE001
        return RunResult(status=INTERNAL, exit_code=None,
                         time_ms=int((time.time() - t0) * 1000), memory_kb=0,
                         stdout_size=0, stderr_head="", killed_by="internal",
                         detail="执行器异常: %r" % e, pid=None)
    finally:
        if guard is not None:
            guard.kill_all()
            guard.close()


def _kill_tree(proc, guard=None):
    if IS_WIN:
        if guard is not None and guard.ok:
            guard.kill_all()
            return
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10, creationflags=CREATE_NO_WINDOW)
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:
                pass


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _head(path, n):
    try:
        with open(path, "rb") as f:
            return f.read(n).decode("utf-8", "replace")
    except OSError:
        return ""


# ================================================================= 编译辅助
def compile_program(cmd, cwd, timeout_ms=15000, log_max=8192, env=None, env_replace=False,
                    job_object=False):
    """编译：返回 (ok, log_text, elapsed_ms)。日志截断到 log_max。

    注意：编译**不要**套 Job Object 的 ActiveProcessLimit（默认 1）——gcc/cc1plus
    是父子进程结构，限制 1 会让 gcc 报
    "cannot execute 'cc1plus.exe': CreateProcess: No such file or directory"。
    """
    logfile = os.path.join(cwd, "__compile.log")
    res = run_process(cmd, cwd=cwd,
                      stdin_path=os.devnull,
                      stdout_path=logfile,
                      stderr_path=logfile + ".err",
                      time_limit_ms=max(1000, int(timeout_ms) // 2),
                      memory_limit_kb=None, output_limit_kb=log_max * 4 // 1024 + 64,
                      env=env, kill_grace_ms=1000, env_replace=env_replace,
                      job_object=job_object)
    chunks = []
    for p in (logfile, logfile + ".err"):
        try:
            with open(p, "rb") as f:
                chunks.append(f.read(log_max).decode("utf-8", "replace"))
        except OSError:
            pass
    log = ("\n".join(c for c in chunks if c)).strip()[:log_max]
    ok = (res.status == OK and res.exit_code == 0)
    if res.status == TLE or res.killed_by == "wall":
        ok = False
        log = ("[编译超时 >%dms]\n" % timeout_ms) + log
    return ok, log, res.time_ms


def which(name):
    """在 PATH + 附带工具链目录里找可执行文件。"""
    p = shutil.which(name)
    if p:
        return p
    for d in _extra_bin_dirs():
        for cand in (name, name + ".exe"):
            full = os.path.join(d, cand)
            if os.path.isfile(full):
                return full
    return None


_TOOLCHAIN_DIRS = None


def set_toolchain_dirs(dirs):
    global _TOOLCHAIN_DIRS
    _TOOLCHAIN_DIRS = [d for d in (dirs or []) if d]


def _extra_bin_dirs():
    global _TOOLCHAIN_DIRS
    if _TOOLCHAIN_DIRS is None:
        _TOOLCHAIN_DIRS = []
    return _TOOLCHAIN_DIRS


if __name__ == "__main__":
    d = tempfile.mkdtemp(prefix="ojrun_")
    with open(os.path.join(d, "in.txt"), "w") as f:
        f.write("hello\n")
    py = sys.executable
    r = run_process([py, "-c", "import sys;print(sys.stdin.read().strip().upper())"],
                    cwd=d, stdin_path=os.path.join(d, "in.txt"),
                    stdout_path=os.path.join(d, "out.txt"),
                    stderr_path=os.path.join(d, "err.txt"), time_limit_ms=5000)
    print(r, open(os.path.join(d, "out.txt")).read().strip())
    r2 = run_process([py, "-c", "while True: pass"], cwd=d,
                     stdin_path=os.devnull, stdout_path=os.path.join(d, "o2"),
                     stderr_path=os.path.join(d, "e2"), time_limit_ms=800)
    print("TLE test:", r2.status, r2.time_ms, "ms")
