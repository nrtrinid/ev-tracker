# Design Direction

## Product Theme In One Sentence

Warm utility: a clear, high-trust decision tool with a restrained field-guide personality.

## Core Rule

Use utility as the base and brand feel as the accent.

The product should feel:

- precise in workflows
- calm in data-heavy screens
- slightly warm and curated at the brand layer

It should not feel:

- foggy
- atmospheric everywhere
- textured on every surface
- like a dramatic sports app at the cost of readability

## Brand Thesis

The product should not feel like generic fintech, but the brand split needs to be intentional.

- Scanner, tracker, bet settlement, and stats should feel like an instrument panel.
- Daily Drop, onboarding, empty states, and hero moments should feel like a field guide.

That split keeps the emotional identity alive while making operational screens faster to read.

## Visual North Star

Aim for:

- less casino
- less glossy dark-gradient showcase
- more trusted analyst tool
- more premium utility
- slight editorial warmth

Mental model:

Bloomberg-lite clarity with a warmer, more curated outer shell.

## Theme System

### Color Roles

Design by semantic roles, not by raw colors.

Recommended role structure:

- `bg.app`
- `bg.surface`
- `bg.surfaceRaised`
- `bg.subtle`
- `border.subtle`
- `border.strong`
- `text.primary`
- `text.secondary`
- `text.muted`
- `text.inverse`
- `accent.brand`
- `accent.featured`
- `state.positive`
- `state.negative`
- `state.warning`
- `state.info`

### Color Behavior

Core neutrals should do most of the work.

- App background should feel stable and quiet.
- Card background should be clearly distinct from the page background.
- Raised surfaces should be used sparingly.
- Borders should separate layers without adding visual noise.
- Primary text should be high contrast.
- Secondary text should remain readable.
- Muted text should be reserved for genuinely secondary information.

### Brand Accent

Keep one restrained brand accent.

Recommended behavior:

- warm gold, wheat, parchment-adjacent tones should be featured or editorial accents
- they should not become the universal primary CTA color everywhere

Gold is best used for:

- Daily Drop
- featured chips
- promo callouts
- highlighted stats
- editorial-style selected states

### Semantic States

Semantic colors should stay predictable.

- positive = green
- negative = red
- warning = amber
- info = blue

Gold, blue, green, orange, and red should not all compete equally on the same screen.

### Accent Rules

Use color for meaning, not decoration.

- green should mean gain, edge, win, or positive delta
- red should mean loss, risk, or negative outcome
- blue should usually mean navigation, information, links, or sportsbook identity
- gold should mean featured, curated, premium, or Daily Drop

Avoid letting gold act as the default action color or letting multiple intense accents fight on the same screen.

## Surface Rules

### Limit Surface Depth

Use three main surface levels:

- app background
- section or card surface
- raised or interactive surface

Too many near-identical dark layers create blur instead of hierarchy.

### Remove Fog From Work Surfaces

For scanner, tracker, stats, and settlement cards:

- no textured overlays
- no soft haze across full cards
- no visible paper grain in dark mode
- minimal internal gradients

These surfaces should feel solid and stable.

### Save Atmosphere For High-Level Areas

Gradients and tactile warmth are appropriate in:

- page hero or header treatments
- Daily Drop modules
- onboarding
- empty states
- occasional highlight banners

They are not appropriate as the default treatment for dense data cards.

### Borders Matter

Use clear, subtle borders to separate layers.

This matters most in dark mode, where missing borders quickly turns the interface into one blob.

## Typography Rules

### Strong Text Ladder

Hierarchy should be obvious across:

- page title
- section title
- card title
- label
- helper or meta text

Avoid placing most text into the same muted middle tier.

### Numeric Readability First

For odds, stake, EV, return, bankroll, and percentages:

- use tabular numerals
- keep label and value spacing consistent
- make the value visually heavier than the label
- align repeated stat rows cleanly

### Muted Text Must Still Be Readable

Secondary information in this product is still meaningful. Muted text should not become nearly invisible.

### Uppercase Sparingly

Uppercase can work for small labels and overlines, but overuse harms scan speed in dense dark interfaces.

## Component Rules

### Bet Cards

Bet cards should feel:

- fast
- clean
- structured
- trustworthy

Rules:

- title should pop first
- metadata row should be quiet but readable
- stat rows should align consistently
- settlement buttons should feel decisive, not glowy
- expanded details should read as a clearly separated secondary section

Avoid:

- muddy gradients
- too many chip colors
- low-contrast details
- decorative shadows inside dense cards

### Buttons

Primary CTA:

- use one clear primary action treatment
- on scanner cards, the main action should be obvious immediately

Secondary CTA:

- outline or softer fill is fine, but it must still look interactive

Destructive action:

- use negative-state styling, but keep it restrained

Important note:

The current gold CTA treatment is attractive, but it reads more like a featured state than a universal action system.

### Tabs And Segmented Controls

These should feel operational, not decorative.

Rules:

- higher contrast than surrounding chrome
- stronger selected state
- clear hover and focus state
- consistent padding and height
- minimal glow

### Filters And Search

Filters and search should read as tools.

Rules:

- inputs need a clearer boundary
- filter buttons should not dissolve into the background
- selected filters should be easy to notice
- reset actions should be visually subordinate but not hidden

### Chips And Badges

Simplify badge styles.

Focus on a small set:

- sportsbook
- market type
- featured
- promo
- CLV state

Too many badge colors make the UI noisy.

### Charts

Charts should be among the cleanest parts of the product.

Rules:

- chart panels should have stable backgrounds
- labels must stay legible
- legends should be calm and clear
- gridlines should be subtle but visible
- variance bands should not muddy the chart
- chart colors should have distinct roles with adequate contrast

Charts are analytical instruments, not decorative illustrations.

## Screen Direction

### Markets / Scanner

This screen should feel like high-signal opportunity scanning.

Priority order:

- edge or value
- event and market
- line context
- action
- supporting metadata

Changes to favor:

- flatter card backgrounds
- less gradient haze
- edge as the strongest numeric signal
- simplified chip system
- clearer CTA and review actions
- filters and search that feel like operational controls

### Tracker / Open Bets / Past Bets

This screen should feel like portfolio management.

Changes to favor:

- crisp, quiet summary cards
- clear settlement certainty on bet cards
- stronger subdivision inside expanded or detail areas
- summary metrics that read as utility, not decoration

### Stats

This screen should feel like high-trust performance review.

Changes to favor:

- keep the top verdict card prominent
- improve contrast and spacing in summary cards
- clean up chart panel styling
- strengthen grouping in "Where it came from"
- raise legibility of secondary captions

### Daily Drop

This is where the brand can breathe more.

Allowed here:

- warmth
- gold accent
- editorial styling
- curated language
- special featured treatment

## Light Mode vs Dark Mode

### Recommended Stance

Light mode is the flagship. Dark mode is the same field guide at night — warm, not clinical.

Dark mode should use:
- warm-dark charcoal backgrounds (brown-tinted, not blue-gray slate)
- cleaner, more visible borders than light mode (borders do the separation work that shadows do in light)
- stronger contrast between text levels
- the same gold accent, slightly brighter to compensate for the dark background
- paper grain at a very low opacity — enough to feel warm, not enough to read as texture

Dark mode should not use:
- cool blue-gray backgrounds (e.g. `hsl(220 ...)`) — these break the warm identity
- the same shadow values as light mode — shadows disappear on dark, borders take over
- grain at 0% — invisible grain contributes nothing; keep it at ~6% opacity

### Text Hierarchy

Both modes need a clear 4-level text ladder. Collapsing everything into two levels (foreground / muted-foreground) is what makes interfaces feel flat.

- Level 1 (`text-hi` / `text-foreground`): titles, key values, odds, EV numbers
- Level 2 (`text-mid` / `text-muted-foreground`): event names, matchup context, supporting labels
- Level 3 (`text-lo`): timestamps, helper text, secondary metadata — readable but clearly subordinate
- Level 4 (`text-ghost`): placeholder text, disabled states, decorative dividers

In dark mode, the gap between Level 1 and Level 2 should be at least 35 lightness points. In light mode, at least 25 points. If the gap is smaller, hierarchy collapses.

### Preserve From The Original Light Theme

Keep:

- warmth
- tactility as a brand idea
- field-guide identity
- a curated tone

Move those mostly into:

- tone
- accent
- illustration
- featured modules
- hero surfaces

Do not push those ideas into every dense workflow card.

## Design Principles For The Overhaul

- clarity beats mood in core workflows
- meaning beats decoration
- contrast and spacing create hierarchy before color does
- one accent should lead and the others should support
- dark mode should feel clean, not foggy
- brand personality belongs at the edges, not inside every card
- numbers are the product, so numeric readability is non-negotiable

## Concrete Do / Don't Rules

### Do

- use semantic tokens
- use tabular numerals for money and odds
- create stronger border separation in dark mode
- flatten work surfaces
- keep color roles strict
- reserve gold for featured or curated moments
- make control surfaces feel clickable
- raise contrast on secondary text

### Don't

- don't use ambient gradients across every card
- don't rely on glow for emphasis
- don't let chips become a rainbow
- don't make muted text too faint
- don't use promotional color as the default CTA system
- don't try to make dark mode feel like literal paper

## Practical Rollout Plan

### Phase 1: Foundation

- define semantic design tokens
- unify typography hierarchy
- unify spacing and radii
- clean up the border system
- establish light and dark surface rules

### Phase 2: Shared Components

- buttons
- tabs
- chips
- inputs
- cards
- chart containers

### Phase 3: Core Screens

- scanner
- tracker and bets
- stats

### Phase 4: Brand Moments

- Daily Drop
- onboarding
- empty states
- promo surfaces

That order matters. Do not start by polishing hero treatments before fixing shared surfaces and controls.

## Acceptance Test

The redesign is working when:

- a user can scan a card in under a second and know what matters
- dark mode feels cleaner and more trustworthy
- the chart page feels easier to read immediately
- filters and tabs feel more operable
- fewer visual accents compete for attention
- the app still feels like EV Tracker, not generic SaaS
