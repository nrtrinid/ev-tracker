# Promo Lenses: How Each Promotion Type Is Modeled

The scanner exposes four "lenses" — each with a distinct mathematical objective. This document explains what each lens does, why the math differs, and how to use them.

All lens logic lives in `frontend/src/app/scanner/page.tsx`.

---

## Overview

| Lens | Objective | Key Metric | Best Bet Type |
|---|---|---|---|
| Standard EV | Maximize expected profit | EV% | Any odds with a true edge |
| Profit Boost | Maximize boosted EV | Boosted EV% | Odds that benefit most from multiplied payouts |
| Bonus Bet | Maximize retained value | Retention % | Longer odds (+200 to +400) |
| Qualifier | Minimize qualifying loss | EV% (near 0) | Restricted odds window (−250 to +150) |

---

## 1. Standard EV

**When to use:** You have a straight cash bet or a standard promo with no special multiplier.

**Objective:** Find lines where the sharp probability exceeds the soft book's implied probability — a genuine statistical edge.

**Formula:**
```
EV% = (true_prob × book_decimal − 1) × 100
```

The scanner filters to EV% > 0 and sorts descending. The "Rec Bet" sizing uses Fractional Kelly (see [methodology.md](./methodology.md)).

**What to look for:** Lines where the book is slow to move after a sharp line shift. Favorites that are priced slightly softer than Pinnacle are common.

---

## 2. Profit Boost

**When to use:** You have a profit boost token (e.g., "30% profit boost on any moneyline").

**How it works:** The boost is applied to the *profit portion* of the payout only. For a $100 bet on a +200 line with a 30% boost:

```
Normal payout:   $100 + $200 profit = $300
Boosted payout:  $100 + $200 × 1.30 = $100 + $260 = $360
Boosted odds:    +260
```

**Formula:**
```
base_profit   = book_decimal − 1
boosted_profit = base_profit × (1 + boost% / 100)
boosted_decimal = 1 + boosted_profit

boosted_EV% = (true_prob × boosted_decimal − 1) × 100
```

The scanner sorts by `boosted_EV%` descending using the selected boost percentage (30% or 50%).

**What to look for:** Lines that were borderline negative EV at true odds but become +EV after applying the boost. Boosts are most powerful on longer odds (e.g., +200 line becomes +260 at 30%) because the absolute dollar gain is larger.

**Note:** Winnings caps (common on boost tokens) are handled in the `calculate_ev()` backend function but not currently surfaced in the scanner UI.

---

## 3. Bonus Bet

**When to use:** You have a "bonus bet" (also called "free bet") token where the stake is not returned on a win.

**Key difference:** With a real money bet at +200, a $100 win returns $300 ($200 profit + $100 stake). With a bonus bet, the same win only returns $200 — the stake is forfeited.

This changes the objective entirely. You're not trying to maximize edge vs. a fair line — you're trying to maximize **how much real money you extract from the token**.

**Formula:**
```
retention = (book_decimal − 1) × true_prob
```

Retention is the expected fraction of the bonus bet's face value you'll receive as real cash. A retention of 0.72 means a $100 bonus bet is expected to yield $72 in real winnings.

**Why longer odds?**

A $100 bonus bet at +100 (decimal 2.0): `retention = 1.0 × 0.50 = 50%`  
A $100 bonus bet at +300 (decimal 4.0): `retention = 3.0 × 0.25 = 75%`

Longer odds increase the multiplier (`decimal − 1`) faster than the probability decreases. There's a sweet spot roughly between +250 and +450 where retention peaks. Beyond ~+600, the win probability gets too low.

The scanner sorts by `retention` descending and shows the top 10 targets across your selected books.

**Benchmark:** 70%+ retention is considered excellent. Below 60% is generally not worth it.

---

## 4. Qualifier

**When to use:** A promotion requires a qualifying bet that meets specific odds criteria before unlocking a bonus (e.g., "place a $50 bet at −200 or longer to activate your free bet").

**Objective:** The qualifier itself isn't meant to make money — it's the cost to unlock a larger promo. So the goal is to **minimize the qualifying loss**, not maximize profit.

**Filter:**
```
−250 ≤ book_odds ≤ +150
```

This window is common across book qualifying requirements. It excludes heavy favorites (where losses are most severe) and longer odds (where variance is higher).

**Sort:** Within the filtered odds window, sides are sorted by `EV%` descending. A result at −1.2% EV is better than one at −3.5% — you're looking for the least-bad qualifying option, ideally one close to 0% or slightly positive.

**Strategy:**
- If a qualifying bet is also slightly +EV (positive result in this lens), that's a free qualifier — the promotion has zero qualifying cost.
- If a near-0% EV line is available in the window, the qualifying cost is close to the book's vig alone (~2–4%), which is minimal relative to the bonus value.

---

## Promo Calculations in the Backend

For bets you've already logged, `backend/calculations.py` computes `ev_per_dollar` at log time:

| Promo Type | `ev_per_dollar` formula |
|---|---|
| `standard` | `−vig` (tracks expected loss vs. fair) |
| `bonus_bet` | `1 − 1/decimal_odds` (expected return on free stake) |
| `no_sweat` | `−vig` (cost of the qualifying leg; the refund is logged separately) |
| `promo_qualifier` | `−vig` (same as no_sweat — minimize cost) |
| `boost_30/50/100/custom` | `win_prob × boost_value − vig` |

The scanner's real-time lens math and the logged-bet EV math are consistent — both reference the same true probability from Pinnacle de-vigging.
