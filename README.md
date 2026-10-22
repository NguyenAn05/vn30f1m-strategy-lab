# VN30F1M Strategy Lab

This project studies six trading strategy families for VN30F1M futures. The goal is to understand how they work, test their assumptions, and compare their results using a repeatable process based on the Plutus standard.

## Project Status

The repository structure and research documents are ready. A standard-library Python collector can download DNSE one-minute candles into one CSV at `data/raw/VN30F1M_1m.csv`; see the [data instructions](data/README.md). Step 1 has not started for any strategy. There is no strategy code or verified performance result yet. Plutus verification has not been run.


| Strategy family | Status             | Research notes                                            |
| ----------------- | -------------------- | ----------------------------------------------------------- |
| Momentum        | Step 1 not started | [Momentum](doc/strategies/momentum/README.md)             |
| Mean reversion  | Step 1 not started | [Mean reversion](doc/strategies/mean_reversion/README.md) |
| Event-driven    | Step 1 not started | [Event-driven](doc/strategies/event_driven/README.md)     |
| Market making   | Step 1 not started | [Market making](doc/strategies/market_making/README.md)   |
| Scalping        | Step 1 not started | [Scalping](doc/strategies/scalping/README.md)             |
| Grid            | Step 1 not started | [Grid](doc/strategies/grid/README.md)                     |

## Goals

- Learn from existing ALGOTRADE repositories and check their assumptions before adapting their code.
- Explain what each strategy expects to earn from and when it may fail.
- Check data quality, trades, positions, fees, and PnL before reviewing returns.
- Compare strategies under conditions defined before the experiments.
- Record failed experiments and unclear results as well as successful ones.

## Trading Scope

The target is the nearest-expiry VN30 futures contract, usually represented by the rolling identifier `VN30F1M`. Each observation must identify the actual listed contract, its expiry, and the rule used to roll to the next contract.

Other data may help form signals, while trading stays within this instrument scope. Each strategy will be developed and tested separately. Running several strategies in one portfolio will need a separate plan for capital and order handling.

## Research Process

1. Form a hypothesis.
2. Prepare the data, including collection and processing.
3. Turn the hypothesis into trading rules.
4. Backtest on in-sample data.
5. Optimize parameters and check their sensitivity.
6. Backtest on out-of-sample data.
7. Run paper trading.

Each strategy has its own records and stage decisions. Move to the next stage when the required evidence is available. A hypothesis may be revised or rejected.

## Repository Structure


| Path                                         | Purpose                                             |
| ---------------------------------------------- | ----------------------------------------------------- |
| [AGENTS.md](AGENTS.md)                       | Working instructions                                |
| [doc/research-plan.md](doc/research-plan.md) | Research order, required evidence, and decision log |
| [doc/strategies/](doc/strategies/)           | Notes for each strategy                             |
| [doc/comparison/](doc/comparison/README.md)  | Rules for comparing strategies                      |
| [doc/report/](doc/report/)                   | Report forms from the original template             |
| [src/](src/README)                           | Future source code                                  |
| [config/](config/README)                     | Future research configurations                      |
| [data/](data/README.md)                      | Data policy, download and audit instructions         |
| [tests/](tests/README.md)                    | Planned correctness checks                          |

## Data and Reproduction

Data coverage and suitability have not been checked. Restricted market data is not included. Read the [data policy](data/README.md) before adding any dataset.

Before backtesting, record the data version, time splits, trading sessions, contracts, gaps, and execution assumptions. If data is missing, keep affected positions and results visible. Do not create a fill from a made-up price.

The collector requires Python 3.10 or later and no third-party packages. The strategy environment and Plutus manifest remain to be defined. Future dependencies must be pinned. Container runs must use a declared and permitted way to obtain their inputs.

## Next Step

Write the first momentum hypothesis and list the data needed to test it. See the [research plan](doc/research-plan.md).

## References

- [Plutus Project Template](https://github.com/algotrade-plutus/plutus-project-template): the starting folder structure and report forms.
- [ProtoMarketMaker](https://github.com/algotrade-plutus/ProtoMarketMaker): a reference for reviewing strategy code and accounting.
- [Plutus Guideline](https://github.com/algotrade-plutus/plutus-guideline): the project standard and technical guide.

When adapting code, record the source commit, files, and license conditions in the relevant strategy or experiment notes. A reference repository's results or badge do not verify this project's results. Follow the authority order in [AGENTS.md](AGENTS.md).
