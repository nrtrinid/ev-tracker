# Methodology: How EV Is Calculated

This document explains the mathematical foundation behind EV Betting Tracker's pricing. Straight bets and player props use different reference models.

- Straight bets: Pinnacle remains the sharp reference.
- Player props: curated cross-book consensus is the reference model.

See [player-props-v2.md](./player-props-v2.md) for the props-specific approach.

---

## The Core Idea

Soft books build vig into their prices. Sharp reference markets move faster and provide a better estimate of fair probability. If a target book is paying better than that fair estimate, the bet is positive expected value.

The home page daily board reuses this logic, even though it serves persisted snapshots instead of always hitting a live manual scan path.

---

## Step 1: Convert Odds

All American odds are converted to decimal.

```text
If odds >= 0: decimal = 1 + odds / 100
If odds < 0:  decimal = 1 + 100 / abs(odds)
```

Examples:

- `+150` -> `2.50`
- `-150` -> `1.667`
- `+100` -> `2.00`

---

## Step 2: Remove The Vig

For a two-way market:

```text
implied_a = 1 / decimal_a
implied_b = 1 / decimal_b
overround = implied_a + implied_b

true_prob_a = implied_a / overround
true_prob_b = implied_b / overround
```

This produces a no-vig probability pair that sums to 1.0.

---

## Step 3: Calculate Edge

```text
EV = (true_prob * book_decimal) - 1
```

Positive EV means the book payout is better than the fair estimate implied by the sharp reference.

---

## Step 4: Kelly Sizing

The system computes full Kelly first:

```text
f* = (b * p - q) / b

where:
  b = decimal_odds - 1
  p = true probability
  q = 1 - p
```

The frontend then applies the user's Kelly multiplier and bankroll.

```text
recommended_bet = base_kelly_fraction * kelly_multiplier * bankroll
```

Quarter Kelly is the default practical setting because it cuts variance materially.

---

## What This Does Not Do

- It does not guarantee a line will still be available by the time you place it.
- It does not solve correlation between legs.
- It does not make every thin market equally trustworthy.
- It does not make CLV and actual game result the same thing.

Straight-bet scanning now covers moneylines, spreads, and totals when an exact-line sharp reference is available, but reliability still varies by market depth and slate quality.

---

## Operational Notes

- Straight bets can run on scheduled paths and the daily board.
- Player props are still curated, but they now also feed the daily board, Pick'em validation, and CLV close tracking.
- Multiple triggers share the same straight-bet cache to protect quota.
- `/api/ops/status` and `/admin/ops` expose compact activity summaries for diagnosing freshness and API health.

---

## Further Reading

- [The Kelly Criterion - Wikipedia](https://en.wikipedia.org/wiki/Kelly_criterion)
- [The Odds API documentation](https://the-odds-api.com/liveapi/guides/v4/)
