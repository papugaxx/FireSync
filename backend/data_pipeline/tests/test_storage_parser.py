"""Storage and protocol contracts using small, new in-memory NASA-shaped samples.

No historical user CSV, network request, or external key is used by this suite.
"""

import csv
import io
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fires_data.errors import ProtocolError
from fires_data.parsing import parse_availability, parse_observations
from fires_data.store import Store
from fires_data.types import FetchPayload, Scope


DAY = date(2024, 7, 10)
FETCHED = datetime(2024, 7, 11, 10, 0, tzinfo=timezone.utc)
MODIS_HEADER = (
    "latitude", "longitude", "brightness", "scan", "track", "acq_date",
    "acq_time", "satellite", "confidence", "version", "bright_t31", "frp", "daynight",
)
VIIRS_HEADER = (
    "latitude", "longitude", "bright_ti4", "scan", "track", "acq_date",
    "acq_time", "satellite", "confidence", "version", "bright_ti5", "frp", "daynight",
)


def csv_bytes(header, records):
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=header)
    writer.writeheader()
    writer.writerows(records)
    return text.getvalue().encode("utf-8")


def modis_row(**changes):
    row = {
        "latitude": "45.12345", "longitude": "12.23456", "brightness": "321.2",
        "scan": "1.1", "track": "1.2", "acq_date": DAY.isoformat(),
        "acq_time": "3", "satellite": "T", "confidence": "86",
        "version": "6.1NRT", "bright_t31": "298.1", "frp": "12.5", "daynight": "N",
    }
    row.update(changes)
    return row


def viirs_row(**changes):
    row = {
        "latitude": "45.12345", "longitude": "12.23456", "bright_ti4": "329.4",
        "scan": "0.4", "track": "0.5", "acq_date": DAY.isoformat(),
        "acq_time": "1201", "satellite": "N20", "confidence": "nominal",
        "version": "2.0NRT", "bright_ti5": "299.7", "frp": "8.3", "daynight": "D",
    }
    row.update(changes)
    return row


def payload(scope, body, source="MODIS_NRT", start=DAY, end=DAY):
    return FetchPayload(
        body=body, source_code=source, scope_id=scope.id,
        start=start, end=end, fetched_at=FETCHED,
        url_redacted="https://firms.modaps.eosdis.nasa.gov/api/area/csv/<redacted>/...",
    )


class ParserContracts(unittest.TestCase):
    def setUp(self):
        self.scope = Scope("sample-area", "Sample area", 10, 40, 15, 50)

    def parse(self, body, source="MODIS_NRT"):
        return list(parse_observations(body, source, self.scope, DAY, DAY))

    def test_short_hhmm_becomes_timezone_aware_utc_and_raw_fields_survive(self):
        row = self.parse(csv_bytes(MODIS_HEADER, [modis_row()]))[0]
        self.assertEqual(row.observed_at, datetime(2024, 7, 10, 0, 3, tzinfo=timezone.utc))
        self.assertEqual(row.raw["acq_time"], "3")
        self.assertEqual(row.raw["scan"], "1.1")
        self.assertEqual(row.confidence_raw, "86")

    def test_one_modis_response_preserves_terra_and_aqua(self):
        body = csv_bytes(MODIS_HEADER, [modis_row(), modis_row(satellite="A", acq_time="1254")])
        rows = self.parse(body)
        self.assertEqual({row.satellite for row in rows}, {"Terra", "Aqua"})
        self.assertEqual({row.raw["satellite"] for row in rows}, {"T", "A"})

    def test_viirs_platform_and_word_confidence_work_without_instrument_column(self):
        row = self.parse(csv_bytes(VIIRS_HEADER, [viirs_row()]), "VIIRS_NOAA20_NRT")[0]
        self.assertEqual(row.sensor, "VIIRS")
        self.assertEqual(row.satellite, "NOAA-20")
        self.assertEqual(row.confidence_raw, "nominal")
        self.assertAlmostEqual(row.frp_mw, 8.3)

    def test_http_200_error_text_is_not_an_empty_observation_response(self):
        for body in (b"Invalid MAP_KEY", b"<html><body>Service unavailable</body></html>", b""):
            with self.subTest(body=body), self.assertRaises(ProtocolError):
                self.parse(body)

    def test_invalid_coordinates_and_invalid_clock_are_rejected(self):
        for changes in ({"latitude": "91"}, {"longitude": "181"},
                        {"latitude": "nan"}, {"acq_time": "2460"}):
            with self.subTest(changes=changes), self.assertRaises(ProtocolError):
                self.parse(csv_bytes(MODIS_HEADER, [modis_row(**changes)]))

    def test_valid_header_only_is_distinct_from_server_error(self):
        self.assertEqual(self.parse(csv_bytes(MODIS_HEADER, [])), [])

    def test_availability_reads_dates_and_skips_products_we_do_not_implement(self):
        body = (
            b"data_id,min_date,max_date\n"
            b"MODIS_SP,2000-11-01,2024-01-31\n"
            b"VIIRS_NOAA20_NRT,2024-02-01,2024-07-10\n"
            b"GOES_NRT,2022-08-09,2024-07-10\n"
        )
        result = parse_availability(body)
        self.assertEqual(set(result), {"MODIS_SP", "VIIRS_NOAA20_NRT"})
        self.assertEqual(result["MODIS_SP"].min_date, date(2000, 11, 1))
        self.assertEqual(result["VIIRS_NOAA20_NRT"].max_date, DAY)

    def test_availability_server_error_is_not_a_successful_empty_catalog(self):
        with self.assertRaises(ProtocolError):
            parse_availability(b"Invalid MAP_KEY")


class SnapshotStorageContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "observations.sqlite3")
        self.store.initialize()
        self.scope = Scope("sample-area", "Sample area", 10, 40, 15, 50)
        self.store.save_scope(self.scope)

    def save(self, body, source="MODIS_NRT", scope=None):
        scope = scope or self.scope
        fetched = payload(scope, body, source)
        return self.store.replace_batch(
            scope, fetched,
            parse_observations(body, source, scope, DAY, DAY),
        )

    def observations(self, scope=None):
        return self.store.observations((scope or self.scope).id, DAY, DAY)

    def test_repeating_a_snapshot_does_not_add_duplicate_observations(self):
        body = csv_bytes(MODIS_HEADER, [modis_row(), modis_row(satellite="A", acq_time="1254")])
        self.save(body)
        self.save(body)
        rows = self.observations()
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["satellite"] for row in rows}, {"Terra", "Aqua"})
        window = self.store.get_window(self.scope.id, "MODIS_NRT", DAY)
        self.assertEqual(window["status"], "loaded")
        self.assertEqual(window["row_count"], 2)

    def test_corrected_frp_replaces_the_previous_snapshot(self):
        self.save(csv_bytes(MODIS_HEADER, [modis_row(frp="12.5")]))
        self.save(csv_bytes(MODIS_HEADER, [modis_row(frp="22.75")]))
        rows = self.observations()
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["frp_mw"], 22.75)
        self.assertEqual(rows[0]["raw"]["frp"], "22.75")

    def test_valid_empty_snapshot_clears_old_rows_but_marks_slice_loaded(self):
        self.save(csv_bytes(MODIS_HEADER, [modis_row()]))
        self.save(csv_bytes(MODIS_HEADER, []))
        self.assertEqual(self.observations(), [])
        window = self.store.get_window(self.scope.id, "MODIS_NRT", DAY)
        self.assertEqual(window["status"], "loaded")
        self.assertEqual(window["row_count"], 0)
        self.assertEqual(self.store.daily_counts(self.scope.id, DAY, DAY), [])

    def test_bad_late_csv_row_keeps_the_previous_loaded_snapshot(self):
        old = csv_bytes(MODIS_HEADER, [modis_row(frp="12.5")])
        self.save(old)
        broken = csv_bytes(MODIS_HEADER, [modis_row(frp="22.75"), modis_row(latitude="91")])
        with self.assertRaises(ProtocolError):
            self.save(broken)
        rows = self.observations()
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["frp_mw"], 12.5)
        self.assertEqual(self.store.get_window(self.scope.id, "MODIS_NRT", DAY)["checksum"],
                         payload(self.scope, old).checksum)

    def test_mid_iterator_failure_rolls_back_deletion_and_partial_insert(self):
        old = csv_bytes(MODIS_HEADER, [modis_row(frp="12.5")])
        self.save(old)
        new = csv_bytes(MODIS_HEADER, [modis_row(frp="33.5")])

        def interrupted():
            yield from parse_observations(new, "MODIS_NRT", self.scope, DAY, DAY)
            raise RuntimeError("interrupted while consuming the response")

        with self.assertRaises(Exception):
            self.store.replace_batch(self.scope, payload(self.scope, new), interrupted())
        rows = self.observations()
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["frp_mw"], 12.5)
        self.assertEqual(self.store.get_window(self.scope.id, "MODIS_NRT", DAY)["checksum"],
                         payload(self.scope, old).checksum)

    def test_standard_processing_wins_only_for_its_family_and_day(self):
        self.save(csv_bytes(MODIS_HEADER, [modis_row(frp="12.5")]))
        self.save(csv_bytes(MODIS_HEADER, [modis_row(version="6.1", frp="15.25")]), "MODIS_SP")
        self.save(csv_bytes(VIIRS_HEADER, [viirs_row()]), "VIIRS_NOAA20_NRT")
        rows = self.observations()
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["source_code"] for row in rows}, {"MODIS_SP", "VIIRS_NOAA20_NRT"})
        modis = next(row for row in rows if row["sensor"] == "MODIS")
        self.assertAlmostEqual(modis["frp_mw"], 15.25)
        counts = self.store.daily_counts(self.scope.id, DAY, DAY)
        self.assertEqual(sum(item["count"] for item in counts), 2)

    def test_loaded_empty_standard_snapshot_does_not_fall_back_to_nrt_rows(self):
        self.save(csv_bytes(MODIS_HEADER, [modis_row()]))
        self.save(csv_bytes(MODIS_HEADER, []), "MODIS_SP")
        self.assertEqual(self.observations(), [])
        self.assertEqual(self.store.get_window(self.scope.id, "MODIS_SP", DAY)["row_count"], 0)

    def test_overlapping_scopes_are_isolated_and_scope_is_mandatory(self):
        other = Scope("other-area", "Overlapping area", 11, 41, 16, 51)
        self.store.save_scope(other)
        body = csv_bytes(MODIS_HEADER, [modis_row()])
        self.save(body)
        self.save(body, scope=other)
        self.assertEqual(len(self.observations()), 1)
        self.assertEqual(len(self.observations(other)), 1)
        self.assertEqual(self.observations()[0]["scope_id"], self.scope.id)
        self.assertEqual(self.observations(other)[0]["scope_id"], other.id)
        with self.assertRaises(ValueError):
            self.store.observations(None, DAY, DAY)


if __name__ == "__main__":
    unittest.main()
