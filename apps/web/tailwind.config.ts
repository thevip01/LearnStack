import type { Config } from "tailwindcss";

/**
 * Every colour is an rgb triplet in a CSS custom property so that a subject's
 * ThemeSpec can repaint the workspace at runtime (see src/lib/theme.ts) while
 * Tailwind opacity modifiers such as `bg-accent/10` keep working.
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        canvas: "rgb(var(--os-canvas) / <alpha-value>)",
        surface: "rgb(var(--os-surface) / <alpha-value>)",
        raised: "rgb(var(--os-raised) / <alpha-value>)",
        line: "rgb(var(--os-line) / <alpha-value>)",
        "line-strong": "rgb(var(--os-line-strong) / <alpha-value>)",
        ink: "rgb(var(--os-ink) / <alpha-value>)",
        muted: "rgb(var(--os-muted) / <alpha-value>)",
        faint: "rgb(var(--os-faint) / <alpha-value>)",
        accent: "rgb(var(--os-accent) / <alpha-value>)",
        "accent-soft": "rgb(var(--os-accent-soft) / <alpha-value>)",
        ok: "rgb(var(--os-ok) / <alpha-value>)",
        warn: "rgb(var(--os-warn) / <alpha-value>)",
        danger: "rgb(var(--os-danger) / <alpha-value>)",
        info: "rgb(var(--os-info) / <alpha-value>)",
      },
      fontFamily: {
        sans: ["var(--os-font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--os-font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      spacing: {
        // Density comes from the ThemeSpec; panels use `p-pad` instead of a literal.
        pad: "var(--os-pad)",
        "pad-sm": "var(--os-pad-sm)",
      },
      borderRadius: {
        panel: "0.625rem",
      },
      boxShadow: {
        panel: "0 1px 0 0 rgb(var(--os-line) / 0.6), 0 8px 24px -16px rgb(0 0 0 / 0.8)",
      },
      keyframes: {
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "slide-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: { from: { backgroundPosition: "200% 0" }, to: { backgroundPosition: "-200% 0" } },
      },
      animation: {
        "fade-in": "fade-in 120ms ease-out",
        "slide-up": "slide-up 140ms ease-out",
        shimmer: "shimmer 1.6s linear infinite",
      },
    },
  },
  plugins: [],
};

export default config;
