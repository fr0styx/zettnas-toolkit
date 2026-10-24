"""Shared paging for list endpoints (ARCH-11).

    @router.get("/things")
    def list_things(page: PageParams = Depends()):
        rows = load(limit=page.fetch)          # enough rows for this page
        items = page.slice(rows)
        return {"things": items, **page.meta(len(rows))}

limit is 1-500 (default 50) and offset 0 or more, validated by FastAPI; responses keep their
existing keys and gain limit, offset and next_offset.
"""

from typing import Any, TypeVar

from fastapi import Query

DEFAULT_LIMIT = 50
MAX_LIMIT = 500
MAX_OFFSET = 1_000_000
T = TypeVar("T")


class PageParams:
    def __init__(
        self,
        limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Items per page"),
        offset: int = Query(0, ge=0, le=MAX_OFFSET, description="Items to skip"),
    ) -> None:
        self.limit = limit
        self.offset = offset

    @property
    def fetch(self) -> int:
        """Rows to load from a source that only knows "the newest N": this page plus one more,
        so we can tell whether another page follows."""
        return self.offset + self.limit + 1

    def slice(self, rows: list[T]) -> list[T]:
        return list(rows)[self.offset : self.offset + self.limit]

    def meta(self, loaded: int, total: int | None = None) -> dict[str, Any]:
        more = (total is not None and self.offset + self.limit < total) or (
            total is None and loaded > self.offset + self.limit
        )
        out: dict[str, Any] = {
            "limit": self.limit,
            "offset": self.offset,
            "next_offset": self.offset + self.limit if more else None,
        }
        if total is not None:
            out["total"] = total
        return out
