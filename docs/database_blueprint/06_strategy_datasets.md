# Strategy Datasets

Each strategy row is derived from tier-level current probabilities after the
fixed high-prize adjustment or its official-count fallback.

Supported keys are:

- `money_back_exact`
- `profit_ex_top`
- `value_full`
- `value_ex_top`
- `moderate_5x`
- `moderate_10x`
- `jackpot_top_odds`
- `large_1000`
- `large_100000`

Every row includes the metric, optional one-in value, launch comparison,
target-tier count, count/value coverage, lowest confidence label, lumpy-tier
indicator, source/catalog observation timestamps, analytics run, and model
version.

Only complete non-null strategy rows receive ranks. The frontend may filter
lumpy confidence, but that filter is a user choice rather than a backend gate.
Small high tiers and tiers without a historical adjustment reference use their
official remaining count and therefore remain represented.

Rankings are available only when:

- the current unpaid-prizes source is complete and fresh;
- the current catalog is complete and fresh;
- the analytics run succeeded for that exact source run; and
- the game is in the current source/catalog recommendation intersection.
