# Data Checks and Quality Reports

No dataset has been approved for research.

Before backtesting, prepare a report with these details:


| Area        | What to record                                                               |
| ------------- | ------------------------------------------------------------------------------ |
| Source      | Provider, access method, restrictions, version, and checksum                 |
| Fields      | Names, units, timestamps, timezone, and how observations or bars are built   |
| Instrument  | Actual contract, expiry, front-month selection, and rollover                 |
| Sessions    | Historical calendar, auctions, breaks, holidays, and exceptions              |
| Quality     | Duplicates, time order, invalid values, gaps, and stale observations         |
| Coverage    | Dates and contracts available, gaps near entries/exits, and affected periods |
| Splits      | Development, validation, and final-holdout dates                             |
| Preparation | Repeatable transformations, input/output versions, and dataset root          |
| Decision    | Allowed uses, open issues, and reasons to reject affected evaluations        |

## Understand Missing Observations

A missing bar may come from a trading break, no trades, the provider's aggregation rules, or lost data. Check the source before choosing how to handle it.

For example, suppose a strategy plans to exit at 14:25 but data stops at 14:20. The system must recognize the scheduled exit. It cannot record a fill without valid execution data. Keep the open position visible and mark the affected evaluation according to a rule defined in advance.

Forward-filling a price does not prove an order could trade there. The final row in a file also does not prove the market session ended. Valuing an open position and closing it are different actions.

## Set Rules Before Reviewing Results

Define gap limits, stale-price limits, and how affected periods will be reported. Apply exclusions consistently across strategies and report their effect on data coverage. Do not remove periods because they produce losses.

Document local data access and container reproduction separately. See the [data policy](../../data/README.md).
