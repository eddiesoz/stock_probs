---
title: "Forecast model"
description: "How Stock Probability builds two empirical return distributions and reports probabilities, intervals, quality, and evaluation."
---

# Forecast model

The current model contract is `forecast-contract-v2`; the model version is
`empirical-ewma-v2`. One captured market-data snapshot produces two results:

1. **Close to next close** starts at the latest completed daily close.
2. **Completed five-minute bar to applicable close** starts at the latest regular-session
   five-minute bar whose end is at or before the request cutoff. During an open session the
   target is that session's close. Outside an open session, the completed prior close is the
   origin and the next scheduled close is the target.

An active partial five-minute bar is excluded. Scheduled US equity sessions use
`America/New_York`, including modeled holidays and common early closes; unscheduled closures
are a stated limitation.

## Samples and transformation

The daily horizon requires at least 61 completed daily closes and uses at most 504 returns.
Open-session intraday samples compare the same bar-start time in prior regular sessions with
each session close. Returns with absolute magnitude of at least 50% are excluded as likely
split, corporate-action, currency, or unit discontinuities.

Each eligible return is standardized using volatility known before that observation, then
rescaled using volatility known at the request cutoff. The configured EWMA spans are 30 for
daily returns and 10 for intraday returns. This prior-only sequence prevents look-ahead
leakage. Small samples of three or fewer returns use the explicit unadjusted fallback.

## Reported distribution

Direction uses `-0.1%` and `+0.1%` boundaries: below is down, within the boundaries is
unchanged, and above is up. Event probabilities use `(events + 0.5) / (samples + 1)` and the
three direction values are normalized to one. The API also reports event counts and 95%
Wilson intervals for the unsmoothed event rates.

Threshold rows report returns at or below `-1%`, `-3%`, `-5%`, and `-10%`, and at or above
`+1%`, `+3%`, `+5%`, and `+10%`. Conditional gain/loss values describe magnitude only among
samples in that direction. Central 50%, 80%, and 95% empirical intervals use interpolated
sample quantiles and are shown as both percentage returns and prices from the origin.

Chronological walk-forward evaluation uses prior outcomes only and reports direction and
threshold scores, reliability bins, and interval coverage. These are historical empirical
summaries—not causal predictions, guaranteed confidence, or trading advice. Inspect the
displayed provider as-of time, request cutoff, quality reasons, sample accounting, model
fingerprint, and limitations before interpreting a result.

See [dashboard usage](../usage/dashboard.md) for the visible controls and result panels.
