# Correctness Checks

The DNSE collector has synthetic checks in test_dnse_download.py. Run `python -m unittest discover -s tests -p 'test_dnse_download.py' -v` from the repository root. No strategy code has been added.

Use synthetic examples with expected results calculated independently to check:

1. Entry, exit, fees, cash, positions, and net PnL for a normal trade.
2. Missing observations while a position is open.
3. Data ending before the planned exit.
4. A scheduled exit without a fresh executable price.
5. Session changes, contract changes, and outstanding orders.
6. Position limits, margin, and exposure.

Keep unresolved positions visible and reflect them in the evaluation status. Closing a position, valuing it, and reaching the end of a file are different events.

Tests must give repeatable results and work without private documents or the knowledge service. Synthetic tests do not prove a strategy is profitable.
