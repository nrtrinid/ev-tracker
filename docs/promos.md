# Promo Lenses: How Each Promotion Type Is Modeled

The app exposes four promo lenses, each with a different mathematical objective.

These lens rules power:

- the manual scanner
- home page `Promos`
- any flow that ranks the same board-backed sides through boost, bonus-bet, or qualifier logic

For scanner request/cache/runtime flow details, see [scanner.md](./scanner.md).

---

## Overview

| Lens | Objective | Key Metric | Best Bet Type |
|---|---|---|---|
| Standard EV | Maximize expected profit | EV% | Any odds with a true edge |
| Profit Boost | Maximize boosted EV | Boosted EV% | Odds that benefit most from multiplied payouts |
| Bonus Bet | Maximize retained value | Retention % | Longer odds with strong retention |
| Qualifier | Minimize qualifying loss | EV% near 0 | Restricted odds window |

---

## 1. Standard EV

**When to use:** You have a normal cash bet with no modifier.

**Formula:**

```text
EV% = (true_prob * book_decimal - 1) * 100
```

The system sorts descending by EV%.

---

## 2. Profit Boost

**When to use:** You have a profit boost token.

The boost applies to the profit portion only.

```text
base_profit = book_decimal - 1
boosted_profit = base_profit * (1 + boost_pct / 100)
boosted_decimal = 1 + boosted_profit

boosted_EV% = (true_prob * boosted_decimal - 1) * 100
```

Boosts usually help longer prices more because the multiplied profit portion is larger.

---

## 3. Bonus Bet

**When to use:** You are trying to maximize the retained value of a free bet / bonus bet token.

Because the original stake is not returned on a win, the right objective is retention rather than standard EV.

```text
retention = (book_decimal - 1) * true_prob
```

Higher retention means more real-money value extracted from the token.

---

## 4. Qualifier

**When to use:** You are placing the least-bad qualifying leg to unlock a bigger offer.

Typical filter:

```text
-250 <= book_odds <= +150
```

Within the window, the system favors lines closest to zero cost.

---

## Logged-Bet Promo Math

For logged bets, the backend computes `ev_per_dollar` in `backend/calculations.py`.

| Promo Type | `ev_per_dollar` intuition |
|---|---|
| `standard` | expected loss vs fair (vig-aware) |
| `bonus_bet` | retained value of the free stake |
| `no_sweat` | cost of the qualifying leg |
| `promo_qualifier` | same qualifying-cost framing |
| `boost_*` | win probability times boost value minus vig |

---

## Board And Promos Behavior

The home page `Promos` view is broader than the old shortlist-style implementation.

- It merges player props with straight-bet game lines.
- Straight-bet promos can now include moneylines, spreads, and totals.
- Final display still depends on selected books, board inventory, and the active promo submode.

So it is normal for `Promos` and `Game Lines` to overlap while still serving different ranking goals.

---

## Operational Notes

- Lens math stays consistent across manual scans, board-backed views, and cached results.
- Because scan results are cached per sport, repeated runs can look identical within the TTL window.
- Ops visibility lives in `/admin/ops` and `/api/ops/status` when promo output feels stale or unexpectedly empty.
