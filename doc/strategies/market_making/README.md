# Market Making

Status: Step 1 not started. No hypothesis, rules, parameters, or results are frozen.

## Research Idea

Study a defined method for placing bid and ask quotes while limiting inventory on VN30F1M. Quote formulas and fill assumptions have not been selected.

## What to Record

- The proposed source of returns, prediction, and rejection conditions.
- Quote/trade coverage, timestamp detail, and stale-price handling.
- Order placement, latency, queue position, partial fills, and cancellation rules.
- Inventory limits, adverse price moves, costs, and session/contract changes.
- Source URL, exact commit, files, and license conditions for any adapted code.
- Experiment settings, results, limits, and stage decisions as work progresses.

## Next Step

Check whether the data and execution model can support the study, following the [research plan](../../research-plan.md). A price touching an order level does not prove the order was filled.
