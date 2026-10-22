"""Audit CSV values and minute-label coverage without changing market data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / "data" / "raw" / "VN30F1M_1m.csv"
DEFAULT_REPORT_DIR = ROOT / "data" / "raw" / "quality_report"
LOCAL_TZ = timezone(timedelta(hours=7))
SESSIONS = {"morning": list(range(540, 690)), "afternoon": list(range(780, 870))}
OPEN_GRID = set(SESSIONS["morning"] + SESSIONS["afternoon"])
CORE_GRID = OPEN_GRID - {540, 780}
MISSING = {"", "nan", "na", "n/a", "null", "none"}
SESSION_SOURCE = "https://hdsd.entrade.com.vn/man-hinh-giao-dich/quy-trinh-giao-dich/thuc-hien-giao-dich/thoi-gian-giao-dich-chung-khoan-phai-sinh-1"


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def consecutive_runs(values) -> list[list[int]]:
    result = []
    for value in sorted(set(values)):
        if not result or value != result[-1][-1] + 1:
            result.append([value])
        else:
            result[-1].append(value)
    return result


def weekday_blocks(days: list[date], holidays=()) -> list[list[date]]:
    """Skip weekends and explicitly supplied closures; break at other absent days."""
    blocks = []
    for day in sorted(days):
        expected = blocks[-1][-1] + timedelta(days=1) if blocks else day
        while expected.weekday() >= 5 or expected in holidays:
            expected += timedelta(days=1)
        if not blocks or day != expected:
            blocks.append([day])
        else:
            blocks[-1].append(day)
    return blocks


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None):
    fields = fields or (list(rows[0]) if rows else [])
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def audit(input_path: Path, output: Path, calendar_path: Path | None = None) -> dict:
    original_hash = file_hash(input_path)
    minute_sets = defaultdict(set)
    day_rows = Counter()
    boundary_counts = defaultdict(Counter)
    missing_values = Counter()
    invalid_numeric = Counter()
    counts = Counter()
    issues = []
    previous = None
    first = None
    last = None
    with input_path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames
        required = {"timestamp_utc", "timestamp_vietnam", "symbol", "open", "high", "low", "close", "volume"}
        if columns is None or not required.issubset(columns):
            raise ValueError("Missing required CSV columns")
        for line, row in enumerate(reader, start=2):
            counts["rows"] += 1
            row_issues = []
            if None in row:
                row_issues.append("extra_columns")
            for column in columns:
                if row.get(column) is None or row[column].strip().lower() in MISSING:
                    missing_values[column] += 1
                    row_issues.append(f"missing:{column}")
            numbers = {}
            for column in ("open", "high", "low", "close", "volume"):
                try:
                    value = float(row[column])
                    if not math.isfinite(value):
                        raise ValueError()
                    numbers[column] = value
                except (ValueError, TypeError):
                    invalid_numeric[column] += 1
            if len(numbers) == 5:
                if not (0 < numbers["low"] <= numbers["open"] <= numbers["high"]
                        and numbers["low"] <= numbers["close"] <= numbers["high"]):
                    counts["invalid_ohlc_rows"] += 1
                    row_issues.append("invalid_ohlc")
                if numbers["volume"] < 0:
                    counts["negative_volume_rows"] += 1
                    row_issues.append("negative_volume")
                if numbers["volume"] == 0:
                    counts["zero_volume_rows"] += 1
            if row["symbol"] != "VN30F1M":
                counts["unexpected_symbol_rows"] += 1
                row_issues.append("unexpected_symbol")
            try:
                local = datetime.fromisoformat(row["timestamp_vietnam"])
                utc = datetime.fromisoformat(row["timestamp_utc"])
                if local.tzinfo is None or utc.tzinfo is None:
                    raise ValueError("Timestamp has no timezone")
                if local != utc or local.utcoffset() != timedelta(hours=7) or utc.utcoffset() != timedelta(0):
                    counts["timestamp_pair_mismatches"] += 1
                    row_issues.append("timestamp_pair_mismatch")
                local = local.astimezone(LOCAL_TZ)
                if previous is not None and local < previous:
                    counts["out_of_order_rows"] += 1
                    row_issues.append("out_of_order")
                previous = local
                first = min(first, local) if first else local
                last = max(last, local) if last else local
                day = local.date()
                minute = local.hour * 60 + local.minute
                day_rows[day] += 1
                if local.second or local.microsecond:
                    counts["off_minute_rows"] += 1
                    row_issues.append("off_minute")
                else:
                    if minute in minute_sets[day]:
                        counts["duplicate_minute_rows"] += 1
                        row_issues.append("duplicate_minute")
                    minute_sets[day].add(minute)
                    boundary_counts[day.year][minute] += 1
            except (ValueError, TypeError):
                counts["invalid_timestamp_rows"] += 1
                row_issues.append("invalid_timestamp")
            if row_issues:
                issues.append({"csv_line": line, "timestamp_vietnam": row.get("timestamp_vietnam"),
                               "issues": ";".join(row_issues)})
    if first is None:
        raise ValueError("No valid timestamp found")

    metadata_path = input_path.with_suffix(".metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    start = date.fromisoformat(metadata.get("requested_start", first.date().isoformat()))
    end = date.fromisoformat(metadata.get("requested_end", last.date().isoformat()))
    start, end = min(start, first.date()), max(end, last.date())
    calendar = json.loads(calendar_path.read_text(encoding="utf-8")) if calendar_path else {}
    holidays = {date.fromisoformat(day) for days in calendar.get("holidays_by_year", {}).values() for day in days}
    if calendar and not (date.fromisoformat(calendar["coverage_start"]) <= start <= end <= date.fromisoformat(calendar["coverage_end"])):
        raise ValueError("Calendar does not cover the full input range")
    daily = []
    missing_minutes = []
    gaps = []
    segments = []
    absent_weekdays = []
    absent_trading_days = []
    complete_days = {"open_labels_240": [], "core_labels_238": []}
    yearly = {}
    boundary_presence = []
    missing_frequency = Counter()
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        seen = minute_sets.get(day, set())
        observed = bool(day_rows[day])
        status = "observed" if observed else ("weekend_no_rows" if day.weekday() >= 5 else (
            "scheduled_holiday_no_rows" if day in holidays else (
                "scheduled_trading_day_no_rows" if calendar else "weekday_no_rows_unclassified")))
        missing = OPEN_GRID - seen
        core_missing = CORE_GRID - seen
        if not observed and day.weekday() < 5:
            absent_weekdays.append(day)
            if calendar and day not in holidays:
                absent_trading_days.append(day)
        if observed:
            if not missing:
                complete_days["open_labels_240"].append(day)
            if not core_missing:
                complete_days["core_labels_238"].append(day)
            stats = yearly.setdefault(day.year, Counter())
            stats.update({"observed_days": 1, "rows": day_rows[day], "missing_open_labels": len(missing),
                          "missing_core_labels": len(core_missing), "complete_open_days": int(not missing),
                          "complete_core_days": int(not core_missing)})
            for minute in missing:
                missing_frequency[minute] += 1
            for session, expected in SESSIONS.items():
                for run in consecutive_runs(set(expected) - seen):
                    core_count = sum(minute in CORE_GRID for minute in run)
                    gaps.append({"date": day.isoformat(), "session": session,
                                 "missing_start": hhmm(run[0]), "missing_end_inclusive": hhmm(run[-1]),
                                 "missing_minutes": len(run), "core_missing_minutes": core_count,
                                 "opening_boundary_missing_minutes": len(run) - core_count,
                                 "cause": "unresolved_missing_bar_or_no_trade_or_source_issue",
                                 "exact_minutes": ";".join(hhmm(minute) for minute in run)})
                    for minute in run:
                        missing_minutes.append({"timestamp_vietnam": f"{day}T{hhmm(minute)}:00+07:00",
                                                "date": day.isoformat(), "session": session,
                                                "minute": hhmm(minute),
                                                "classification": "core" if minute in CORE_GRID else "opening_boundary_unverified"})
                for run in consecutive_runs(set(expected) & seen):
                    segments.append({"date": day.isoformat(), "session": session,
                                     "start": hhmm(run[0]), "end_inclusive": hhmm(run[-1]),
                                     "available_minute_labels": len(run),
                                     "complete_open_session": int(len(run) == len(expected))})
        daily.append({"date": day.isoformat(), "weekday": day.strftime("%A"), "status": status,
                      "rows": day_rows[day], "observed_open_labels": len(OPEN_GRID & seen),
                      "missing_open_labels_if_observed": len(missing) if observed else "",
                      "missing_core_labels_if_observed": len(core_missing) if observed else "",
                      "complete_open_day": int(observed and not missing),
                      "complete_core_day": int(observed and not core_missing),
                      "has_0900": int(540 in seen), "has_1130": int(690 in seen),
                      "has_1300": int(780 in seen), "has_1430": int(870 in seen), "has_1445": int(885 in seen),
                      "outside_open_grid_labels": ";".join(hhmm(m) for m in sorted(seen - OPEN_GRID))})
    periods = []
    for profile, days in complete_days.items():
        for block in weekday_blocks(days, holidays):
            periods.append({"profile": profile, "start_date": block[0].isoformat(), "end_date": block[-1].isoformat(),
                            "complete_observed_days": len(block), "calendar_days": (block[-1] - block[0]).days + 1,
                            "calendar_rule": "weekends_and_sourced_holidays_skipped" if calendar else "weekends_skipped_unobserved_weekdays_break_the_period"})
    empty_blocks = []
    for block in weekday_blocks(absent_weekdays):
        empty_blocks.append({"start_date": block[0].isoformat(), "end_date": block[-1].isoformat(),
                             "weekday_count": len(block), "calendar_days": (block[-1] - block[0]).days + 1,
                             "scheduled_holidays": sum(day in holidays for day in block),
                             "other_empty_weekdays": sum(day not in holidays for day in block),
                             "classification": "see_daily_calendar_classification" if calendar else "unclassified_holiday_or_missing_data",
                             "exact_weekdays": ";".join(str(day) for day in block)})
    for year, frequency in sorted(boundary_counts.items()):
        for minute in (540, 690, 780, 870, 885):
            boundary_presence.append({"year": year, "minute": hhmm(minute), "observed_days": yearly[year]["observed_days"],
                                      "days_with_label": frequency[minute]})
    frequency_rows = [{"minute": hhmm(minute), "missing_observed_days": missing_frequency[minute],
                       "classification": "core" if minute in CORE_GRID else "opening_boundary_unverified"}
                      for minute in sorted(OPEN_GRID)]
    source_by_day = {source["requested_day_vietnam"]: source for source in metadata.get("sources", [])}
    raw_review = []
    for day in absent_trading_days:
        source = source_by_day.get(str(day), {})
        review = {"date": str(day), "export_source_status": source.get("status", "unavailable"),
                  "http_status": "", "raw_response_rows": "", "raw_checksum_matches_export": "",
                  "review_status": "source_unavailable"}
        folder = Path(source.get("snapshot_dir", "")).resolve()
        if source and folder.is_relative_to(input_path.parent.resolve()):
            try:
                body = (folder / "response.json").read_bytes()
                payload = json.loads(body)
                raw_meta = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
                review.update({"http_status": raw_meta.get("http_status"),
                               "raw_response_rows": len(payload["t"]) if isinstance(payload.get("t"), list) else "invalid_schema",
                               "raw_checksum_matches_export": sha256_bytes(body) == source.get("response_sha256"),
                               "review_status": "reviewed"})
            except (OSError, ValueError, TypeError, AttributeError):
                review["review_status"] = "source_unreadable"
        raw_review.append(review)
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "daily_coverage.csv", daily)
    write_csv(output / "missing_intervals.csv", gaps, ["date", "session", "missing_start", "missing_end_inclusive", "missing_minutes", "core_missing_minutes", "opening_boundary_missing_minutes", "cause", "exact_minutes"])
    write_csv(output / "missing_minutes.csv", missing_minutes, ["timestamp_vietnam", "date", "session", "minute", "classification"])
    write_csv(output / "continuous_segments.csv", segments)
    write_csv(output / "complete_periods.csv", periods)
    write_csv(output / "empty_weekday_blocks.csv", empty_blocks)
    missing_day_blocks = [{"start_date": str(block[0]), "end_date": str(block[-1]),
                           "missing_scheduled_days": len(block), "calendar_days": (block[-1] - block[0]).days + 1,
                           "missing_open_labels_under_schedule": len(block) * 240,
                           "exact_missing_dates": ";".join(str(day) for day in block),
                           "cause": "unresolved_source_gap_or_exceptional_market_event"}
                          for block in weekday_blocks(absent_trading_days, holidays)]
    write_csv(output / "missing_day_blocks.csv", missing_day_blocks,
              ["start_date", "end_date", "missing_scheduled_days", "calendar_days", "missing_open_labels_under_schedule", "exact_missing_dates", "cause"])
    write_csv(output / "missing_trading_days.csv", [{"date": str(day), "expected_morning_labels": 150,
              "expected_afternoon_labels": 90, "missing_open_labels_under_schedule": 240,
              "minutes": "09:00-11:29;13:00-14:29", "cause": "unresolved_source_gap_or_exceptional_market_event"}
              for day in absent_trading_days], ["date", "expected_morning_labels", "expected_afternoon_labels", "missing_open_labels_under_schedule", "minutes", "cause"])
    write_csv(output / "minute_frequency.csv", frequency_rows)
    write_csv(output / "boundary_presence.csv", boundary_presence)
    write_csv(output / "empty_day_raw_review.csv", raw_review,
              ["date", "export_source_status", "http_status", "raw_response_rows", "raw_checksum_matches_export", "review_status"])
    write_csv(output / "row_issues.csv", issues, ["csv_line", "timestamp_vietnam", "issues"])
    write_csv(output / "yearly_summary.csv", [{"year": year, **dict(stats)} for year, stats in sorted(yearly.items())])
    summary = {
        "input": str(input_path.resolve()), "sha256": original_hash,
        "audit_created_at_utc": datetime.now(timezone.utc).isoformat(),
        "auditor_sha256": file_hash(Path(__file__)),
        "hash_matches_download_metadata": original_hash == metadata.get("csv_sha256"),
        "first_timestamp": first.isoformat(), "last_timestamp": last.isoformat(),
        "rows": counts["rows"], "observed_days": len(day_rows),
        "missing_values_by_column": {column: missing_values[column] for column in columns},
        "nonfinite_or_invalid_numeric_by_column": dict(invalid_numeric),
        "row_checks": dict(counts), "issue_rows": len(issues),
        "open_label_grid": "09:00-11:29 and 13:00-14:29 inclusive; 240 labels; assumes bar-open labels",
        "core_label_grid": "09:01-11:29 and 13:01-14:29 inclusive; 238 labels; excludes ambiguous opening labels",
        "missing_minutes_observed_days_open_grid": len(missing_minutes),
        "missing_minutes_observed_days_core_grid": sum(row["classification"] == "core" for row in missing_minutes),
        "missing_intervals_observed_days": len(gaps),
        "complete_observed_days_open_grid": len(complete_days["open_labels_240"]),
        "complete_observed_days_core_grid": len(complete_days["core_labels_238"]),
        "empty_weekdays_total": len(absent_weekdays),
        "empty_weekdays_unclassified": 0 if calendar else len(absent_weekdays),
        "scheduled_holidays_without_rows": sum(day in holidays for day in absent_weekdays),
        "scheduled_trading_days_without_rows": len(absent_trading_days) if calendar else None,
        "missing_open_labels_including_absent_scheduled_days": len(missing_minutes) + len(absent_trading_days) * 240 if calendar else None,
        "empty_weekends": sum(row["status"] == "weekend_no_rows" for row in daily),
        "empty_weekday_blocks": len(empty_blocks),
        "yearly": [{"year": year, **dict(stats)} for year, stats in sorted(yearly.items())],
        "largest_gaps": sorted(gaps, key=lambda row: row["missing_minutes"], reverse=True)[:15],
        "longest_complete_periods_open_grid": sorted([p for p in periods if p["profile"] == "open_labels_240"], key=lambda row: row["complete_observed_days"], reverse=True)[:15],
        "longest_empty_weekday_blocks": sorted(empty_blocks, key=lambda row: row["weekday_count"], reverse=True)[:15],
        "missing_day_blocks": sorted(missing_day_blocks, key=lambda row: row["missing_scheduled_days"], reverse=True),
        "calendar_file": str(calendar_path.resolve()) if calendar_path else None,
        "calendar_sha256": file_hash(calendar_path) if calendar_path else None,
        "calendar_sources": calendar.get("sources", []),
        "absent_scheduled_days_with_verified_empty_raw_response": sum(
            row["review_status"] == "reviewed" and row["raw_response_rows"] == 0
            and row["raw_checksum_matches_export"] and row["http_status"] == 200 for row in raw_review),
        "unexpected_nonboundary_minutes": [{"date": str(day), "minute": hhmm(minute)}
            for day, seen in sorted(minute_sets.items()) for minute in sorted(seen - OPEN_GRID - {690, 870, 885})],
        "session_source": SESSION_SOURCE,
        "limitations": ["Scheduled HNX closures are supplied; exceptional historical suspensions are not exhaustively verified." if calendar else "No independently verified historical exchange holiday calendar was supplied.",
                        "Scheduled missing days may reflect a source problem or an exceptional market event; causes remain unresolved.",
                        "A missing label may reflect no trade, aggregation conventions, or data loss; causes are unresolved.",
                        "Auction periods are not treated as continuous one-minute matching sessions.",
                        "Complete periods skip only weekends and explicitly sourced holidays; all other absent scheduled days break a period.",
                        "Only structural data checks were performed; no strategy performance or holdout exploration."],
    }
    if file_hash(input_path) != original_hash:
        raise RuntimeError("Input changed during the audit; rerun against a stable snapshot")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_report(summary, output)
    return summary


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def write_report(summary: dict, output: Path):
    """Write a readable report beside the exhaustive audit CSVs."""
    s = summary
    missing_total = s["missing_open_labels_including_absent_scheduled_days"]
    missing_total_text = f"{missing_total:,}" if missing_total is not None else "not estimated without a supplied calendar"
    lines = ["# VN30F1M One-Minute Data Audit", "",
             f"Input: `{s['input']}`", f"SHA-256: `{s['sha256']}`", "",
             f"Audit created: {s['audit_created_at_utc']}. Auditor SHA-256: `{s['auditor_sha256']}`.", "",
             f"Coverage: {s['first_timestamp']} through {s['last_timestamp']}.",
             f"The file has {s['rows']:,} rows across {s['observed_days']:,} observed dates. The source CSV was not changed.", "",
             "## Values and Timestamps", "",
             "| Check | Result |", "| --- | ---: |",
             f"| Missing cells / NaN tokens | {sum(s['missing_values_by_column'].values()):,} |",
             f"| Non-finite or invalid numeric cells | {sum(s['nonfinite_or_invalid_numeric_by_column'].values()):,} |",
             f"| Duplicate minute rows | {s['row_checks'].get('duplicate_minute_rows', 0):,} |",
             f"| Out-of-order rows | {s['row_checks'].get('out_of_order_rows', 0):,} |",
             f"| Invalid OHLC rows | {s['row_checks'].get('invalid_ohlc_rows', 0):,} |",
             f"| UTC/local timestamp mismatches | {s['row_checks'].get('timestamp_pair_mismatches', 0):,} |",
             f"| CSV checksum matches download metadata | {s['hash_matches_download_metadata']} |", "",
             "No missing cells does not mean no missing bars. A missing bar has no row in the source CSV.", "",
             "## Coverage Definition", "",
             f"[DNSE session reference]({SESSION_SOURCE}) separates continuous matching, lunch, and auctions. The main audit assumes bar-open minute labels: **09:00-11:29 and 13:00-14:29**, or **240 labels per scheduled trading day**. This is a stated audit convention; provider label semantics remain unverified.", "",
             "A second check removes the ambiguous 09:00 and 13:00 opening labels: **238 core labels**, 09:01-11:29 and 13:01-14:29. Labels at 11:30, 14:30 and the 14:45 close are reported separately. Missing bars during the opening/closing auction are not counted as continuous-session gaps. Lunch, nights, weekends, and the supplied scheduled HNX holidays are excluded.", "",
             f"On observed dates, **{s['missing_minutes_observed_days_open_grid']:,} labels** are absent across **{s['missing_intervals_observed_days']:,} intervals** under the 240-label convention. Of these, **{s['missing_minutes_observed_days_core_grid']:,}** are core labels and **{s['missing_minutes_observed_days_open_grid'] - s['missing_minutes_observed_days_core_grid']:,}** are opening labels. Missing-minute counts count labels inclusively; they are not the elapsed wall-clock difference between the last and next bar.", "",
             f"**{s['complete_observed_days_open_grid']:,}/{s['observed_days']:,} observed dates** contain all 240 labels. **{s['complete_observed_days_core_grid']:,}** contain all 238 core labels. These counts do not include fully absent scheduled dates.", "",
             "| Year | Observed dates | Rows | Missing 240-grid labels | Missing core labels | Complete 240-grid dates |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in s["yearly"]:
        lines.append(f"| {row['year']} | {row['observed_days']} | {row['rows']:,} | {row['missing_open_labels']} | {row['missing_core_labels']} | {row['complete_open_days']} |")
    lines += ["", "## Whole Dates Without Data", "",
              f"There are {s['empty_weekdays_total']} weekdays without rows: **{s['scheduled_holidays_without_rows']} scheduled holidays** and **{s['scheduled_trading_days_without_rows']} otherwise scheduled trading dates**. Another {s['empty_weekends']} dates are weekends without rows. Holiday dates and amendments are transcribed in the supplied calendar; this is not an exhaustive investigation of exceptional historical suspensions.", "",
              f"For **{s['absent_scheduled_days_with_verified_empty_raw_response']}** absent scheduled dates, the saved raw response is HTTP 200 with an empty `t` array and its checksum matches the export source record. For these dates the consolidated CSV did not drop existing raw candles; the stored API response was empty. Why the provider returned empty remains unresolved.", "",
              "| Start | End | Absent scheduled dates | Calendar-day span |",
              "| --- | --- | ---: | ---: |"]
    for row in s["missing_day_blocks"]:
        lines.append(f"| {row['start_date']} | {row['end_date']} | {row['missing_scheduled_days']} | {row['calendar_days']} |")
    lines += ["", f"The 240-label convention therefore has **{missing_total_text} absent labels** including the otherwise scheduled whole-day gaps. This is conditional on the published schedule, not proof that every missing label resulted from a data-feed outage.", "",
              "## Longest Complete Periods", "",
              "Each listed period contains all 240 labels on every scheduled trading date. Weekends and sourced holidays are skipped. Any other absent scheduled date or incomplete observed date breaks the period. The full list, including the alternate 238-label profile, is in `complete_periods.csv`.", "",
              "| Start | End | Complete scheduled dates |", "| --- | --- | ---: |"]
    for row in s["longest_complete_periods_open_grid"]:
        lines.append(f"| {row['start_date']} | {row['end_date']} | {row['complete_observed_days']} |")
    lines += ["", "## Largest Gaps Within Observed Dates", "",
              "Both missing endpoints are inclusive. `missing_intervals.csv` lists all intervals and the exact missing minute labels. `missing_minutes.csv` has one row per absent label in an observed date; fully absent scheduled dates are listed separately in `missing_trading_days.csv`.", "",
              "| Date | Session | Missing from | Missing through | Missing labels | Core labels |",
              "| --- | --- | --- | --- | ---: | ---: |"]
    for row in s["largest_gaps"]:
        lines.append(f"| {row['date']} | {row['session']} | {row['missing_start']} | {row['missing_end_inclusive']} | {row['missing_minutes']} | {row['core_missing_minutes']} |")
    lines += ["", "## Boundary Labels and Unusual Times", "",
              "`boundary_presence.csv` shows the year-by-year presence of 09:00, 11:30, 13:00, 14:30 and 14:45. The frequent disappearance of 11:30 and 14:30 labels in later data is not counted as lost continuous-session minutes. A 243-row day and a 241-row day can both contain the complete 240-label grid.", ""]
    for row in s["unexpected_nonboundary_minutes"]:
        lines.append(f"- Unexpected nonboundary label: {row['date']} {row['minute']} Vietnam time. Its meaning requires provider confirmation.")
    lines += ["", "## Files", "",
              "- `daily_coverage.csv`: every calendar date, expected-label coverage and boundary markers.",
              "- `missing_intervals.csv`: all intraday missing runs, durations and exact minutes.",
              "- `missing_minutes.csv`: each absent minute in an observed date.",
              "- `missing_day_blocks.csv` and `missing_trading_days.csv`: whole scheduled dates without rows.",
              "- `continuous_segments.csv`: every uninterrupted one-minute run inside each continuous session.",
              "- `complete_periods.csv`: all maximal complete-date periods for the 240- and 238-label profiles.",
              "- `empty_day_raw_review.csv`: raw-response checks for otherwise scheduled dates without data.",
              "- `yearly_summary.csv`, `minute_frequency.csv`, `boundary_presence.csv`, `row_issues.csv` and `summary.json`: supporting audit details.", "",
              "## Research Use", "",
              "Missing labels may reflect no trades, source aggregation, provider gaps, or exceptional exchange events. Do not forward-fill them as execution evidence. Full minute-label coverage does not verify contract mapping, rollover, bar availability time, prices against another source, or execution feasibility. This audit does not approve strategy backtesting or inspect performance.", "",
              f"Calendar checksum: `{s['calendar_sha256']}`. Calendar source notices:", ""]
    for source in s["calendar_sources"]:
        lines.append(f"- [{source['id']}]({source['url']}) ({source['published']}).")
    lines += ["", "Rerun from the repository root:", "", "```powershell",
              "python src/vn30f1m_strategy_lab/data/audit_dnse.py", "```", ""]
    (output / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--calendar", type=Path, default=ROOT / "config/data/hnx-holidays-2018-2026.json")
    args = parser.parse_args()
    summary = audit(args.csv.resolve(), args.output_dir.resolve(), args.calendar.resolve())
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
