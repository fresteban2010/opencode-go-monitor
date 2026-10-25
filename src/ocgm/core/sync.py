from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .client import ApiError
from .models import Usage
from .store import Store

BACKFILL_KEY = "backfill_cursor"


@dataclass
class SyncResult:
    usage: Usage | None
    new_requests: int = 0
    pages: int = 0
    errors: list[str] = field(default_factory=list)
    stale: bool = False
    logs_stale: bool = False
    logs_skipped: bool = False
    retryable: bool = False
    retry_after: float | None = None
    truncated: bool = False


@dataclass
class _Walk:
    new: int
    pages: int
    next_start: str | None
    done: bool
    error: ApiError | None = None


def _walk(
    store: Store,
    client: object,
    start: str | None,
    *,
    stop_when_cached: bool,
    page_size: int,
    max_pages: int,
) -> _Walk:
    cursor = start
    pages = 0
    new = 0
    while pages < max_pages:
        try:
            page = client.request_logs(cursor=cursor, limit=page_size)  # type: ignore[attr-defined]
        except ApiError as error:
            return _Walk(new, pages, cursor, False, error)

        added = store.upsert_requests(page.items)
        new += added
        pages += 1

        if not page.items or not page.next_cursor:
            return _Walk(new, pages, None, True)
        if stop_when_cached and added == 0:
            return _Walk(new, pages, None, True)
        cursor = page.next_cursor

    return _Walk(new, pages, cursor, False)


def _remember(store: Store, cursor: str | None) -> None:
    store.meta_set(BACKFILL_KEY, cursor or "")


def _resume_cursor(store: Store) -> str | None:
    value = store.meta_get(BACKFILL_KEY)
    return value or None


def synchronize(
    store: Store,
    client: object,
    full: bool = False,
    page_size: int = 100,
    max_pages: int = 40,
    include_logs: bool = True,
    now: datetime | None = None,
) -> SyncResult:
    usage: Usage | None = None
    errors: list[str] = []
    stale = False
    logs_stale = False
    retryable = False
    retry_after: float | None = None
    truncated = False

    try:
        usage = client.usage()  # type: ignore[attr-defined]
        store.record_usage(usage)
    except ApiError as error:
        errors.append(str(error))
        stale = True
        retryable = retryable or error.retryable
        retry_after = retry_after or error.retry_after
        usage = store.last_usage()

    total_new = 0
    total_pages = 0
    if include_logs:
        resume = None if full else _resume_cursor(store)
        if full:
            _remember(store, None)

        first = _walk(
            store,
            client,
            None,
            stop_when_cached=not full,
            page_size=page_size,
            max_pages=max_pages,
        )
        total_new += first.new
        total_pages += first.pages
        if first.error is not None:
            errors.append(str(first.error))
            logs_stale = True
            retryable = retryable or first.error.retryable
            retry_after = retry_after or first.error.retry_after
            if first.next_start:
                _remember(store, first.next_start)
        elif not first.done:
            truncated = True
            _remember(store, first.next_start)

        if not full and resume and first.error is None:
            second = _walk(
                store,
                client,
                resume,
                stop_when_cached=False,
                page_size=page_size,
                max_pages=max_pages,
            )
            total_new += second.new
            total_pages += second.pages
            if second.error is not None:
                errors.append(str(second.error))
                logs_stale = True
                retryable = retryable or second.error.retryable
                retry_after = retry_after or second.error.retry_after
                if second.next_start:
                    _remember(store, second.next_start)
            elif second.done:
                _remember(store, None)
            else:
                truncated = True
                _remember(store, second.next_start)

        if full and first.done:
            _remember(store, None)

    return SyncResult(
        usage=usage,
        new_requests=total_new,
        pages=total_pages,
        errors=errors,
        stale=stale,
        logs_stale=logs_stale,
        logs_skipped=not include_logs,
        retryable=retryable,
        retry_after=retry_after,
        truncated=truncated,
    )
