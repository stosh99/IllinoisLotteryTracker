# Legacy/New Analytics Comparison

- Generated at: `2026-08-08T23:51:25+00:00`
- Model: `core_ticket_model 1.0.0`
- Source run: `91`
- Source observed at: `2026-08-08T03:04:43-04:00`
- Current games compared: `57`

This is the required one-time transition audit. The legacy estimate uses all
reported remaining winning tickets times published overall odds as its
denominator. The replacement uses the non-circular <=$500 progress model,
leave-one-tier-out regular references, and cutoff-versioned high-tier status.
The columns are therefore expected to differ and must not be overwritten.

## Coverage and Difference Summary

| Metric | Paired games | Median new - legacy | Mean absolute difference |
|---|---:|---:|---:|
| Estimated remaining tickets | 55 | -15.720178 | 166.623498 |
| EV full | 55 | -0.020935 | 0.139955 |
| EV excluding top | 55 | -0.003126 | 0.045142 |
| Payout ratio full | 55 | -0.003658 | 0.008133 |

## Largest Full-EV Differences

| Game | Legacy EV | New EV | New - legacy | Data status |
|---|---:|---:|---:|---|
| 7670 $5,000,000 JACKPOT | 23.776129 | 20.277694 | -3.498435 | partial |
| 7654 SAPPHIRE 10S | 7.517302 | 6.912584 | -0.604718 | partial |
| 7611 MILLIONAIRE CLUB | 41.270998 | 40.939213 | -0.331785 | complete |
| 7653 BLOWOUT X | 23.933646 | 23.650144 | -0.283502 | complete |
| 7661 $3 MILLION VAULT | 16.198883 | 15.933625 | -0.265258 | complete |
| 7575 $10,000,000 BANKROLL | 40.958764 | 40.693929 | -0.264835 | complete |
| 7650 DIAMONDS | 8.026450 | 7.806449 | -0.220001 | complete |
| 7590 200X THE CASH | 24.013880 | 23.811449 | -0.202431 | complete |
| 7657 DOUBLE THE LUCK | 16.398534 | 16.198664 | -0.199870 | complete |
| 7621 $2,000,000 DIAMOND DELUXE | 15.795965 | 15.599497 | -0.196468 | complete |
| 7624 $2,000,000 MAXIMUM MULTIPLIER | 15.656771 | 15.470342 | -0.186429 | complete |
| 7616 $1,000,000 CA$H CHA$ER | 8.246242 | 8.089247 | -0.156995 | complete |
| 7623 ROYAL RICHES | 23.353799 | 23.219278 | -0.134521 | complete |
| 7646 GOLD RUSH SUPREME | 7.518277 | 7.388757 | -0.129520 | complete |
| 7665 $1,000,000 CROSSWORD 50X | 19.421501 | 19.321550 | -0.099951 | complete |

## Cutover Decision

- Legacy columns remain physically present and unchanged for audit.
- Nightly/import code no longer writes legacy estimated columns.
- Current reports and rankings use versioned analytics views only.
- The legacy report command is disabled with an explicit deprecation message.
