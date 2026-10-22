"""Independent small examples for minute gaps and holiday-aware periods."""

import csv
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
import io
from unittest.mock import patch
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from vn30f1m_strategy_lab.data import audit_dnse as audit


class AuditTests(unittest.TestCase):
    def test_cli_default_paths_follow_data_raw_from_another_directory(self):
        expected = Path(__file__).resolve().parents[1] / "data" / "raw"
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                with patch.object(sys, "argv", ["audit_dnse.py"]), patch.object(audit, "audit", return_value={}) as run, redirect_stdout(io.StringIO()):
                    audit.main()
                self.assertEqual(run.call_args.args[0], expected / "VN30F1M_1m.csv")
                self.assertEqual(run.call_args.args[1], expected / "quality_report")
            finally:
                os.chdir(original_cwd)

    def test_minute_runs_count_missing_labels_inclusively(self):
        self.assertEqual(audit.consecutive_runs([600, 601, 601, 603]), [[600, 601], [603]])
        self.assertEqual(len(audit.OPEN_GRID), 240)
        self.assertEqual(len(audit.CORE_GRID), 238)
        self.assertNotIn(690, audit.OPEN_GRID)  # 11:30 boundary
        self.assertNotIn(885, audit.OPEN_GRID)  # 14:45 closing auction
        self.assertNotIn(720, audit.OPEN_GRID)  # Lunch break

    def test_calendar_blocks_skip_only_supplied_holidays(self):
        days = [date(2023, 12, 29), date(2024, 1, 2)]
        self.assertEqual(len(audit.weekday_blocks(days)), 2)
        self.assertEqual(len(audit.weekday_blocks(days, {date(2024, 1, 1)})), 1)
        self.assertEqual(len(audit.weekday_blocks(days + [date(2024, 1, 4)], {date(2024, 1, 1)})), 2)

    def test_report_distinguishes_intraday_gaps_empty_days_and_holidays(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "sample.csv"
            fields = ["timestamp_utc", "timestamp_vietnam", "symbol", "open", "high", "low", "close", "volume"]
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for day in (date(2024, 1, 8), date(2024, 1, 11)):
                    for minute in sorted(audit.OPEN_GRID | {885}):
                        if day.day == 8 and minute == 605:
                            continue
                        local = datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=audit.LOCAL_TZ)
                        writer.writerow(dict(zip(fields, (local.astimezone(timezone.utc).isoformat(), local.isoformat(),
                                                          "VN30F1M", 100, 101, 99, 100, 0))))
            path.with_suffix(".metadata.json").write_text(json.dumps({"requested_start": "2024-01-08", "requested_end": "2024-01-11"}), encoding="utf-8")
            calendar = root / "calendar.json"
            calendar.write_text(json.dumps({"coverage_start": "2024-01-08", "coverage_end": "2024-01-11",
                                            "holidays_by_year": {"2024": ["2024-01-09"]}}), encoding="utf-8")
            before = path.read_bytes()
            result = audit.audit(path, root / "report", calendar)
            self.assertEqual(result["missing_minutes_observed_days_open_grid"], 1)
            self.assertEqual(result["missing_minutes_observed_days_core_grid"], 1)
            self.assertEqual(result["scheduled_holidays_without_rows"], 1)
            self.assertEqual(result["scheduled_trading_days_without_rows"], 1)
            self.assertEqual(result["missing_open_labels_including_absent_scheduled_days"], 241)
            self.assertEqual(result["complete_observed_days_open_grid"], 1)
            self.assertEqual(result["issue_rows"], 0)
            self.assertEqual(result["missing_values_by_column"]["volume"], 0)
            self.assertEqual(path.read_bytes(), before)
            with (root / "report/missing_minutes.csv").open(encoding="utf-8-sig", newline="") as stream:
                missing = list(csv.DictReader(stream))
            self.assertEqual([row["minute"] for row in missing], ["10:05"])
            self.assertEqual(result["largest_gaps"][0]["missing_minutes"], 1)
            changed = json.loads(calendar.read_text())
            changed["coverage_end"] = "2024-01-10"
            calendar.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Calendar does not cover"):
                audit.audit(path, root / "outside_calendar", calendar)

    def test_sourced_calendar_includes_later_amendments(self):
        self.assertEqual(audit.hhmm(540), "09:00")
        self.assertEqual(audit.hhmm(869), "14:29")
        calendar = json.loads((audit.ROOT / "config/data/hnx-holidays-2018-2026.json").read_text())
        holidays = {day for days in calendar["holidays_by_year"].values() for day in days}
        self.assertEqual(len(holidays), 93)
        self.assertIn("2024-04-29", holidays)
        self.assertIn("2026-01-02", holidays)


if __name__ == "__main__":
    unittest.main()
