import sys
import os

# Try importing psutil; fall back to Windows API if not installed
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    import ctypes

from core.tools.registry import registry


def get_memory_stats():
    """Fetches system RAM usage stats."""
    if HAS_PSUTIL:
        mem = psutil.virtual_memory()
        return {
            "total_gb": round(mem.total / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "percent_used": mem.percent,
        }
    else:
        # Fallback for Windows without psutil installed
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))

        total_gb = round(stat.ullTotalPhys / (1024**3), 2)
        avail_gb = round(stat.ullAvailPhys / (1024**3), 2)
        used_gb = round(total_gb - avail_gb, 2)

        return {
            "total_gb": total_gb,
            "available_gb": avail_gb,
            "used_gb": used_gb,
            "percent_used": stat.dwMemoryLoad,
        }


def check_memory():
    """Tool function exposed to Vaelor runtime."""
    stats = get_memory_stats()
    return (
        f"RAM Usage: {stats['percent_used']}%\n"
        f"Used: {stats['used_gb']} GB / {stats['total_gb']} GB\n"
        f"Available: {stats['available_gb']} GB"
    )


# Register the tool function directly with all required positional arguments:
# register(name, description, read_only, func)
registry.register(
    "check_memory",
    "Returns current RAM usage, total memory, and available memory on the system.",
    True,
    check_memory
)


if __name__ == "__main__":
    print(check_memory())