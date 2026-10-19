# Research Plan

## Current Work

The repository has a folder structure, working instructions, strategy notes, and data rules. No strategy hypothesis, dataset, code, or result has been validated.

The next task is to write a momentum hypothesis. Complete one strategy's research steps before expanding the shared code to support more strategies.

## Development Order


| Order | Strategy       | What to learn                                                        |
| ------- | ---------------- | ---------------------------------------------------------------------- |
| 1     | Momentum       | Follow one hypothesis through data preparation and rule design       |
| 2     | Mean reversion | Test a different price behavior with the same accounting             |
| 3     | Grid           | Handle several order levels, inventory, and exposure limits          |
| 4     | Event-driven   | Work with event sources, publication times, and limited samples      |
| 5     | Market making  | Model quotes, fills, inventory, and execution                        |
| 6     | Scalping       | Check short-horizon signals, trading costs, latency, and data detail |

This order supports learning; it does not rank expected profits. Event-driven work needs suitable event data. Market making and scalping need enough market detail to support their execution assumptions. Record the reason if this order changes.

## Learn from Existing Repositories

Before adapting code, record the source URL, exact commit, files, and license conditions in the relevant strategy or experiment notes.

Follow a trade through contract selection, data preparation, signals, orders, fills, positions, and PnL. Explain which parts can be reused and which assumptions need correction. Check source code and reported results separately.

## Evidence for Each Step


| Step                      | What must be recorded                                                                    |
| --------------------------- | ------------------------------------------------------------------------------------------ |
| Repository preparation    | Scope, working instructions, strategy folders, and data rules                            |
| 1. Form hypotheses        | Reasoning, prediction, data needs, alternatives, and rejection conditions                |
| 2. Prepare data           | Sources, checksums, fields, coverage, quality report, and time splits                    |
| 3. Form rules             | Signals, orders, sizing, risk limits, execution rules, and essential correctness checks  |
| 4. In-sample backtest     | New explicit human request, frozen experiment, checked accounting, trade log, and report |
| 5. Optimize               | Search budget, all trials, selection rule, and parameter sensitivity                     |
| 6. Out-of-sample backtest | Frozen setup, untouched evaluation data, and research decision                           |
| 7. Paper trading          | Authorized scope, forward signal/order logs, execution comparison, and incidents         |

Track progress separately for each strategy. Stop or revise the work if data is insufficient or the evidence rejects the hypothesis. Having a file for a step does not mean that step has passed.

## First Hypothesis

The momentum hypothesis should explain:

- What price behavior is expected and why it may exist.
- What can be measured and over which time horizon.
- Which market and other data are needed.
- Which other explanations could produce the same pattern.
- Which observations would reject the hypothesis.
- Which execution and risk assumptions need checking.

## Checks Before Performance Evaluation

Use small synthetic examples to check:

1. A normal trade, with fees and net PnL calculated independently.
2. A data gap while a position is open.
3. Data ending before the planned exit.
4. Session changes, contract changes, and outstanding orders.
5. An exit trigger when the executable price is missing or stale.

Define expected behavior before writing checks. Do not fill gaps just to produce a complete equity curve.

## Comparison

Follow the [comparison rules](comparison/README.md). Use validation data to develop and select strategies. Test frozen candidates on the final holdout using a plan written beforehand. If those results guide later selection or changes, record that use and confirm the revised choice with new future data.

## Decision Log


| Date       | Decision                                                              | Reason                                                                       | Next action                                          |
| ------------ | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------ |
| 2026-10-19 | Keep six strategy families in one repo and develop them one at a time | Agreed scope; common data checks and accounting help comparison              | Write the first momentum hypothesis                  |
| 2026-10-19 | Keep the template report forms and define missing-data rules          | Existing report forms; previously reported missing bars and unresolved exits | Define coverage and execution rules in Steps 2 and 3 |
| 2026-10-19 | Use simpler English across project documents                          | Requested documentation update and the personal writing skill                | Keep the same style in future research notes         |
