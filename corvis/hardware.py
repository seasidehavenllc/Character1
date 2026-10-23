"""Looks at the device Corvis is running on and suggests which local model fits it."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass

# (minimum RAM in GB, Ollama model to suggest, why)
RECOMMENDATIONS = [
    (48, "qwen2.5-coder:32b", "large coding model — closest to cloud quality"),
    (24, "qwen2.5-coder:14b", "strong coding model"),
    (12, "qwen2.5-coder:7b", "good coding model for most laptops"),
    (6, "qwen2.5-coder:3b", "light coding model"),
    (0, "qwen2.5-coder:1.5b", "smallest model; best for phones and old PCs"),
]


@dataclass
class DeviceInfo:
    system: str
    machine: str
    cpu_cores: int
    ram_gb: float
    gpu: str
    recommended_model: str
    recommendation_reason: str

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        return f"{self.ram_gb:.0f} GB RAM · {self.cpu_cores} cores · {self.gpu}"


def total_ram_gb() -> float:
    try:
        import psutil  # optional, most accurate

        return psutil.virtual_memory().total / 1024**3
    except ImportError:
        pass
    if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    if platform.system() == "Windows":
        import ctypes

        class MemStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        stat = MemStatus()
        stat.dwLength = ctypes.sizeof(MemStatus)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return stat.ullTotalPhys / 1024**3
    return 0.0


def detect_gpu() -> str:
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return "Apple Silicon GPU"
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
            if out:
                return "NVIDIA " + out.splitlines()[0]
        except (OSError, subprocess.SubprocessError):
            pass
    if shutil.which("rocm-smi"):
        return "AMD GPU (ROCm)"
    return "CPU only"


def detect() -> DeviceInfo:
    ram = total_ram_gb()
    model, reason = next((m, r) for min_gb, m, r in RECOMMENDATIONS if ram >= min_gb)
    return DeviceInfo(platform.system(), platform.machine(), os.cpu_count() or 1,
                      round(ram, 1), detect_gpu(), model, reason)
