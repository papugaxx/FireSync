import contextlib
from datetime import date
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fires_data.cli import build_parser, get_range, main
from fires_data.config import load_settings
from fires_data.errors import ConfigurationError
from fires_data.store import Store
from fires_data.types import Scope
from fires_data.types import Availability, utc_now


class CliConfigTests(unittest.TestCase):
    def test_calibration_without_data_returns_insufficient_without_nasa(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"FIRMS_MAP_KEY": "", "FIRMS_DB_PATH": ""}):
            path = Path(folder) / "test.sqlite3"
            store = Store(path)
            store.initialize()
            store.save_scope(Scope.world())
            output = io.StringIO()
            with contextlib.redirect_stdout(output), patch("fires_data.cli.FirmsClient") as nasa:
                code = main(["--db", str(path), "--env-file", str(Path(folder)/"absent"),
                             "calibrate", "--scope", "world", "--from", "2024-08-01",
                             "--to", "2024-08-31", "--split", "2024-08-22"])
            self.assertEqual(code, 0)
            nasa.assert_not_called()
            result = json.loads(output.getvalue())
            self.assertEqual(result["status"], "insufficient_data")
            self.assertIsNone(result["coefficient"])

    def test_calendar_reads_local_database_without_nasa_or_key(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"FIRMS_MAP_KEY": "", "FIRMS_DB_PATH": ""}):
            path = Path(folder) / "test.sqlite3"
            store = Store(path)
            store.initialize()
            store.save_scope(Scope.world())
            output = io.StringIO()
            with contextlib.redirect_stdout(output), patch("fires_data.cli.FirmsClient") as nasa:
                code = main(["--db", str(path), "--env-file", str(Path(folder)/"absent"),
                             "calendar", "--scope", "world", "--from", "2024-08-01", "--to", "2024-08-02"])
            self.assertEqual(code, 0)
            nasa.assert_not_called()
            report = json.loads(output.getvalue())
            self.assertEqual(len(report["daily"]), 2)
            self.assertEqual(report["daily"][0]["modis"]["status"], "missing")
            self.assertIsNone(report["daily"][0]["modis"]["active_cells"])

    def test_init_and_keyless_doctor_do_not_contact_nasa(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"FIRMS_MAP_KEY": "", "FIRMS_DB_PATH": ""}):
            path = Path(folder) / "test.sqlite3"
            arguments = ["--db", str(path), "--env-file", str(Path(folder)/"absent")]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main([*arguments, "init"]), 0)
            self.assertTrue(path.is_file())
            self.assertEqual(json.loads(output.getvalue())["stored_rows"], 0)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main([*arguments, "doctor"]), 0)
            self.assertFalse(json.loads(output.getvalue())["map_key_configured"])
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                self.assertEqual(main([*arguments, "availability"]), 1)
            self.assertIn("FIRMS_MAP_KEY", error.getvalue())

    def test_configuration_uses_its_own_directory_and_hides_the_key(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"FIRMS_MAP_KEY": "", "FIRMS_DB_PATH": ""}):
            env = Path(folder) / ".env"
            env.write_text('FIRMS_MAP_KEY=test-only-secret\nFIRMS_DB_PATH=var/fires.sqlite3\n')
            # Only explicit environment entries should override the file.
            with patch.dict(os.environ, {}, clear=True):
                settings = load_settings(env)
            self.assertEqual(settings.db_path, (Path(folder)/"var"/"fires.sqlite3").resolve())
            self.assertEqual(settings.api_key, "test-only-secret")
            self.assertNotIn("test-only-secret", repr(settings))

    def test_live_refresh_can_include_today_without_hardcoded_dates(self):
        args = build_parser().parse_args(["sync", "--recent-days", "3", "--include-today"])
        metadata = {"MODIS_NRT": Availability("MODIS_NRT", date(2020,1,1), utc_now().date())}
        start, end = get_range(args, metadata)
        self.assertEqual(end, utc_now().date())
        self.assertEqual((end-start).days, 2)

    def test_include_today_cannot_silently_change_an_all_history_request(self):
        args = build_parser().parse_args(["plan", "--all-history", "--include-today"])
        with self.assertRaises(ConfigurationError):
            get_range(args, {})


if __name__ == "__main__":
    unittest.main()
