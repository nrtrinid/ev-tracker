# Methodology: How EV Is Calculated

This document explains the mathematical foundation behind EV Betting Tracker's scanner. All calculations are implemented in `backend/calculations.py` and `backend/services/odds_api.py`.

---

## The Core Idea

Standard sportsbooks ("soft books") like DraftKings and FanDuel build a profit margin (the "vig" or "juice") into their odds. This means their lines systematically overstate the true probability of each outcome.

Pinnacle is a "sharp book" — it accepts large bets from professional bettors and adjusts its lines aggressively in response. As a result, Pinnacle's lines serve as the market's best estimate of true outcome probabilities. By removing Pinnacle's small vig, we can derive a **no-vig fair probability** and compare it directly against soft book payouts.

If the soft book is paying better than fair, we have a +EV bet.

---

## Step 1: Odds Conversion

All American odds are first converted to decimal:

```
If odds ≥ 0:   decimal = 1 + (odds / 100)
If odds < 0:   decimal = 1 + (100 / |odds|)
```

**Examples:**
- `+150` → `2.50`
- `−150` → `1.667`
- `+100` → `2.00`

Decimal odds represent total return per $1 wagered, including the original stake.

---

## Step 2: De-Vigging Pinnacle

Given Pinnacle's two-way moneyline (both sides), we remove the vig using the **additive (proportional) method**:

```
implied_a = 1 / decimal_a
implied_b = 1 / decimal_b
overround  = implied_a + implied_b   # > 1.0 due to the vig

true_prob_a = implied_a / overround
true_prob_b = implied_b / overround
```

The overround represents the total "extra" probability built into the line. Dividing each side by the overround strips the vig proportionally, giving true probabilities that sum to exactly 1.0.

**Example:**

Pinnacle posts: Home −115, Away +100

```
decimal_home = 1 + 100/115 = 1.8696
decimal_away = 1 + 100/100 = 2.0000

implied_home = 1/1.8696 = 0.5349
implied_away = 1/2.0000 = 0.5000
overround    = 0.5349 + 0.5000 = 1.0349

true_prob_home = 0.5349 / 1.0349 = 0.5169  (51.7%)
true_prob_away = 0.5000 / 1.0349 = 0.4831  (48.3%)
```

This implementation is in `devig_pinnacle()` in `odds_api.py`.

---

## Step 3: Calculate Edge

With the true probability in hand, we compare it against the soft book's payout:

```
EV = (true_prob × book_decimal) − 1
```

This gives the expected return per $1 wagered at the soft book's odds, using our best estimate of the true probability.

**Example:**

DraftKings posts Home at −105 (decimal = 1.9524), true probability = 51.7%

```
EV = (0.517 × 1.9524) − 1 = 1.0094 − 1 = +0.94%
```

This means for every $100 wagered, you expect to gain $0.94 on average over many bets.

A positive EV means the book's payout exceeds what the sharp market says is fair. A negative EV means the book's line is sharper than (or consistent with) Pinnacle — no edge.

---

## Step 4: Kelly Criterion (Bet Sizing)

Once we have true probability and decimal odds, we calculate the optimal fraction of bankroll to wager using the **Kelly Criterion**:

```
f* = (b × p − q) / b

Where:
  b = decimal_odds − 1   (net payout per $1 wagered)
  p = true probability of winning
  q = 1 − p
```

If `f* ≤ 0`, no bet is recommended.

The backend returns `base_kelly_fraction` (full Kelly). The frontend multiplies by the user's `kellyMultiplier` (default: 0.25 for "quarter Kelly") and their bankroll to give a dollar recommendation:

```
recommended_bet = base_kelly_fraction × kelly_multiplier × bankroll
```

**Why fractional Kelly?** Full Kelly maximizes long-run bankroll growth but produces very volatile swings. Quarter Kelly (0.25×) is a common practical choice that sacrifices some growth for much smoother variance.

**Example:**

DraftKings: +215 (decimal 3.15, `b` = 2.15), true prob = 32.0%

```
f* = (2.15 × 0.32 − 0.68) / 2.15 = (0.688 − 0.68) / 2.15 = 0.008 / 2.15 ≈ 0.0037
```

With $1,000 bankroll and 0.25× multiplier: `0.0037 × 0.25 × 1000 = $0.93`

---

## What This Methodology Does Not Do

- **Doesn't account for CLV decay.** Lines move between the time you see them and when you place the bet. Always confirm odds haven't moved before placing.
- **Doesn't model correlated legs.** Each side is evaluated independently.
- **Doesn't adjust for low-liquidity markets.** UFC and tennis lines can be thinner, meaning Pinnacle's hold may be higher and the de-vig less precise.
- **Moneylines only.** The scanner currently evaluates head-to-head (h2h) markets only. Spreads and totals are not included.

---

## Operational Notes

- **Scheduler-first operations:** Math and de-vig logic are unchanged, but production scan execution is expected to run primarily through scheduler jobs when enabled.
- **Cron fallback:** If your host sleeps or scheduler is disabled, external cron routes can trigger the same scan pipeline.
- **Shared cache behavior:** Multiple scan triggers (manual, scheduler, cron) share the same 5-minute per-sport cache, reducing quota usage and keeping outputs consistent.
- **Operator visibility:** `/api/ops/status` and `/admin/ops` expose compact scan/odds activity summaries (counts, recency, status) to diagnose data freshness and API reliability.
- **No payload leakage:** Ops activity telemetry intentionally excludes raw API response payloads and secrets.

---

## Further Reading

- [The Kelly Criterion — Wikipedia](https://en.wikipedia.org/wiki/Kelly_criterion)
- [De-vigging methods — Pinnacle Resources](https://www.pinnacle.com/en/betting-articles/educational/the-basics-of-betting/no-vig-fair-odds)
- [The Odds API documentation](https://the-odds-api.com/liveapi/guides/v4/)
