"""Synthetic checks for response integrity, day boundaries, retries and resume."""

import io
import csv
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from vn30f1m_strategy_lab.data import fetch_dnse as dnse

DAY = date(2024, 1, 2)
STAMP = 1704160800  # 2024-01-02 09:00 +07:00


def payload(stamps=None):
    stamps = [STAMP] if stamps is None else stamps
    return {"t": stamps, "o": [100] * len(stamps), "h": [101] * len(stamps),
            "l": [99] * len(stamps), "c": [100.5] * len(stamps), "v": [12] * len(stamps)}


def encoded(value):
    return json.dumps(value).encode("utf-8")


def response(body):
    stream = io.BytesIO(body)
    stream.status = 200
    return stream


class ParseTests(unittest.TestCase):
    def test_vietnam_midnight_and_timezone_aware_csv(self):
        self.assertEqual(dnse.day_bounds(DAY), (1704128400, 1704214800))
        rows, report = dnse.parse_candles(encoded(payload()), DAY, "VN30F1M")
        self.assertEqual(rows[0]["timestamp_utc"], "2024-01-02T02:00:00+00:00")
        self.assertEqual(rows[0]["timestamp_vietnam"], "2024-01-02T09:00:00+07:00")
        self.assertEqual(rows[0]["close"], 100.5)
        self.assertEqual(report["rows"], 1)

    def test_next_midnight_is_excluded_and_long_gap_is_reported(self):
        body = encoded(payload([STAMP, STAMP + 120, 1704214800]))
        rows, report = dnse.parse_candles(body, DAY, "VN30F1M")
        self.assertEqual(len(rows), 2)
        self.assertEqual(report["excluded_outside_requested_day"], 1)
        self.assertEqual(report["gaps_gt_one_minute"], 1)
        self.assertEqual(report["max_gap_seconds"], 120)

    def test_rejects_malformed_arrays_nonfinite_values_and_bad_prices(self):
        cases = []
        unequal = payload()
        unequal["v"] = []
        cases.append(unequal)
        for field, value in (("h", 98), ("v", -1), ("c", float("nan")),
                             ("o", True), ("t", STAMP * 1000), ("t", STAMP + 1)):
            changed = payload()
            changed[field][0] = value
            cases.append(changed)
        for case in cases:
            with self.subTest(case=case), self.assertRaises(dnse.DataError):
                dnse.parse_candles(encoded(case), DAY, "VN30F1M")

    def test_rejects_duplicate_and_unordered_timestamps(self):
        for stamps in ([STAMP, STAMP], [STAMP + 60, STAMP]):
            with self.subTest(stamps=stamps), self.assertRaises(dnse.DataError):
                dnse.parse_candles(encoded(payload(stamps)), DAY, "VN30F1M")

    def test_empty_arrays_are_distinct_from_error_payloads(self):
        rows, report = dnse.parse_candles(encoded(payload([])), DAY, "VN30F1M")
        self.assertEqual(rows, [])
        self.assertEqual(report["rows"], 0)
        for body in (b'{"error":"denied"}', b'<html>error</html>'):
            with self.assertRaises(dnse.DataError):
                dnse.parse_candles(body, DAY, "VN30F1M")


class StorageTests(unittest.TestCase):
    def test_relocated_cache_uses_new_paths_without_downloading(self):
        body = encoded(payload())
        with tempfile.TemporaryDirectory() as directory:
            old_root = Path(directory) / "old_raw"
            new_root = Path(directory) / "new_raw"
            with patch.object(dnse, "request_bytes", return_value=(body, 200, 1)):
                first = dnse.fetch_day(DAY, "VN30F1M", old_root, delay=0)
            shutil.copytree(old_root, new_root)
            # The old location must not supply the export after relocation.
            (Path(first["snapshot_dir"]) / "response.json").write_bytes(b"old location changed")
            with patch.object(dnse, "request_bytes", side_effect=AssertionError("Unexpected download")):
                cached = dnse.fetch_day(DAY, "VN30F1M", new_root, delay=0)
            self.assertTrue(cached["cached"])
            self.assertTrue(Path(cached["snapshot_dir"]).is_relative_to(new_root))
            result = dnse.export_csv([cached], new_root, DAY, DAY, "VN30F1M")
            self.assertEqual(result["rows"], 1)
            self.assertEqual(result["status"], "complete")

    def test_raw_bytes_resume_tampering_and_refresh_preserve_snapshots(self):
        body = b'  ' + encoded(payload()) + b'\n'
        with tempfile.TemporaryDirectory() as directory, patch.object(dnse, "request_bytes", return_value=(body, 200, 1)) as get:
            root = Path(directory)
            first = dnse.fetch_day(DAY, "VN30F1M", root, delay=0)
            first_dir = Path(first["snapshot_dir"])
            self.assertEqual((first_dir / "response.json").read_bytes(), body)
            self.assertEqual(first["response_sha256"], dnse.sha256(body))
            self.assertEqual(first["listed_contract"], None)
            self.assertEqual(first["rows"], 1)
            self.assertTrue(dnse.fetch_day(DAY, "VN30F1M", root, delay=0)["cached"])
            self.assertEqual(get.call_count, 1)
            self.assertFalse((first_dir / "bars.csv").exists())
            (first_dir / "response.json").write_bytes(b"corrupt")
            replacement = dnse.fetch_day(DAY, "VN30F1M", root, delay=0)
            self.assertFalse(replacement["cached"])
            refreshed = dnse.fetch_day(DAY, "VN30F1M", root, refresh=True, delay=0)
            self.assertNotEqual(refreshed["snapshot_dir"], replacement["snapshot_dir"])
            self.assertEqual(get.call_count, 3)
            self.assertTrue(first_dir.exists())

    def test_first_collector_snapshots_can_be_reused_after_code_changes(self):
        body = encoded(payload())
        with tempfile.TemporaryDirectory() as directory, patch.object(dnse, "request_bytes", return_value=(body, 200, 1)) as get:
            root = Path(directory)
            first = dnse.fetch_day(DAY, "VN30F1M", root, delay=0)
            folder = Path(first["snapshot_dir"])
            legacy_csv = b"legacy daily CSV\n"
            (folder / "bars.csv").write_bytes(legacy_csv)
            legacy = {**first, "collector_sha256": "previous-source-version", "csv_sha256": dnse.sha256(legacy_csv)}
            (folder / "metadata.json").write_text(json.dumps(legacy), encoding="utf-8")
            self.assertTrue(dnse.fetch_day(DAY, "VN30F1M", root, delay=0)["cached"])
            self.assertEqual(get.call_count, 1)
            (folder / "bars.csv").write_bytes(b"corrupt")
            self.assertFalse(dnse.fetch_day(DAY, "VN30F1M", root, delay=0)["cached"])

    def test_invalid_ohlc_keeps_original_body_without_csv(self):
        changed = payload()
        changed["h"] = [98]
        body = encoded(changed)
        with tempfile.TemporaryDirectory() as directory, patch.object(dnse, "request_bytes", return_value=(body, 200, 1)):
            result = dnse.fetch_day(DAY, "VN30F1M", Path(directory), delay=0)
            folder = Path(result["snapshot_dir"])
            self.assertEqual(result["status"], "error")
            self.assertEqual((folder / "response.json").read_bytes(), body)
            self.assertFalse((folder / "bars.csv").exists())
            self.assertEqual(json.loads((folder / "metadata.json").read_text())["status"], "error")

    def test_outside_only_response_is_not_cached_as_empty(self):
        body = encoded(payload([1704214800]))
        with tempfile.TemporaryDirectory() as directory, patch.object(dnse, "request_bytes", return_value=(body, 200, 1)):
            result = dnse.fetch_day(DAY, "VN30F1M", Path(directory), delay=0)
            self.assertEqual(result["status"], "error")

    def test_http_error_body_is_saved_without_a_csv(self):
        body = b'<html>Forbidden</html>'
        with tempfile.TemporaryDirectory() as directory, patch.object(dnse, "request_bytes", return_value=(body, 403, 1)):
            result = dnse.fetch_day(DAY, "VN30F1M", Path(directory), delay=0)
            folder = Path(result["snapshot_dir"])
            self.assertEqual(result["http_status"], 403)
            self.assertEqual(result["status"], "error")
            self.assertEqual((folder / "response.json").read_bytes(), body)
            self.assertFalse((folder / "bars.csv").exists())

    def test_empty_response_is_recorded_and_transport_failure_is_not_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(dnse, "request_bytes", side_effect=dnse.DataError("offline")):
                failed = dnse.fetch_day(DAY, "VN30F1M", root, delay=0)
                self.assertEqual(failed["status"], "error")
            with patch.object(dnse, "request_bytes", return_value=(encoded(payload([])), 200, 1)) as get:
                empty = dnse.fetch_day(DAY, "VN30F1M", root, delay=0)
                self.assertEqual(empty["status"], "empty")
                self.assertTrue(dnse.fetch_day(DAY, "VN30F1M", root, delay=0)["cached"])
                self.assertEqual(get.call_count, 1)


class RequestTests(unittest.TestCase):
    @patch.object(dnse.time, "sleep")
    def test_rate_limit_retries_but_authentication_error_does_not(self, sleep):
        limited = HTTPError("https://example.invalid", 429, "limited", {"Retry-After": "2"}, io.BytesIO(b"limited"))
        with patch.object(dnse, "urlopen", side_effect=[limited, response(b"{}")]) as get:
            self.assertEqual(dnse.request_bytes("https://example.invalid", 3, 3), (b"{}", 200, 2))
            self.assertEqual(get.call_count, 2)
            sleep.assert_called_once_with(2)
        denied = HTTPError("https://example.invalid", 403, "denied", {}, io.BytesIO(b"denied"))
        with patch.object(dnse, "urlopen", side_effect=denied) as get:
            self.assertEqual(dnse.request_bytes("https://example.invalid", 3, 3), (b"denied", 403, 1))
            self.assertEqual(get.call_count, 1)

    @patch.object(dnse.time, "sleep")
    def test_transport_retry_is_bounded(self, sleep):
        with patch.object(dnse, "urlopen", side_effect=URLError("offline")) as get:
            with self.assertRaises(dnse.DataError):
                dnse.request_bytes("https://example.invalid", 3, 3)
            self.assertEqual(get.call_count, 3)
            self.assertEqual(sleep.call_count, 2)

    @patch.object(dnse.time, "sleep")
    def test_long_retry_after_does_not_trigger_an_early_retry(self, sleep):
        limited = HTTPError("https://example.invalid", 429, "limited", {"Retry-After": "120"}, io.BytesIO(b"limited"))
        with patch.object(dnse, "urlopen", side_effect=limited) as get:
            self.assertEqual(dnse.request_bytes("https://example.invalid", 3, 3), (b"limited", 429, 1))
            self.assertEqual(get.call_count, 1)
            sleep.assert_not_called()


class CliTests(unittest.TestCase):
    def test_default_output_is_data_raw_from_another_working_directory(self):
        expected = Path(__file__).resolve().parents[1] / "data" / "raw"
        result = {"status": "complete", "csv_file": "test.csv", "metadata_file": "test.json", "rows": 1}
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                with patch.object(dnse, "fetch_day", return_value={"status": "ok", "cached": True, "rows": 1}) as fetch, patch.object(dnse, "export_csv", return_value=result), redirect_stdout(io.StringIO()):
                    self.assertEqual(dnse.main(["--start", "2024-01-02", "--end", "2024-01-02"]), 0)
                self.assertEqual(fetch.call_args.args[2], expected)
            finally:
                os.chdir(original_cwd)

    def test_failed_day_does_not_hide_later_days_and_returns_failure(self):
        results = [{"status": "error", "cached": False, "error": "offline"},
                   {"status": "ok", "cached": False, "rows": 1}]
        export = {"status": "partial", "csv_file": "test.partial.csv", "metadata_file": "test.json", "rows": 1}
        with patch.object(dnse, "fetch_day", side_effect=results) as fetch, patch.object(dnse, "export_csv", return_value=export), redirect_stdout(io.StringIO()):
            self.assertEqual(dnse.main(["--start", "2024-01-02", "--end", "2024-01-03"]), 1)
            self.assertEqual(fetch.call_count, 2)

    def test_rejects_reversed_dates_and_current_day(self):
        today = dnse.datetime.now(dnse.VIETNAM_TZ).date().isoformat()
        for args in (["--start", "2024-01-03", "--end", "2024-01-02"],
                     ["--start", today, "--end", today]):
            with self.subTest(args=args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                dnse.main(args)
            self.assertEqual(error.exception.code, 2)


class ExportTests(unittest.TestCase):
    def test_cli_combines_days_in_time_order_and_rerun_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            args = ["--start", "2024-01-02", "--end", "2024-01-03", "--output-dir", directory, "--delay", "0"]
            bodies = [(encoded(payload()), 200, 1), (encoded(payload([STAMP + 86400])), 200, 1)]
            with patch.object(dnse, "request_bytes", side_effect=bodies) as get, redirect_stdout(io.StringIO()):
                self.assertEqual(dnse.main(args), 0)
                self.assertEqual(dnse.main(args), 0)
                self.assertEqual(get.call_count, 2)
            path = Path(directory) / "VN30F1M_1m.csv"
            with path.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2)
            self.assertEqual([row["timestamp_vietnam"] for row in rows],
                             ["2024-01-02T09:00:00+07:00", "2024-01-03T09:00:00+07:00"])
            meta = json.loads(path.with_suffix(".metadata.json").read_text())
            self.assertEqual(meta["rows"], 2)
            self.assertEqual(meta["csv_sha256"], dnse.sha256(path.read_bytes()))
            self.assertEqual(len(meta["sources"]), 2)
            self.assertEqual(len(list(Path(directory).rglob("*.csv"))), 1)

    def test_partial_export_preserves_previous_complete_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(dnse, "request_bytes", return_value=(encoded(payload()), 200, 1)):
                first = dnse.fetch_day(DAY, "VN30F1M", root, delay=0)
            complete = dnse.export_csv([first], root, DAY, DAY, "VN30F1M")
            original = Path(complete["csv_file"]).read_bytes()
            next_day = DAY + timedelta(days=1)
            with patch.object(dnse, "request_bytes", side_effect=dnse.DataError("offline")):
                failure = dnse.fetch_day(next_day, "VN30F1M", root, delay=0)
            partial = dnse.export_csv([first, failure], root, DAY, next_day, "VN30F1M")
            self.assertEqual(partial["status"], "partial")
            self.assertEqual(partial["failed_days"], 1)
            self.assertEqual(partial["rows"], 1)
            self.assertTrue(partial["csv_file"].endswith("VN30F1M_1m.partial.csv"))
            self.assertEqual(Path(complete["csv_file"]).read_bytes(), original)
            interrupted = dnse.export_csv([first], root, DAY, next_day, "VN30F1M", interrupted=True)
            self.assertTrue(interrupted["interrupted"])
            self.assertEqual(interrupted["status"], "partial")

    def test_changed_source_cannot_replace_previous_csv(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(dnse, "request_bytes", return_value=(encoded(payload()), 200, 1)):
            root = Path(directory)
            snapshot = dnse.fetch_day(DAY, "VN30F1M", root, delay=0)
            result = dnse.export_csv([snapshot], root, DAY, DAY, "VN30F1M")
            original = Path(result["csv_file"]).read_bytes()
            (Path(snapshot["snapshot_dir"]) / "response.json").write_bytes(b"changed")
            with self.assertRaises(dnse.DataError):
                dnse.export_csv([snapshot], root, DAY, DAY, "VN30F1M")
            self.assertEqual(Path(result["csv_file"]).read_bytes(), original)
            self.assertEqual(list(root.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
