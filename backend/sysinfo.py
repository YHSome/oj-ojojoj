# -*- coding: utf-8 -*-
"""轻量系统信息：CPU 利用率（多机共判时用来算"我还有多少余力"）。

  * Windows：GetSystemTimes 差分
  * Linux/macOS：os.getloadavg() 或 /proc/stat
不依赖 psutil。
"""
from __future__ import annotations

import os
import sys
import threading
import time

IS_WIN = os.name == "nt"
_k32 = None
if IS_WIN:
    try:
        import ctypes
        _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", ctypes.c_ulong),
                        ("dwHighDateTime", ctypes.c_ulong)]

        def _ft(v):
            return (v.dwHighDateTime << 32) | v.dwLowDateTime
    except Exception:  # noqa: BLE001
        _k32 = None


class CpuSampler(object):
    """采样 CPU 利用率（0.0~1.0）。调用 cost 很低，内部按间隔缓存。"""

    def __init__(self, cache_s=1.0):
        self.cache_s = float(cache_s)
        self._last = 0.0
        self._value = 0.0
        self._prev = None
        self._lock = threading.Lock()

    def _read(self):
        if _k32 is not None:
            idle, kern, user = FILETIME(), FILETIME(), FILETIME()
            if not _k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
                return None
            return _ft(idle), _ft(kern) + _ft(user)
        try:
            with open("/proc/stat", "r") as f:
                parts = [float(x) for x in f.readline().split()[1:]]
            idle = parts[3] + (parts[4] if len(parts) > 4 else 0.0)
            return idle, sum(parts)
        except OSError:
            try:
                la = os.getloadavg()[0]
                return None, la
            except OSError:
                return None

    def percent(self):
        now = time.time()
        with self._lock:
            if now - self._last < self.cache_s:
                return self._value
            cur = self._read()
            if cur is None:
                return self._value
            if self._prev is not None:
                if cur[0] is None:            # loadavg 形态
                    self._value = min(1.0, cur[1] / max(1, os.cpu_count() or 1))
                else:
                    di = cur[0] - self._prev[0]
                    dt = cur[1] - self._prev[1]
                    if dt > 0:
                        self._value = max(0.0, min(1.0, 1.0 - di / float(dt)))
            self._prev = cur
            self._last = now
            return self._value

    def load_pct(self):
        return int(round(self.percent() * 100))


if __name__ == "__main__":
    s = CpuSampler(cache_s=0.2)
    s.percent()          # 第一次只是建立基线
    time.sleep(0.3)
    for _ in range(3):
        print("cpu = %d%%" % s.load_pct())
        time.sleep(0.4)
    print("cores =", os.cpu_count(), "python =", sys.version.split()[0])
