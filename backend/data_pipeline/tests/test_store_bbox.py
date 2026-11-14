"""Geographic read filtering over one cached world scope; no external data."""

import csv
from datetime import date, datetime, timezone
import io
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fires_data.parsing import parse_observations
from fires_data.store import Store
from fires_data.types import FetchPayload, Scope


DAY = date(2024, 7, 10)


def csv_body(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


class BoundingBoxReads(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(Path(self.directory.name) / "world.sqlite3")
        self.store.initialize()
        self.scope = Scope.world()
        self.store.save_scope(self.scope)
        base = {"latitude": "45.5", "longitude": "12.5", "brightness": "321.2",
                "scan": "1.0", "track": "1.0", "acq_date": DAY.isoformat(),
                "acq_time": "0030", "satellite": "T", "confidence": "86",
                "version": "6.1NRT", "frp": "12.5", "daynight": "N"}
        body = csv_body([base, {**base, "latitude": "46.5", "longitude": "13.5", "satellite": "A"}])
        payload = FetchPayload(body, "MODIS_NRT", "world", DAY, DAY,
                               datetime(2024, 7, 11, tzinfo=timezone.utc), "redacted")
        self.store.replace_batch(self.scope, payload,
                                 parse_observations(body, "MODIS_NRT", self.scope, DAY, DAY))

    def test_observations_filter_world_cache_by_bbox(self):
        all_rows = self.store.observations("world", DAY, DAY)
        inside = self.store.observations("world", DAY, DAY, bbox=(12, 45, 13, 46))
        self.assertEqual(len(all_rows), 2)
        self.assertEqual(len(inside), 1)
        self.assertEqual(inside[0]["satellite"], "Terra")
        self.assertEqual(inside[0]["id"], next(row["id"] for row in all_rows if row["satellite"] == "Terra"))
        self.assertEqual(self.store.observations("world", DAY, DAY, bbox=(20, 20, 21, 21)), [])

    def test_daily_counts_filter_the_same_bbox(self):
        self.assertEqual(sum(row["count"] for row in self.store.daily_counts("world", DAY, DAY)), 2)
        counts = self.store.daily_counts("world", DAY, DAY, bbox=(12, 45, 13, 46))
        self.assertEqual(counts, [{"day": DAY.isoformat(), "sensor": "MODIS", "satellite": "Terra", "count": 1}])
        self.assertEqual(self.store.daily_counts("world", DAY, DAY, bbox=(20, 20, 21, 21)), [])

    def test_invalid_bbox_is_rejected_for_both_reads(self):
        for bbox in ((13, 45, 12, 46), (12, 46, 13, 45), (-181, 0, 0, 1),
                     (12, 45, 13), (12, 45, float("nan"), 46)):
            for read in (self.store.observations, self.store.daily_counts):
                with self.subTest(bbox=bbox, read=read.__name__), self.assertRaises(ValueError):
                    read("world", DAY, DAY, bbox=bbox)


if __name__ == "__main__":
    unittest.main()
