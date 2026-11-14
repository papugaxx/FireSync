from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
import math
import shutil
import time
from typing import Callable, Iterable, Mapping

from .errors import ConfigurationError, PipelineError, QuotaError
from .parsing import parse_observations
from .types import Availability, FetchTask, PRODUCTS, Scope, utc_now


def days_between(start, end):
    current = start
    while current <= end:
        yield current
        if current == date.max:
            break
        current += timedelta(days=1)


@dataclass
class SyncPlan:
    scope: Scope
    start: date
    end: date
    sources: list[str]
    tasks: list[FetchTask]
    skipped_units: int
    unavailable_days: dict[str, int]

    def summary(self):
        counts = Counter(task.source_code for task in self.tasks)
        return {
            "scope": self.scope.id,
            "bbox": list(self.scope.bbox),
            "date_from": self.start.isoformat(),
            "date_to": self.end.isoformat(),
            "pending_days": len(self.tasks),
            "cached_days": self.skipped_units,
            "pending_by_source": dict(counts),
            "unavailable_days": self.unavailable_days,
        }


def select_sources(sources):
    values = list(sources or ["auto"])
    if values == ["auto"]:
        return list(PRODUCTS), True
    if "auto" in values or any(value not in PRODUCTS for value in values):
        raise ConfigurationError("Use auto or supported source codes, without mixing auto and codes.")
    return list(dict.fromkeys(values)), False


def build_plan(store, scope, availability: Mapping[str, Availability], start: date, end: date,
               sources=None, force_refresh=False, refresh_recent_days=3):
    if end < start:
        raise ConfigurationError("End date precedes start date.")
    if end > utc_now().date():
        raise ConfigurationError("Future dates cannot be loaded as observations.")
    if not 0 <= refresh_recent_days <= 31:
        raise ConfigurationError("Recent refresh interval must be between 0 and 31 days.")
    selected, automatic = select_sources(sources)
    groups = {}
    for code in selected:
        group = PRODUCTS[code].family if automatic else code
        groups.setdefault(group, []).append(code)
    tasks = []
    skipped = 0
    unavailable = {}
    requested_days = (end - start).days + 1
    fresh_boundary = utc_now().date() - timedelta(days=max(0, refresh_recent_days - 1))
    cached_windows = {
        (row["source_code"], row["day"]): row
        for row in store.list_windows(scope.id, start, end)
    }
    for group, codes in groups.items():
        metadata = [availability[code] for code in codes if code in availability]
        if not metadata:
            unavailable[group] = requested_days
            continue
        lower = max(start, min(row.min_date for row in metadata))
        upper = min(end, max(row.max_date for row in metadata))
        available_days = 0
        for day in days_between(lower, upper):
            candidates = [code for code in codes if code in availability
                          and availability[code].min_date <= day <= availability[code].max_date]
            if not candidates:
                continue
            available_days += 1
            # In auto mode SP and NRT are alternatives, not independent observations.
            chosen = max(candidates, key=lambda code: PRODUCTS[code].priority)
            window = cached_windows.get((chosen, day.isoformat()))
            recent_nrt = (refresh_recent_days > 0 and PRODUCTS[chosen].processing == "NRT"
                          and day >= fresh_boundary)
            if window and window.get("status") == "loaded" and not force_refresh and not recent_nrt:
                skipped += 1
            else:
                tasks.append(FetchTask(chosen, day))
        unavailable[group] = requested_days - available_days
    tasks.sort(key=lambda item: (item.source_code, item.day))
    return SyncPlan(scope, start, end, selected, tasks, skipped, unavailable)


def make_batches(tasks: Iterable[FetchTask], batch_days=1):
    if not 1 <= batch_days <= 5:
        raise ConfigurationError("API batch size must be between 1 and 5 days.")
    batch = []
    for task in tasks:
        contiguous = (batch and task.source_code == batch[-1].source_code
                      and task.day - batch[-1].day == timedelta(days=1))
        if batch and (not contiguous or len(batch) >= batch_days):
            yield batch
            batch = []
        batch.append(task)
    if batch:
        yield batch


class SyncService:
    def __init__(self, client, store):
        self.client, self.store = client, store

    def refresh_availability(self):
        metadata = self.client.availability()
        self.store.save_availability(metadata)
        return metadata

    def run(self, plan: SyncPlan, batch_days=1, max_requests=20, min_interval=1.0,
            quota_reserve=100, check_quota=True, min_free_gb=30,
            progress: Callable[[dict], None] | None = None):
        if max_requests < 0 or not 0 <= min_interval <= 30 or quota_reserve < 0:
            raise ConfigurationError("Invalid request budget, interval or quota reserve.")
        if not isinstance(min_free_gb, (int, float)) or not math.isfinite(min_free_gb) or min_free_gb < 0:
            raise ConfigurationError("Disk reserve must be a finite non-negative GiB value.")
        reserve_bytes = int(min_free_gb * 1024**3)
        batches = make_batches(plan.tasks, batch_days)
        job_id = self.store.create_job(plan.scope.id, plan.sources, plan.start, plan.end,
                                       len(plan.tasks) + plan.skipped_units)
        self.store.update_job(job_id, status="running", skipped_units=plan.skipped_units)
        requests = 0
        completed = 0
        rows = 0
        failed = 0
        try:
            for batch in batches:
                if shutil.disk_usage(self.store.path.parent).free < reserve_bytes:
                    self.store.update_job(job_id, status="paused", error="Disk-space reserve reached; completed slices were preserved.")
                    break
                if max_requests and requests >= max_requests:
                    self.store.update_job(job_id, status="paused", error="Request budget reached; rerun the same command to continue.")
                    break
                if check_quota and requests % 5 == 0:
                    quota = self.client.quota_status()
                    limit = int(quota["transaction_limit"])
                    current = int(quota["current_transactions"])
                    if limit - current <= quota_reserve:
                        self.store.update_job(job_id, status="paused", error="NASA transaction reserve reached; retry after the quota window resets.")
                        break
                if requests and min_interval:
                    time.sleep(min_interval)
                first, last = batch[0], batch[-1]
                try:
                    requests += 1
                    payload = self.client.fetch_area(plan.scope, first.source_code, first.day, last.day)
                    # Validate the full response before asking storage to replace a slice.
                    validated_rows = sum(1 for _ in parse_observations(
                        payload.body, first.source_code, plan.scope, first.day, last.day))
                    old_rows = sum(row["row_count"] for row in self.store.list_windows(
                        plan.scope.id, first.day, last.day) if row["source_code"] == first.source_code)
                    # Conservative room for records, indexes and the temporary WAL.
                    estimated_peak = max(old_rows, validated_rows) * 3072 + 1024**2
                    if shutil.disk_usage(self.store.path.parent).free < reserve_bytes + estimated_peak:
                        self.store.update_job(job_id, status="paused", error="Not enough disk space for the next batch and its reserve; previous data was preserved.")
                        break
                    result = self.store.replace_batch(
                        plan.scope, payload,
                        parse_observations(payload.body, first.source_code, plan.scope, first.day, last.day),
                    )
                except PipelineError as exc:
                    self.store.record_failure(plan.scope.id, first.source_code, first.day, last.day, str(exc))
                    failed += len(batch)
                    self.store.update_job(job_id, status="paused" if isinstance(exc, QuotaError) else "failed",
                                          completed_units=completed, failed_units=failed, error=str(exc))
                    break
                completed += len(batch)
                rows += result["rows"]
                self.store.update_job(job_id, completed_units=completed)
                if progress:
                    progress({"job_id": job_id, "source": first.source_code,
                              "from": first.day.isoformat(), "to": last.day.isoformat(),
                              "rows": result["rows"], "completed_days": completed,
                              "pending_days": len(plan.tasks) - completed})
                if completed < len(plan.tasks) and shutil.disk_usage(self.store.path.parent).free < reserve_bytes:
                    self.store.update_job(job_id, status="paused", error="Disk-space reserve reached; completed slices were preserved.")
                    break
            else:
                self.store.update_job(job_id, status="completed", error=None)
        except KeyboardInterrupt:
            self.store.update_job(job_id, status="paused", completed_units=completed,
                                  error="Interrupted; rerun the same command to continue.")
            raise
        except Exception:
            # Do not echo third-party exceptions that could include an authenticated URL.
            self.store.update_job(job_id, status="failed", completed_units=completed,
                                  error="Unexpected failure; completed daily checkpoints were preserved.")
            raise PipelineError("Sync stopped unexpectedly; inspect job status and retry.") from None
        job = self.store.get_job(job_id)
        return {"job": job, "requests": requests, "written_rows": rows,
                "unavailable_days": plan.unavailable_days}
