# Agent UI Rules

## Purpose

This document translates the design direction into concrete implementation rules for AI agents and future contributors.

Use this together with [design-direction.md](./design-direction.md).

## Repo-Specific Theme Sources

Before changing UI styling, inspect and reuse the existing theme system:

- [frontend/src/app/globals.css](../../frontend/src/app/globals.css) for current light and dark tokens
- [frontend/src/app/layout.tsx](../../frontend/src/app/layout.tsx) for root theme initialization
- [frontend/src/lib/theme.ts](../../frontend/src/lib/theme.ts) for theme persistence and root-class application
- [frontend/src/lib/theme-context.tsx](../../frontend/src/lib/theme-context.tsx) for client-side theme state
- [frontend/src/app/settings/page.tsx](../../frontend/src/app/settings/page.tsx) for the user-facing theme toggle

Do not add a parallel theme system when extending the UI.

## Core Product Split

Treat screens in two groups.

### Operational Screens

These should feel like an instrument panel:

- `/scanner/[surface]`
- `/bets`
- `/bets/stats`
- settlement and tracker surfaces
- dense controls, filters, and chart panels

Default treatment:

- stable surfaces
- clear borders
- minimal atmosphere
- strong text hierarchy
- few accent colors

### Brand Screens

These can carry more editorial warmth:

- `/`
- Daily Drop modules
- onboarding
- empty states
- highlight banners

Brand warmth is allowed here, but clarity still wins if the screen becomes data-dense.

## Non-Negotiable Rules

- Use semantic roles and existing CSS variables before introducing new color values.
- Prefer contrast, spacing, and borders before adding more color.
- Dark mode should be clean and readable, not foggy or paper-textured.
- Gold is a featured accent, not the universal CTA color.
- Green means positive outcome.
- Red means negative outcome.
- Blue means information, links, navigation, or sportsbook identity.
- Use fewer badge styles, not more.
- If a workflow card is dense, flatten it.
- If information is repeated, align it.
- If a value matters, make it visually stronger than its label.

## Theme Implementation Rules

- Default theme is dark unless product direction explicitly changes it globally.
- Dark mode is the same field guide at night — warm charcoal base (`hsl(30 10% 10%)`), not cool blue-gray slate.
- Do not use `hsl(220 ...)` backgrounds in dark mode. That hue breaks the warm identity.
- Light mode is allowed to feel warmer and more tactile than dark mode.
- Do not simulate paper through grain or haze on core workflow cards.
- Apply theme preference through the root html class, not by per-component overrides.
- Keep theme persistence local unless the product explicitly decides to store it server-side.
- Paper grain: `opacity: 0.16` in light, `opacity: 0.06` in dark. Do not set to 0 — invisible grain contributes nothing.

## Text Hierarchy Rules

The "everything looks the same" problem comes from collapsing all secondary content into one muted tier. Use the 4-level system:

- `text-hi` (or `text-foreground`): titles, key values, odds, EV numbers — the thing the user reads first
- `text-mid` (or `text-muted-foreground`): event names, matchup context, supporting labels
- `text-lo`: timestamps, helper text, secondary metadata — readable but clearly subordinate
- `text-ghost`: placeholder text, disabled states, decorative dividers

In dark mode, Level 1 to Level 2 gap must be at least 35 lightness points. If you're unsure which level a piece of text belongs to, ask: "would the user miss this if it disappeared?" If yes, it's Level 1 or 2. If no, it's Level 3 or 4.

Do not use raw `opacity` to create hierarchy — it interacts badly with colored backgrounds. Use the explicit token levels above.

## Surface Rules

- Use only three main surface levels: app background, card surface, raised interactive surface.
- Do not create stacks of nearly identical dark panels.
- Operational cards should not use ambient gradients as their default background.
- Internal card sections should be separated with borders or tonal shifts, not mystery-meat darkness.
- In dark mode, increase border clarity before increasing shadow or glow.

## Typography Rules

- Keep a clear ladder between page title, section title, card title, labels, and helper text.
- Avoid putting most text into the same muted middle tier.
- Secondary text must remain readable.
- Use tabular numerals for odds, money, EV, stake, bankroll, percentages, and stat grids.
- Avoid excessive uppercase in dense data screens.

Use existing numeric styling where possible:

- [frontend/src/app/globals.css](../../frontend/src/app/globals.css) already gives `.font-mono` tabular numerals

## Buttons, Tabs, Inputs, Chips

### Buttons

- One primary action per context should be obvious.
- Outline buttons should still feel interactive.
- Destructive buttons should be clear but restrained.
- Do not use a featured gold treatment as the default button language everywhere.

### Tabs And Segmented Controls

- Selected state must be obvious at a glance.
- Contrast must be stronger than surrounding chrome.
- Avoid glow-heavy treatments.

### Inputs And Filters

- Inputs need a clear boundary against the background.
- Selected filters must be easy to identify.
- Reset and secondary actions should be visible, but subordinate.

### Chips And Badges

Keep chip types limited to meaningful categories such as:

- sportsbook
- market type
- featured
- promo
- CLV state

If badges start forming a rainbow, simplify.

## Charts

- Charts should use stable panels and readable labels.
- Gridlines should be subtle but visible.
- Range and variance treatments should not muddy the chart.
- Prefer analytical clarity over decorative styling.

## Current Design Biases To Avoid

Avoid introducing any of the following into operational surfaces:

- full-card haze
- paper-grain overlays in dark mode
- soft atmospheric gradients on every card
- low-contrast metadata
- too many accent colors at once
- glowing controls as the primary emphasis method

## When Unsure, Choose This

If a design choice is ambiguous, prefer:

- flatter surface over richer texture
- clearer border over deeper shadow
- fewer accents over more accents
- readable secondary text over moodier muted text
- semantic consistency over novelty
- numeric clarity over decorative hierarchy

## Implementation Boundaries

- Extend the existing Tailwind and CSS-variable setup instead of introducing a new design system layer.
- Reuse current shared components before creating one-off styling exceptions.
- Do not perform broad layout rewrites when the goal is visual clarity.
- Do not mix brand experimentation into scanner, tracker, and stats without preserving scan speed.

## Recommended Order For UI Overhauls

1. Fix tokens, spacing, borders, and hierarchy.
2. Normalize shared controls and card patterns.
3. Clean up scanner, tracker, and stats.
4. Add personality back into Daily Drop, onboarding, and empty states.

## Acceptance Test For Agents

Your UI changes are moving in the right direction if:

- the main action on a card is obvious
- important values read faster than before
- dark mode feels cleaner after the change, not moodier
- there are fewer accents competing on screen
- borders and spacing create more structure than color alone
- the result still feels like EV Tracker
