from __future__ import annotations

import os


def rss_mb() -> float | None:
    """
    Best-effort resident set size (RSS) in MB.

    Uses stdlib-only approaches to keep deps minimal.
    - On Linux (Render), resource.ru_maxrss is typically in KB.
    - On macOS, resource.ru_maxrss is typically in bytes.
    """
    try:
        import resource  # type: ignore
    except Exception:
        resource = None  # type: ignore

    if resource is not None:
        try:
            raw = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            if raw <= 0:
                return None
            # Heuristic: if the value is huge, it's probably bytes (macOS); otherwise KB (Linux).
            mb = raw / (1024 * 1024) if raw > 10_000_000 else raw / 1024
            return round(mb, 2)
        except Exception:
            pass

    # Fallback: /proc (Linux only)
    try:
        if os.name == "posix" and os.path.exists("/proc/self/status"):
            with open("/proc/self/status", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            kb = float(parts[1])
                            return round(kb / 1024, 2)
    except Exception:
        return None

    return None

