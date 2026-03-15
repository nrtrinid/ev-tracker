# EV Tracker Color Palette

> **Important:** Only use colors from this palette. Do not introduce new colors without team discussion.

## Core Theme Colors (CSS Variables)

These are the primary design tokens. Use the Tailwind class names, not raw hex values.

| Token | Hex | Tailwind Class | Usage |
|-------|-----|----------------|-------|
| Background | `#FAF8F5` | `bg-background` | Page background |
| Foreground | `#2C2416` | `text-foreground` | Primary text |
| Card | `#F0EBE3` | `bg-card` | Card backgrounds |
| Primary | `#C4A35A` | `bg-primary` / `text-primary` | Amber accents, pending states |
| Muted | `#E8E4DC` | `bg-muted` / `text-muted-foreground` | Subtle backgrounds, secondary text |
| Border | `#DDD5C7` | `border-border` | All borders |

## Semantic Colors

| Name | Hex | Tailwind Class | Usage |
|------|-----|----------------|-------|
| Profit / Win | `#4A7C59` | `text-[#4A7C59]` | Positive numbers, win states |
| Loss | `#B85C38` | `text-[#B85C38]` | Negative numbers, loss states |
| Pending / Amber | `#C4A35A` | `text-[#C4A35A]` | Pending states, highlights |
| Neutral | `#6B5E4F` | `text-[#6B5E4F]` | Muted text, secondary info |

## Promo Type Badges

| Type | Background | Text | Classes |
|------|-----------|------|---------|
| Bonus Bet | `#7A9E7E/20` | `#4A7C59` | `bg-[#7A9E7E]/20 text-[#4A7C59]` |
| Boosts | `#C4A35A/20` | `#8B7355` | `bg-[#C4A35A]/20 text-[#8B7355]` |
| Standard | `#DDD5C7` | `#6B5E4F` | `bg-[#DDD5C7] text-[#6B5E4F]` |

## Sportsbook Brand Colors

Use for left borders and accent dots only. Text should remain neutral.

| Book | Hex | Tailwind Class |
|------|-----|----------------|
| DraftKings | `#4CBB17` | `bg-draftkings` / `text-draftkings` |
| FanDuel | `#0E7ACA` | `bg-fanduel` / `text-fanduel` |
| BetMGM | `#C5A562` | `bg-betmgm` / `text-betmgm` |
| Caesars | `#C49A6C` | `bg-caesars` / `text-caesars` |
| ESPN Bet | `#ED174C` | `bg-espnbet` / `text-espnbet` |
| Fanatics | `#0047BB` | `bg-fanatics` / `text-fanatics` |
| Hard Rock | `#FDB913` | `bg-hardrock` / `text-hardrock` |
| bet365 | `#00843D` | `bg-bet365` / `text-bet365` |

## Chart Colors (Ordered)

For pie charts, bar charts, etc. Apply in order.

```javascript
const CHART_COLORS = [
  "#4A7C59", // Forest green
  "#C4A35A", // Amber
  "#6B5E4F", // Warm gray
  "#B85C38", // Terracotta
  "#8B7355", // Taupe
  "#7A9E7E", // Sage
  "#D4C4A8", // Tan
  "#9B8A7B", // Stone
];
```

### Special: "Other" Category
For grouped/small slices in charts:
- **Color:** `#E7E5E4` (stone-200)
- Always render last in the legend

## Action Button Colors

| Action | Style |
|--------|-------|
| Win | `text-emerald-600 border-emerald-200 bg-emerald-50/30` |
| Loss | `text-rose-600 border-rose-200 bg-rose-50/30` |

## ROI Thresholds (Analytics)

| Condition | Color | Meaning |
|-----------|-------|---------|
| ROI > 15% | `text-[#4A7C59]` | High efficiency |
| ROI 0-15% | `text-[#C4A35A]` | Drifting |
| ROI < 0% | `text-[#B85C38]` | Leaking |

## Z-Score Performance Bands

| Z-Score | Color | Label |
|---------|-------|-------|
| ≥ 1.5 | `text-[#4A7C59]` | Running Hot |
| ≥ 0.5 | `text-[#4A7C59]` | Above Average |
| ≥ -0.5 | `text-[#C4A35A]` | On Track |
| ≥ -1.5 | `text-[#B85C38]` | Below Average |
| < -1.5 | `text-[#B85C38]` | Running Cold |

---

## ❌ Do NOT Use

These colors are **not** part of our palette:

- Generic Tailwind grays (`gray-*`, `slate-*`, `zinc-*`)
- Pure black (`#000000`) or pure white (`#FFFFFF`)
- Saturated primary colors (`red-500`, `blue-500`, `green-500`)
- Purple, pink, cyan, or any other hue not listed above

---

## Quick Reference

```
Positive/Win:   #4A7C59 (forest green)
Negative/Loss:  #B85C38 (terracotta)
Pending/Accent: #C4A35A (amber)
Neutral Text:   #6B5E4F (warm gray)
Background:     #FAF8F5 (cream)
Card:           #F0EBE3 (light cream)
Border:         #DDD5C7 (tan)
```


