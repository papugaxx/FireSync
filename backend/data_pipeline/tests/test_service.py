from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fires_data.errors import ProtocolError
from fires_data.service import SyncService, build_plan, make_batches
from fires_data.store import Store
from fires_data.types import Availability, FetchPayload, FetchTask, PRODUCTS, Scope, utc_now


DAY = date(2024, 7, 10)


def response_body(source, start, end, frp=10):
    product = PRODUCTS[source]
    satellite = "T" if product.sensor == "MODIS" else "N20"
    version = "6.1" if product.sensor == "MODIS" else "2.0"
    if product.processing == "NRT":
        version += "NRT"
    confidence = "80" if product.sensor == "MODIS" else "nominal"
    header = "latitude,longitude,acq_date,acq_time,satellite,confidence,version,frp,daynight\n"
    rows = []
    current = start
    while current <= end:
        rows.append(f"45,12,{current.isoformat()},3,{satellite},{confidence},{version},{frp},N\n")
        current += timedelta(days=1)
    return (header + "".join(rows)).encode()


class FakeClient:
    def __init__(self, metadata, fail=False, remaining=5000):
        self.metadata, self.fail, self.remaining = metadata, fail, remaining
        self.calls = []

    def availability(self):
        return self.metadata

    def quota_status(self):
        return {"transaction_limit": 5000, "current_transactions": 5000 - self.remaining,
                "transaction_interval": "10 minutes"}

    def fetch_area(self, scope, source_code, start, end):
        self.calls.append((source_code, start, end))
        if self.fail:
            raise ProtocolError("Invalid response fixture.")
        return FetchPayload(response_body(source_code, start, end), source_code, scope.id,
                            start, end, utc_now(), "https://firms.modaps.eosdis.nasa.gov/api/area/csv/<MAP_KEY>/...")


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "fires.sqlite3")
        self.store.initialize()
        self.scope = Scope("test", "Test area", 10, 40, 15, 50)
        self.store.save_scope(self.scope)

    def metadata(self, *sources, days=1):
        return {source: Availability(source, DAY, DAY + timedelta(days=days-1)) for source in sources}

    def test_auto_prefers_sp_with_nrt_fallback_and_unavailable_days(self):
        metadata = {
            "MODIS_SP": Availability("MODIS_SP", DAY, DAY),
            "MODIS_NRT": Availability("MODIS_NRT", DAY, DAY + timedelta(days=1)),
        }
        plan = build_plan(self.store, self.scope, metadata, DAY-timedelta(days=1), DAY+timedelta(days=2))
        self.assertEqual([(task.source_code, task.day) for task in plan.tasks],
                         [("MODIS_NRT", DAY+timedelta(days=1)), ("MODIS_SP", DAY)])
        self.assertEqual(plan.unavailable_days["MODIS"], 2)

    def test_request_budget_checkpoints_and_rerun_continues(self):
        metadata = self.metadata("MODIS_SP", "VIIRS_NOAA20_SP")
        client = FakeClient(metadata)
        service = SyncService(client, self.store)
        plan = build_plan(self.store, self.scope, metadata, DAY, DAY)
        first = service.run(plan, max_requests=1, min_interval=0)
        self.assertEqual(first["job"]["status"], "paused")
        self.assertEqual(len(self.store.observations(self.scope.id, DAY, DAY)), 1)
        resumed = build_plan(self.store, self.scope, metadata, DAY, DAY)
        self.assertEqual(resumed.skipped_units, 1)
        self.assertEqual(len(resumed.tasks), 1)
        second = service.run(resumed, max_requests=1, min_interval=0)
        self.assertEqual(second["job"]["status"], "completed")
        self.assertEqual(len(self.store.observations(self.scope.id, DAY, DAY)), 2)

    def test_bad_refresh_preserves_previous_snapshot(self):
        metadata = self.metadata("MODIS_SP")
        service = SyncService(FakeClient(metadata), self.store)
        service.run(build_plan(self.store, self.scope, metadata, DAY, DAY), min_interval=0)
        before = self.store.observations(self.scope.id, DAY, DAY)
        service.client.fail = True
        result = service.run(build_plan(self.store, self.scope, metadata, DAY, DAY, force_refresh=True), min_interval=0)
        self.assertEqual(result["job"]["status"], "failed")
        self.assertEqual(self.store.observations(self.scope.id, DAY, DAY), before)
        self.assertEqual(self.store.get_window(self.scope.id, "MODIS_SP", DAY)["status"], "loaded")

    def test_low_quota_pauses_before_area_request(self):
        metadata = self.metadata("MODIS_SP")
        client = FakeClient(metadata, remaining=50)
        result = SyncService(client, self.store).run(
            build_plan(self.store, self.scope, metadata, DAY, DAY), min_interval=0)
        self.assertEqual(result["job"]["status"], "paused")
        self.assertEqual(client.calls, [])

    def test_disk_reserve_pauses_before_request_and_preserves_database(self):
        metadata = self.metadata("MODIS_SP")
        client = FakeClient(metadata)
        service = SyncService(client, self.store)
        plan = build_plan(self.store, self.scope, metadata, DAY, DAY)
        with patch("fires_data.service.shutil.disk_usage", return_value=SimpleNamespace(free=1024)):
            result = service.run(plan, min_interval=0, min_free_gb=1)
        self.assertEqual(result["job"]["status"], "paused")
        self.assertEqual(client.calls, [])
        self.assertEqual(self.store.observations(self.scope.id, DAY, DAY), [])

    def test_five_day_batch_stores_individual_day_checkpoints(self):
        metadata = self.metadata("MODIS_SP", days=6)
        client = FakeClient(metadata)
        plan = build_plan(self.store, self.scope, metadata, DAY, DAY+timedelta(days=5), ["MODIS_SP"])
        result = SyncService(client, self.store).run(plan, batch_days=5, min_interval=0)
        self.assertEqual(result["job"]["status"], "completed")
        self.assertEqual(len(client.calls), 2)
        for offset in range(6):
            self.assertEqual(self.store.get_window(self.scope.id, "MODIS_SP", DAY+timedelta(days=offset))["status"], "loaded")


if __name__ == "__main__":
    unittest.main()
