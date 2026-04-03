/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/lib/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        // Surface tokens
        "surface-card": "hsl(var(--surface-card))",
        "surface-elevated": "hsl(var(--surface-elevated))",
        "surface-overlay": "hsl(var(--surface-overlay))",
        // Semantic state colors
        "color-profit": "hsl(var(--color-profit))",
        "color-profit-fg": "hsl(var(--color-profit-fg))",
        "color-profit-subtle": "hsl(var(--color-profit-subtle))",
        "color-loss": "hsl(var(--color-loss))",
        "color-loss-fg": "hsl(var(--color-loss-fg))",
        "color-loss-subtle": "hsl(var(--color-loss-subtle))",
        "color-pending": "hsl(var(--color-pending))",
        "color-pending-fg": "hsl(var(--color-pending-fg))",
        "color-pending-subtle": "hsl(var(--color-pending-subtle))",
        "color-neutral": "hsl(var(--color-neutral))",
        "color-neutral-fg": "hsl(var(--color-neutral-fg))",
        "color-neutral-subtle": "hsl(var(--color-neutral-subtle))",
        // EV tiers
        "ev-low": "hsl(var(--color-ev-low))",
        "ev-mid": "hsl(var(--color-ev-mid))",
        "ev-high": "hsl(var(--color-ev-high))",
        "ev-elite": "hsl(var(--color-ev-elite))",
        // Bonus
        "color-bonus": "hsl(var(--color-bonus))",
        // Legacy aliases (deprecated, use color-* tokens)
        profit: "hsl(var(--profit))",
        loss: "hsl(var(--loss))",
        pending: "hsl(var(--pending))",
        // Sportsbook brand colors (authentic)
        draftkings: "#4CBB17",
        fanduel: "#0E7ACA",
        betmgm: "#C5A562",
        caesars: "#C49A6C",
        espnbet: "#ED174C",
        fanatics: "#0047BB",
        hardrock: "#FDB913",
        bet365: "#00843D",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      transitionDuration: {
        fast: "var(--duration-fast)",
        base: "var(--duration-base)",
        slow: "var(--duration-slow)",
      },
      transitionTimingFunction: {
        standard: "var(--easing-standard)",
      },
    },
  },
  plugins: [],
}
