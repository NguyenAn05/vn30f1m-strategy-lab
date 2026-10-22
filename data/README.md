# Data Policy

## Current Status

The local DNSE download is stored under raw/. Its structural audit is under raw/quality_report/. These files are ignored by Git. A structural audit does not approve the dataset for strategy evaluation. No synthetic example has been added.

## What Can Be Stored Here

- Data definitions, source information, checksums, and preparation code.
- Clearly labeled synthetic examples under synthetic/.
- Small excerpts allowed by the source license, with required attribution.
- Charts and summary statistics allowed by the source license.

Do not commit restricted raw data or processed data that could replace a substantial part of the original dataset. Do not upload the full dataset or publish substantial processed derivatives without prior written permission.

The workspace dataset is covered by ../../data/LICENSE. It must not be used for live or production trading.

## Data Access

Set a clear dataset root for local research. Record the source version and checksums so the same input can be identified again.

A Plutus container cannot be assumed to read files outside this repository. Define a permitted download, database/API preparation step, or permitted committed input for reproduction. An ignored local dataset alone is not enough.

## Data Checks

Keep field definitions, source settings and the sourced holiday calendar under ../config/data/. Local audit outputs belong under raw/quality_report/. Record transformations, session and contract coverage, gaps, stale-price rules, and time splits before strategy evaluation.

Check gaps against the historical session calendar and the source's data format. Synthetic examples help check correctness; they do not measure market performance.

## Download and Audit

Use Python 3.10 or later. No third-party packages are required. Run from the repository root:

```powershell
python src/vn30f1m_strategy_lab/data/fetch_dnse.py --start 2018-08-13 --end 2026-10-21
python src/vn30f1m_strategy_lab/data/audit_dnse.py
```

The collector defaults to VN30F1M one-minute candles and writes one consolidated CSV to `data/raw/VN30F1M_1m.csv`. Raw JSON snapshots and request metadata remain under `data/raw/dnse/` for source checks and resume. The auditor reads the same CSV and writes `data/raw/quality_report/REPORT.md` and supporting CSVs. Default paths are resolved from the repository location, independently of the working directory.

Both download dates are inclusive. Omitting `--end` uses yesterday in Vietnam; today and future dates are rejected. Repeat the original command to resume from checksum-verified snapshots. Use `--refresh` to download new snapshots. A successful export replaces the consolidated CSV with exactly the requested date range; keep the original start date when extending coverage. Interrupted or failed downloads export to `VN30F1M_1m.partial.csv` and preserve the previous complete CSV. Empty responses do not prove a market holiday or complete coverage.

The collector's `--output-dir` changes the storage root. If using a custom root, supply matching `--csv` and `--output-dir` paths to the auditor. `--symbol VN30` downloads the index separately. The auditor is specific to the VN30F1M CSV schema and uses the explicit calendar coverage in ../config/data/hnx-holidays-2018-2026.json.

After relocating existing snapshots, the collector discovers their current directories and verifies response checksums. Export metadata contains absolute source paths; update those location fields when moving an existing export. Historical per-snapshot metadata records the original collection location and is retained. The migration backup and record preserve that provenance.

Offline checks:

```powershell
python -m unittest discover -s tests -p 'test_dnse_*.py' -v
```
