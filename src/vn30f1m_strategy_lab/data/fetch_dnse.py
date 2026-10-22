"""Download completed days of DNSE one-minute candles using only the standard library."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
import time
import uuid
from datetime import date, datetime, time as day_time, timedelta, timezone
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

VIETNAM_TZ = timezone(timedelta(hours=7))
API_ROOT = "https://api.dnse.com.vn/chart-api/v2/ohlcs"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "data" / "raw"
FIELDS = ("t", "o", "h", "l", "c", "v")
CSV_FIELDS = ("timestamp_utc", "timestamp_vietnam", "symbol", "open", "high", "low", "close", "volume")
COLLECTOR_VERSION = 1


class DataError(Exception):
    """A request or response could not be used safely."""


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def day_bounds(day: date) -> tuple[int, int]:
    start = datetime.combine(day, day_time.min, tzinfo=VIETNAM_TZ)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())


def request_bytes(url: str, timeout: float, attempts: int) -> tuple[bytes, int, int]:
    """Retry transport failures, HTTP 429 and HTTP 5xx; preserve the final body."""
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "vn30f1m-strategy-lab/1"})
    for attempt in range(1, attempts + 1):
        wait = float(2 ** (attempt - 1))
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read(), response.status, attempt
        except HTTPError as exc:
            body = exc.read()
            status = exc.code
            retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
            exc.close()
            if status != 429 and not 500 <= status < 600:
                return body, status, attempt
            if retry_after:
                try:
                    wait = max(wait, float(retry_after))
                except ValueError:
                    # Do not retry early when an HTTP-date delay cannot be interpreted.
                    return body, status, attempt
            if attempt == attempts or not math.isfinite(wait) or wait > 60:
                return body, status, attempt
        except (URLError, TimeoutError, OSError, HTTPException) as exc:
            if attempt == attempts:
                raise DataError(f"Request failed after {attempt} attempt(s): {exc}") from exc
        time.sleep(wait)
    raise DataError("Request did not return a response")


def parse_candles(body: bytes, day: date, symbol: str) -> tuple[list[dict], dict]:
    """Validate without repairing, sorting, filling, or deduplicating prices."""
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError) as exc:
        raise DataError("Response is not valid JSON") from exc
    if not isinstance(payload, dict) or any(not isinstance(payload.get(key), list) for key in FIELDS):
        raise DataError("Expected arrays named t, o, h, l, c, v")
    lengths = {len(payload[key]) for key in FIELDS}
    if len(lengths) != 1:
        raise DataError("OHLCV arrays have different lengths")

    lower, upper = day_bounds(day)
    rows = []
    excluded = 0
    previous = None
    gaps = []
    for index, values in enumerate(zip(*(payload[key] for key in FIELDS))):
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
            raise DataError(f"Row {index}: timestamp and OHLCV must be numeric")
        try:
            finite = all(math.isfinite(value) for value in values)
        except OverflowError:
            finite = False
        if not finite:
            raise DataError(f"Row {index}: non-finite numeric value")
        stamp, opening, high, low, closing, volume = values
        if stamp != int(stamp) or stamp % 60:
            raise DataError(f"Row {index}: expected a whole minute in Unix seconds")
        try:
            utc = datetime.fromtimestamp(stamp, timezone.utc)
        except (ValueError, OverflowError, OSError) as exc:
            raise DataError(f"Row {index}: timestamp is outside the Unix-seconds date range") from exc
        if not lower <= stamp < upper:
            excluded += 1
            continue
        if previous is not None:
            if stamp <= previous:
                raise DataError(f"Row {index}: duplicate or unordered timestamp")
            if stamp - previous > 60:
                gaps.append(stamp - previous)
        if low <= 0 or not low <= opening <= high or not low <= closing <= high or volume < 0:
            raise DataError(f"Row {index}: invalid OHLC or volume; original response retained")
        rows.append(dict(zip(CSV_FIELDS, (
            utc.isoformat(), utc.astimezone(VIETNAM_TZ).isoformat(), symbol,
            opening, high, low, closing, volume,
        ))))
        previous = stamp
    return rows, {
        "response_rows": len(payload["t"]),
        "rows": len(rows),
        "excluded_outside_requested_day": excluded,
        "first_timestamp_vietnam": rows[0]["timestamp_vietnam"] if rows else None,
        "last_timestamp_vietnam": rows[-1]["timestamp_vietnam"] if rows else None,
        "gaps_gt_one_minute": len(gaps),
        "max_gap_seconds": max(gaps, default=0),
        "coverage_status": "not_verified_against_exchange_calendar",
    }


def request_parameters(day: date, symbol: str) -> tuple[str, dict]:
    market = "index" if symbol == "VN30" else "derivative"
    lower, upper = day_bounds(day)
    return f"{API_ROOT}/{market}", {"symbol": symbol, "resolution": "1", "from": lower, "to": upper}


def find_cached(day_dir: Path, endpoint: str, parameters: dict) -> dict | None:
    """Reuse compatible raw snapshots, including snapshots from the first collector."""
    for path in sorted(day_dir.glob("*/metadata.json"), reverse=True):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(meta, dict):
                continue
            if (meta.get("collector_version") != COLLECTOR_VERSION
                    or meta.get("endpoint") != endpoint or meta.get("parameters") != parameters
                    or meta.get("status") not in {"ok", "empty"}):
                continue
            body = (path.parent / "response.json").read_bytes()
            if sha256(body) != meta.get("response_sha256"):
                continue
            # Older snapshots included a daily CSV. Keep checking it when present.
            if "csv_sha256" in meta and sha256((path.parent / "bars.csv").read_bytes()) != meta["csv_sha256"]:
                continue
            return {**meta, "snapshot_dir": str(path.parent.resolve())}
        except (OSError, ValueError, TypeError):
            continue
    return None


def fetch_day(day: date, symbol: str, output: Path, *, refresh: bool = False,
              timeout: float = 30, attempts: int = 3, delay: float = 1) -> dict:
    endpoint, parameters = request_parameters(day, symbol)
    market = endpoint.rsplit("/", 1)[1]
    day_dir = output / "dnse" / market / symbol / "1m" / day.isoformat()
    code_hash = sha256(Path(__file__).read_bytes())
    if not refresh:
        cached = find_cached(day_dir, endpoint, parameters)
        if cached is not None:
            return {**cached, "cached": True}

    # Pause before each network request, including across day boundaries.
    time.sleep(delay)
    now = datetime.now(timezone.utc)
    snapshot = day_dir / f"{now:%Y%m%dT%H%M%S%fZ}_{uuid.uuid4().hex[:8]}"
    snapshot.mkdir(parents=True, exist_ok=False)
    meta = {
        "collector_version": COLLECTOR_VERSION,
        "collector_sha256": code_hash,
        "endpoint": endpoint,
        "parameters": parameters,
        "requested_day_vietnam": day.isoformat(),
        "requested_at_utc": now.isoformat(),
        "snapshot_dir": str(snapshot.resolve()),
        "instrument_kind": "spot_index" if symbol == "VN30" else "provider_continuous_front_month",
        "listed_contract": None,
        "bar_timestamp_semantics": "unverified",
        "status": "error",
    }
    try:
        body, status, used_attempts = request_bytes(f"{endpoint}?{urlencode(parameters)}", timeout, attempts)
        (snapshot / "response.json").write_bytes(body)
        meta.update({"http_status": status, "attempts": used_attempts,
                     "received_at_utc": datetime.now(timezone.utc).isoformat(),
                     "response_sha256": sha256(body)})
        if status != 200:
            raise DataError(f"HTTP {status}; response retained in {snapshot}")
        rows, summary = parse_candles(body, day, symbol)
        # Out-of-range-only responses are not evidence of an empty trading day.
        if not rows and summary["response_rows"]:
            raise DataError("Response contained no rows inside the requested day")
        meta.update(summary)
        meta["status"] = "ok" if rows else "empty"
    except DataError as exc:
        meta["error"] = str(exc)
    # Metadata is written last. Incomplete snapshots cannot be reused by the cache.
    (snapshot / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {**meta, "cached": False}


def export_csv(snapshots: list[dict], output: Path, start: date, end: date,
               symbol: str, *, interrupted: bool = False) -> dict:
    """Stream the requested range to one CSV; keep incomplete exports separate."""
    complete = (not interrupted and len(snapshots) == (end - start).days + 1
                and all(meta["status"] in {"ok", "empty"} for meta in snapshots))
    name = f"{symbol}_1m" + ("" if complete else ".partial")
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / f"{name}.csv"
    metadata_path = output / f"{name}.metadata.json"
    token = uuid.uuid4().hex
    temporary_csv = output / f".{name}.{token}.csv.tmp"
    temporary_metadata = output / f".{name}.{token}.metadata.tmp"
    row_count = 0
    sources = []
    try:
        with temporary_csv.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for index, meta in enumerate(snapshots):
                day = start + timedelta(days=index)
                endpoint, parameters = request_parameters(day, symbol)
                if meta.get("endpoint") != endpoint or meta.get("parameters") != parameters:
                    raise DataError(f"Snapshot does not match the requested day: {day}")
                sources.append({key: meta[key] for key in (
                    "requested_day_vietnam", "snapshot_dir", "status", "response_sha256", "error"
                ) if key in meta})
                if meta["status"] not in {"ok", "empty"}:
                    continue
                body = (Path(meta["snapshot_dir"]) / "response.json").read_bytes()
                if sha256(body) != meta.get("response_sha256"):
                    raise DataError(f"Raw snapshot checksum changed: {day}")
                rows, summary = parse_candles(body, day, symbol)
                if not rows and summary["response_rows"]:
                    raise DataError(f"Raw snapshot has no rows inside its requested day: {day}")
                writer.writerows(rows)
                row_count += len(rows)
        digest = hashlib.sha256()
        with temporary_csv.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        result = {
            "status": "complete" if complete else "partial",
            "symbol": symbol,
            "resolution_minutes": 1,
            "requested_start": start.isoformat(),
            "requested_end": end.isoformat(),
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "rows": row_count,
            "csv_file": str(csv_path.resolve()),
            "csv_sha256": digest.hexdigest(),
            "metadata_file": str(metadata_path.resolve()),
            "collector_sha256": sha256(Path(__file__).read_bytes()),
            "interrupted": interrupted,
            "processed_days": len(snapshots),
            "failed_days": sum(meta["status"] == "error" for meta in snapshots),
            "empty_days": sum(meta["status"] == "empty" for meta in snapshots),
            "coverage_status": "not_verified_against_exchange_calendar",
            "sources": sources,
        }
        temporary_metadata.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        temporary_csv.replace(csv_path)
        temporary_metadata.replace(metadata_path)
        return result
    finally:
        temporary_csv.unlink(missing_ok=True)
        temporary_metadata.unlink(missing_ok=True)


def iso_date(value: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use a valid YYYY-MM-DD date") from exc


def positive_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Must be a finite positive number")
    return number


def nonnegative_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("Must be a finite nonnegative number")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, type=iso_date, help="First Vietnam-local day, inclusive (YYYY-MM-DD)")
    parser.add_argument("--end", type=iso_date, default=datetime.now(VIETNAM_TZ).date() - timedelta(days=1),
                        help="Last day, inclusive; default yesterday in Vietnam")
    parser.add_argument("--symbol", choices=("VN30F1M", "VN30"), default="VN30F1M")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT, help="Default: repository data/raw")
    parser.add_argument("--refresh", action="store_true", help="Create new snapshots even when valid local files exist")
    parser.add_argument("--timeout", type=positive_float, default=30, help="Seconds per request attempt (default 30)")
    parser.add_argument("--attempts", type=int, choices=range(1, 6), default=3, help="Maximum attempts per day (default 3)")
    parser.add_argument("--delay", type=nonnegative_float, default=1, help="Seconds before each new daily request (default 1)")
    args = parser.parse_args(argv)
    if args.start > args.end:
        parser.error("--start must be on or before --end")
    if args.end >= datetime.now(VIETNAM_TZ).date():
        parser.error("Only completed days are supported; --end must be before today in Vietnam")
    if args.end == date.max:
        parser.error("--end is outside the supported date range")
    output = args.output_dir.resolve()
    print(f"Output: {output}", flush=True)
    counts = {"ok": 0, "empty": 0, "error": 0}
    cached_count = 0
    snapshots = []
    interrupted = False
    try:
        for offset in range((args.end - args.start).days + 1):
            day = args.start + timedelta(days=offset)
            meta = fetch_day(day, args.symbol, output, refresh=args.refresh,
                             timeout=args.timeout, attempts=args.attempts, delay=args.delay)
            snapshots.append(meta)
            status = meta["status"]
            counts[status] += 1
            cached_count += int(meta["cached"])
            detail = meta.get("error", f"{meta.get('rows', 0)} rows")
            print(f"{day} {args.symbol} {status.upper()} {'[cached] ' if meta['cached'] else ''}{detail}", flush=True)
    except KeyboardInterrupt:
        print("Interrupted. Run the same command to resume.", file=sys.stderr)
        interrupted = True
    except OSError as exc:
        print(f"Filesystem error: {exc}", file=sys.stderr)
        return 1
    try:
        result = export_csv(snapshots, output, args.start, args.end, args.symbol, interrupted=interrupted)
    except (OSError, DataError) as exc:
        print(f"CSV export failed: {exc}", file=sys.stderr)
        return 1
    print(f"CSV ({result['status']}): {result['csv_file']} ({result['rows']} rows)")
    print(f"Metadata: {result['metadata_file']}")
    print(f"Done: {counts['ok']} nonempty, {counts['empty']} empty, {counts['error']} failed; {cached_count} cached.")
    print("Empty responses and row counts do not establish complete exchange-session coverage.")
    return 130 if interrupted else (1 if counts["error"] else 0)


if __name__ == "__main__":
    raise SystemExit(main())
