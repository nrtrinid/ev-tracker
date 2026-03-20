from datetime import datetime, timezone
from typing import Iterable


def merge_scheduled_scan_times(
    base_times: Iterable[tuple[int, int]],
    temp_scan_time: tuple[int, int] | None,
) -> list[tuple[int, int]]:
    times = list(base_times)
    if temp_scan_time is not None and temp_scan_time not in times:
        times.append(temp_scan_time)
    return times


def scanned_at_from_oldest_fetch(oldest_fetched: float | None, fallback_iso: str) -> str:
    if oldest_fetched is None:
        return fallback_iso
    return datetime.fromtimestamp(oldest_fetched, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def scheduled_scan_rollup(scan_summary: dict) -> tuple[int, int, int, list[dict], int, int, str | None, float | None]:
    return (
        scan_summary["total_sides"],
        scan_summary["alerts_scheduled"],
        scan_summary["hard_errors"],
        scan_summary["all_sides"],
        scan_summary["total_events"],
        scan_summary["total_with_both"],
        scan_summary["min_remaining"],
        scan_summary["oldest_fetched"],
    )
