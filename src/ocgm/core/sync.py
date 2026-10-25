from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .client import ApiError
from .models import Usage
from .store import Store


@dataclass
class SyncResult:
    usage: Usage | None
    new_requests: int = 0
    pages: int = 0
    errors: list[str] = field(default_factory=list)
    stale: bool = False


def synchronize(
    store: Store,
    client: object,
    full: bool = False,
    page_size: int = 100,
    max_pages: int = 40,
    now: datetime | None = None,
) -> SyncResult:
    usage: Usage | None = None
    errors: list[str] = []
    stale = False

    try:
        usage = client.usage()  # type: ignore[attr-defined]
        store.record_usage(usage)
    except ApiError as error:
        errors.append(str(error))
        stale = True
        usage = store.last_usage()

    cursor: str | None = None
    pages = 0
    new_requests = 0
    while pages < max_pages:
        try:
            page = client.request_logs(cursor=cursor, limit=page_size)  # type: ignore[attr-defined]
        except ApiError as error:
            errors.append(str(error))
            break

        added = store.upsert_requests(page.items)
        new_requests += added
        pages += 1

        if not page.items or not page.next_cursor:
            break
        if not full and added == 0:
            break
        cursor = page.next_cursor

    return SyncResult(
        usage=usage,
        new_requests=new_requests,
        pages=pages,
        errors=errors,
        stale=stale,
    )
