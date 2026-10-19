# Data Policy

## Current Status

No research dataset or synthetic example has been added. Data coverage and suitability have not been checked.

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

Keep field definitions, transformations, session and contract coverage, gaps, stale-price rules, and time splits under [doc/data](../doc/data/README.md).

Check gaps against the historical session calendar and the source's data format. Synthetic examples help check correctness; they do not measure market performance.
