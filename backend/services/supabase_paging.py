from __future__ import annotations

from typing import Any, Callable

DEFAULT_PAGE_SIZE = 1000
DEFAULT_MAX_ROWS = 50000


def fetch_all_rows(
    *,
    query_factory: Callable[[int, int], Any],
    page_size: int = DEFAULT_PAGE_SIZE,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> list[dict[str, Any]]:
    """Fetch a complete result set from Supabase/PostgREST using ranged pages."""

    rows: list[dict[str, Any]] = []
    offset = 0

    while len(rows) < max_rows:
        query = query_factory(offset, page_size)
        response = query.execute()
        batch = list(response.data or [])
        if not batch:
            break

        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    if len(rows) > max_rows:
        return rows[:max_rows]
    return rows
