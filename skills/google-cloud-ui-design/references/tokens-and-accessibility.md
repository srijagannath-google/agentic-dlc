<!-- disableFinding(LINE_OVER_80) -->

# Google Cloud Design Tokens, CSS Architecture & WCAG 2.3 Reference

This reference contains production CSS custom properties (`src/index.css`),
theme context (`ThemeProvider`), component snippets, typography and table
alignment specifications, unified surfaces, and WCAG 2.3 / HTML5 standards for
the
[Google Cloud UI Design SKILL.md](SKILL.md).

--------------------------------------------------------------------------------

## 1. Component & Runtime Snippets

### Gemini Sparkle Brand Icon (`Inline SVG`)

Use `lucide-react` (`size={16}` or `size={18}`, `strokeWidth={1.75}`) for
general UI. Use inline SVG with unique gradient IDs for the Gemini mark:

```tsx
export function GeminiSparkleIcon({ className = "w-4 h-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true" focusable="false">
      <path d="M12 2C12 7.52285 16.4772 12 22 12C16.4772 12 12 16.4772 12 22C12 16.4772 7.52285 12 2 12C7.52285 12 12 7.52285 12 2Z" fill="url(#gemini-sparkle-grad)" />
      <defs>
        <linearGradient id="gemini-sparkle-grad" x1="2" y1="2" x2="22" y2="22" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#1A73E8" /><stop offset="50%" stopColor="#7C3AED" /><stop offset="100%" stopColor="#D93025" />
        </linearGradient>
      </defs>
    </svg>
  );
}
```

### Mandatory `sonner` Toast Mount (`App.tsx`)

Mount `<Toaster />` from `sonner` once at the application root:

```tsx
import { Toaster } from "sonner";

<Toaster
  position="bottom-right"
  closeButton
  expand={false}
  toastOptions={{
    style: {
      background: "var(--g-surface)",
      color: "var(--g-ink)",
      border: "1px solid var(--g-border)",
      borderRadius: "0.75rem",
      boxShadow: "var(--shadow-2)",
      fontFamily: "var(--font-sans)",
    },
  }}
/>
```

### Navigation Rail Header (`CUSTOMER_PLACEHOLDER`)

Collapsible nav rails (`240px` expanded, `56px` collapsed) require a uniform top
row with left identity and flush-right toggle (`ml-auto shrink-0`):

```tsx
<div className="flex items-center justify-between w-full px-3 h-12 border-b border-[var(--g-border-subtle)]">
  {!isCollapsed && (
    <div className="flex items-center gap-2.5 min-w-0">
      <Layers size={18} strokeWidth={1.75} className="shrink-0 text-[var(--g-ink)]" aria-hidden="true" />
      <span className="truncate text-sm font-semibold text-[var(--g-ink)]">CUSTOMER_PLACEHOLDER</span>
    </div>
  )}
  <button
    type="button"
    onClick={() => setIsCollapsed(!isCollapsed)}
    aria-label={isCollapsed ? "Expand navigation rail" : "Collapse navigation rail"}
    className={`inline-flex h-8 w-8 items-center justify-center rounded-md text-[var(--g-ink-secondary)] hover:bg-[var(--g-surface-high)] hover:text-[var(--g-ink)] shrink-0 ${isCollapsed ? "mx-auto" : "ml-auto"}`}
  >
    {isCollapsed ? <PanelLeftOpen size={16} strokeWidth={1.75} /> : <PanelLeftClose size={16} strokeWidth={1.75} />}
  </button>
</div>
```

### Demo Port Standard (`package.json`)

Document dedicated ports (`3100`-`8999`) and include a `demo` script:

```json
{
  "scripts": {
    "dev": "vite",
    "demo": "bunx --bun vite --port 4729 --host",
    "build": "tsc -b && vite build"
  }
}
```

--------------------------------------------------------------------------------

## 2. Color System & `ThemeProvider` (`defaultTheme="system"`)

Always default theme to `"system"` with live OS synchronization:

```tsx
// src/providers/theme-provider.tsx
import React, { createContext, useContext, useEffect, useState } from "react";

type Theme = "system" | "light" | "dark";
type ThemeContextType = { theme: Theme; setTheme: (theme: Theme) => void; };

const ThemeContext = createContext<ThemeContextType>({ theme: "system", setTheme: () => null });

export function ThemeProvider({ children, defaultTheme = "system", storageKey = "ui-theme-mode" }: {
  children: React.ReactNode; defaultTheme?: Theme; storageKey?: string;
}) {
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem(storageKey) as Theme) || defaultTheme);

  useEffect(() => {
    const root = document.documentElement;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const isDark = theme === "dark" || (theme === "system" && media.matches);
      root.classList.toggle("dark", isDark);
    };
    apply();
    localStorage.setItem(storageKey, theme);
    if (theme === "system") {
      media.addEventListener("change", apply);
      return () => media.removeEventListener("change", apply);
    }
  }, [theme, storageKey]);

  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>;
}

export const useTheme = () => useContext(ThemeContext);
```

### Neutral Surface & Ink Tokens

| Token               | Light Hex /      | Dark Hex / OKLCH | Role & Usage     |
:                     : OKLCH            :                  :                  :
| :------------------ | :--------------- | :--------------- | :--------------- |
| `--g-surface`       | `#FFFFFF` /      | `#1E1F20` /      | Primary unified  |
:                     : `oklch(100% 0    : `oklch(23% 0.003 : surface, main    :
:                     : 0)`              : 240)`            : sheet            :
| `--g-bg`            | `#F8F9FA` /      | `#131314` /      | App shell canvas |
:                     : `oklch(98% 0.003 : `oklch(18% 0.002 : behind surfaces  :
:                     : 240)`            : 240)`            :                  :
| `--g-surface-dim`   | `#F1F3F4` /      | `#18191A` /      | Sidebars, table  |
:                     : `oklch(96% 0.003 : `oklch(20% 0.002 : headers, code    :
:                     : 240)`            : 240)`            : wells            :
| `--g-surface-high`  | `#E8EAED` /      | `#282A2C` /      | Hover states,    |
:                     : `oklch(93% 0.004 : `oklch(27% 0.003 : active pills,    :
:                     : 240)`            : 240)`            : modal headers    :
| `--g-border`        | `#DADCE0` /      | `#3C4043` /      | Outer container  |
:                     : `oklch(89% 0.004 : `oklch(35% 0.004 : borders, table   :
:                     : 240)`            : 240)`            : bounds           :
| `--g-border-subtle` | `#E8EAED` /      | `#282A2C` /      | Internal `1px`   |
:                     : `oklch(93% 0.004 : `oklch(27% 0.003 : hairlines        :
:                     : 240)`            : 240)`            : (`divide-x`/`y`) :
| `--g-border-strong` | `#BDC1C6` /      | `#5F6368` /      | Form controls at |
:                     : `oklch(80% 0.004 : `oklch(50% 0.008 : rest (`>= 3\:1`  :
:                     : 240)`            : 240)`            : contrast)        :
| `--g-ink`           | `#202124` /      | `#E8EAED` /      | Primary          |
:                     : `oklch(24% 0.005 : `oklch(93% 0.004 : headings, values :
:                     : 240)`            : 240)`            : (`15.8\:1` /     :
:                     :                  :                  : `14.6\:1`)       :
| `--g-ink-secondary` | `#5F6368` /      | `#9AA0A6` /      | Field labels,    |
:                     : `oklch(50% 0.008 : `oklch(68% 0.006 : timestamps       :
:                     : 240)`            : 240)`            : (`5.9\:1` /      :
:                     :                  :                  : `6.8\:1`)        :
| `--g-ink-muted`     | `#80868B` /      | `#5F6368` /      | Disabled         |
:                     : `oklch(62% 0.007 : `oklch(50% 0.008 : controls only    :
:                     : 240)`            : 240)`            :                  :

### Semantic Accent & Status Tokens

| Role            | Token        | Light (`Hex` /   | Dark (`Hex` / `Soft` /  |
:                 :              : `Soft` / `Text`) : `Text`)                 :
| :-------------- | :----------- | :--------------- | :---------------------- |
| Primary Action  | `--g-blue`   | `#1A73E8` /      | `#8AB4F8` / `#172B4D` / |
:                 :              : `#E8F0FE` /      : `#8AB4F8`               :
:                 :              : `#1557B0`        :                         :
| Critical Error  | `--g-red`    | `#D93025` /      | `#F28B82` / `#3C1917` / |
:                 :              : `#FCE8E6` /      : `#F28B82`               :
:                 :              : `#C5221F`        :                         :
| Healthy Success | `--g-green`  | `#1E8E3E` /      | `#81C995` / `#132A1C` / |
:                 :              : `#E6F4EA` /      : `#81C995`               :
:                 :              : `#137333`        :                         :
| Warning Notice  | `--g-amber`  | `#F9AB00` /      | `#FDD663` / `#332607` / |
:                 :              : `#FEF7E0` /      : `#FDD663`               :
:                 :              : `#B06000`        :                         :
| Gemini AI       | `--g-purple` | `#7C3AED` /      | `#C084FC` / `#2B1447` / |
:                 :              : `#F3E8FF` /      : `#D8B4FE`               :
:                 :              : `#6D28D9`        :                         :

> **Notice on Amber Contrast**: Pure `#F9AB00` on white fails WCAG AA text
> (`1.95:1`). Use `--g-amber-text` (`#B06000`, `4.7:1`) for light mode warning
> text, reserving `#F9AB00` for icons and status dots.

--------------------------------------------------------------------------------

## 3. Production CSS Custom Properties Block (`src/index.css`)

```css
@import "tailwindcss";
@custom-variant dark (&:is(.dark *));

:root {
  /* Canonical Neutral Tokens in Hex & OKLCH */
  --g-bg: #F8F9FA; /* oklch(98% 0.003 240) */
  --g-surface: #FFFFFF; /* oklch(100% 0 0) */
  --g-surface-dim: #F1F3F4; /* oklch(96% 0.003 240) */
  --g-surface-high: #E8EAED; /* oklch(93% 0.004 240) */
  --g-ink: #202124; /* oklch(24% 0.005 240) */
  --g-ink-secondary: #5F6368; /* oklch(50% 0.008 240) */
  --g-ink-muted: #80868B; /* oklch(62% 0.007 240) */
  --g-border: #DADCE0; /* oklch(89% 0.004 240) */
  --g-border-subtle: #E8EAED;
  --g-border-strong: #BDC1C6;
  --g-base: var(--g-surface); --g-canvas: var(--g-bg); --g-surface-low: var(--g-surface-dim);
  --g-text-primary: var(--g-ink); --g-text-secondary: var(--g-ink-secondary); --g-text-disabled: var(--g-ink-muted);
  /* Status Tokens */
  --g-blue: #1A73E8; --g-blue-hover: #1557B0; --g-blue-text: #1557B0; --g-blue-soft: #E8F0FE; --g-blue-subtle: var(--g-blue-soft); --g-blue-border: #D2E3FC;
  --g-red: #D93025; --g-red-text: #C5221F; --g-red-soft: #FCE8E6; --g-red-subtle: var(--g-red-soft); --g-red-border: #FAD2CF;
  --g-green: #1E8E3E; --g-green-text: #137333; --g-green-soft: #E6F4EA; --g-green-subtle: var(--g-green-soft); --g-green-border: #CEEAD6;
  --g-amber: #F9AB00; --g-amber-text: #B06000; --g-amber-soft: #FEF7E0; --g-amber-subtle: var(--g-amber-soft); --g-amber-border: #FDE293;
  --g-purple: #7C3AED; --g-purple-text: #6D28D9; --g-purple-soft: #F3E8FF; --g-purple-subtle: var(--g-purple-soft); --g-purple-border: #E9D5FF;
  /* Elevation & ShadCN Mappings */
  --shadow-1: 0 1px 2px 0 rgba(60,64,67,0.15), 0 1px 3px 1px rgba(60,64,67,0.08);
  --shadow-2: 0 4px 8px 3px rgba(60,64,67,0.12), 0 1px 3px 0 rgba(60,64,67,0.20);
  --background: var(--g-bg); --foreground: var(--g-ink);
  --card: var(--g-surface); --card-foreground: var(--g-ink);
  --popover: var(--g-surface); --popover-foreground: var(--g-ink);
  --primary: var(--g-blue); --primary-foreground: #FFFFFF;
  --secondary: var(--g-surface-dim); --secondary-foreground: var(--g-ink);
  --muted: var(--g-surface-dim); --muted-foreground: var(--g-ink-secondary);
  --accent: var(--g-surface-high); --accent-foreground: var(--g-ink);
  --destructive: var(--g-red); --destructive-foreground: #FFFFFF;
  --border: var(--g-border); --input: var(--g-border-strong); --ring: var(--g-blue);
  --radius: 0.5rem;
}

.dark {
  /* Neutral Tokens in Hex & OKLCH */
  --g-bg: #131314; /* oklch(18% 0.002 240) */
  --g-surface: #1E1F20; /* oklch(23% 0.003 240) */
  --g-surface-dim: #18191A; /* oklch(20% 0.002 240) */
  --g-surface-high: #282A2C; /* oklch(27% 0.003 240) */
  --g-ink: #E8EAED; /* oklch(93% 0.004 240) */
  --g-ink-secondary: #9AA0A6; /* oklch(68% 0.006 240) */
  --g-ink-muted: #5F6368; /* oklch(50% 0.008 240) */
  --g-border: #3C4043; /* oklch(35% 0.004 240) */
  --g-border-subtle: #282A2C;
  --g-border-strong: #5F6368;
  --g-base: #131314; --g-canvas: #18191A; --g-surface-low: var(--g-surface);
  --g-text-primary: var(--g-ink); --g-text-secondary: var(--g-ink-secondary); --g-text-disabled: var(--g-ink-muted);
  --g-blue: #8AB4F8; --g-blue-hover: #AECBFA; --g-blue-text: #8AB4F8; --g-blue-soft: #172B4D; --g-blue-subtle: var(--g-blue-soft); --g-blue-border: #1E3A5F;
  --g-red: #F28B82; --g-red-text: #F28B82; --g-red-soft: #3C1917; --g-red-subtle: var(--g-red-soft); --g-red-border: #5C2421;
  --g-green: #81C995; --g-green-text: #81C995; --g-green-soft: #132A1C; --g-green-subtle: var(--g-green-soft); --g-green-border: #1E4620;
  --g-amber: #FDD663; --g-amber-text: #FDD663; --g-amber-soft: #332607; --g-amber-subtle: var(--g-amber-soft); --g-amber-border: #523E0A;
  --g-purple: #C084FC; --g-purple-text: #D8B4FE; --g-purple-soft: #2B1447; --g-purple-subtle: var(--g-purple-soft); --g-purple-border: #462170;
  --shadow-1: 0 1px 3px 0 rgba(0,0,0,0.45);
  --shadow-2: 0 6px 16px 0 rgba(0,0,0,0.60);
  --background: var(--g-bg); --foreground: var(--g-ink);
  --card: var(--g-surface); --card-foreground: var(--g-ink);
  --popover: var(--g-surface-high); --popover-foreground: var(--g-ink);
  --primary: var(--g-blue); --primary-foreground: #131314;
  --secondary: var(--g-surface-high); --secondary-foreground: var(--g-ink);
  --muted: var(--g-surface-dim); --muted-foreground: var(--g-ink-secondary);
  --accent: var(--g-surface-high); --accent-foreground: var(--g-ink);
  --destructive: var(--g-red); --destructive-foreground: #131314;
  --border: var(--g-border); --input: var(--g-border-strong); --ring: var(--g-blue);
}

@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-destructive-foreground: var(--destructive-foreground);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);
  --font-sans: "Google Sans Text", "Inter", sans-serif;
  --font-display: "Google Sans", "Inter", sans-serif;
  --font-mono: "JetBrains Mono", monospace;
}

@layer base {
  button:not(:disabled),
  [role="button"]:not(:disabled),
  a[href],
  select:not(:disabled),
  summary,
  input[type="checkbox"]:not(:disabled),
  input[type="radio"]:not(:disabled),
  input[type="range"]:not(:disabled) {
    cursor: pointer;
  }

  select {
    appearance: none;
    -webkit-appearance: none;
    padding-left: 0.75rem;
    padding-right: 2.25rem;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%235F6368' stroke-width='1.75' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
    background-position: right 0.75rem center;
    background-repeat: no-repeat;
    background-size: 16px 16px;
  }

  .dark select {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%239AA0A6' stroke-width='1.75' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
  }
}

@keyframes g-fade-slide-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.animate-g-fade-in { animation: g-fade-slide-in 180ms cubic-bezier(0.16, 1, 0.3, 1) forwards; }

.dark .maplibre-google-tiles canvas,
.dark .google-raster-dark .maplibregl-canvas {
  filter: invert(92%) hue-rotate(180deg) brightness(94%) contrast(92%) saturate(85%);
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

--------------------------------------------------------------------------------

## 4. Typography, Scannable Hierarchy & Numeric Discipline

### Asset Loading (`index.html`)

```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Google+Sans+Text:wght@400;500;600&family=Google+Sans:wght@500;600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet" />
```

### Type Scale & Table Discipline

Role                  | Font Family      | Size / Leading                              | Weight      | Rules
:-------------------- | :--------------- | :------------------------------------------ | :---------- | :----
Display (`Persuade`)  | `--font-display` | `clamp(2.25rem, 4vw+1rem, 3.5rem)` / `1.12` | `600`/`700` | `20ch-30ch`, `text-wrap: balance`
H1 (Page Title)       | `--font-display` | `1.5rem` (`24px`) / `1.25`                  | `600`       | Single `<h1>` per route
H2 (Section Header)   | `--font-display` | `1.125rem` (`18px`) / `1.3`                 | `600`       | Anchored to `<section aria-labelledby>`
H3 (Panel Title)      | `--font-sans`    | `0.9375rem` (`15px`) / `1.4`                | `600`       | Single-line `.truncate` in headers
Body (`Read` / Forms) | `--font-sans`    | `1rem` (`16px`) / `1.6`                     | `400`       | Strict `60ch-75ch` measure
Dense UI / Cell       | `--font-sans`    | `0.8125rem` (`13px`) / `1.4`                | `400`/`500` | Tables, filter bars, sidebar nav
KPI Value             | `--font-display` | `1.5rem`-`1.875rem` / `1.15`                | `600`       | `tabular-nums` + monochrome `--g-ink`
Micro / Header        | `--font-sans`    | `0.75rem` (`12px`) / `1.35`                 | `600`       | Table `<th>`, shortcut hints (`⌘K`)
Code / ID             | `--font-mono`    | `0.8125rem` (`13px`) / `1.45`               | `400`/`500` | Project IDs, SHAs, IP addresses

Data tables must pair `text-left` for resource names/IDs with `text-right` for
monochrome numerical metrics (`tabular-nums`) and action menus.

--------------------------------------------------------------------------------

## 5. Spatial Grid, Unified Surfaces & Proximity

### Spatial Units & Unified Surfaces (Ban "Card Soup")

| Token           | Value  | Standard Architectural Role                      |
| :-------------- | :----- | :----------------------------------------------- |
| `gap-1` / `p-1` | `4px`  | Badge icon gaps, inline code padding             |
| `gap-2` / `p-2` | `8px`  | Button icon gaps, minimum distance next to       |
:                 :        : destructive controls                             :
| `gap-3` / `p-3` | `12px` | Form field label-to-input vertical spacing       |
| `gap-4` / `p-4` | `16px` | Standard panel padding, dense grid gap           |
:                 :        : (`Operate`)                                      :
| `gap-5` / `p-5` | `20px` | Unified strip/panel padding on desktop           |
| `gap-6` / `p-6` | `24px` | Canvas padding, major section separation, drawer |
:                 :        : body padding                                     :

Organize content on a **single unified surface** (`bg-[var(--g-surface)]`) using
internal `1px` hairlines (`divide-x` /
`divide-y divide-[var(--g-border-subtle)]`) and semantic `<dl>` key-value grids
rather than nested sub-card boxes:

```tsx
<div className="rounded-xl border border-[var(--g-border)] bg-[var(--g-surface)] divide-y divide-[var(--g-border-subtle)]">
  <section className="p-5">
    <dl className="grid grid-cols-1 sm:grid-cols-3 gap-6">
      <div>
        <dt className="text-xs font-medium text-[var(--g-ink-secondary)]">Resource</dt>
        <dd className="mt-1 font-mono text-xs text-[var(--g-ink)]">us-west3-a/cluster-prod</dd>
      </div>
      <div>
        <dt className="text-xs font-medium text-[var(--g-ink-secondary)]">Operator</dt>
        <dd className="mt-1 text-sm font-medium text-[var(--g-ink)]">SRE On-Call</dd>
      </div>
      <div>
        <dt className="text-xs font-medium text-[var(--g-ink-secondary)]">Blast Radius</dt>
        <dd className="mt-1 text-sm text-[var(--g-ink)]">3 downstream services</dd>
      </div>
    </dl>
  </section>
</div>
```

--------------------------------------------------------------------------------

## 6. Mandatory WCAG 2.3 Accessibility & Semantic HTML5 Architecture

### 1. Luminance & Contrast Minimums

| Element Category   | WCAG Ratio      | APCA Contrast | Implementation Rule   |
| :----------------- | :-------------- | :------------ | :-------------------- |
| Body Copy (`<      | `>= 4.5:1` (AA) | `Lc >= 75`    | Use `--g-ink`         |
: 24px`)             :                 :               : (`15.8\:1` Light,     :
:                    :                 :               : `14.6\:1` Dark)       :
| Labels / Table     | `>= 4.5:1`      | `Lc >= 60`    | Use                   |
: Cells              :                 :               : `--g-ink-secondary`   :
:                    :                 :               : (`5.9\:1` / `6.8\:1`) :
| Control Boundaries | `>= 3:1`        | `Lc >= 30`    | Inputs use            |
:                    :                 :               : `--g-border-strong`   :
:                    :                 :               : (`#BDC1C6`/`#5F6368`) :

Never apply `opacity < 1` to text containers; use explicit foreground tokens.

### 2. Targets, Affordance & Destructive Guards

-   **Target Sizes**: `24x24px` minimum clickable floor; `32px` (`h-8`) desktop
    compact; `36px` (`h-9`) form inputs/buttons; `44x44px` on touch viewports.
-   **Pointer Cursor**: All interactive elements require `cursor: pointer`.
-   **Symmetrical Select Padding**: `12px` left text padding, `12px` right
    caret.
-   **Destructive Guard**: Minimum `8px` (`gap-2`) non-interactive buffer
    between destructive actions and primary/cancel buttons. Cancel on left,
    primary on right.

### 3. Focus, Skip Links & Single-Pointer Alternatives

-   **Focus Ring**: `2px solid var(--g-blue)` with `2px` offset
    (`focus-visible:ring-2`).
-   **Skip Link**: Top of `<body>` must feature a skip link targeting
    `#main-content`.
-   **Single-Pointer Drag Alternatives**: Split panes must support keyboard
    arrow keys (`ResizableHandle`), a double-click reset to `50/50`, and never
    crowd the top app bar with ratio buttons. GIS maps require `+`/`-` buttons,
    North `0°` reset, and fit-bounds triggers.

### 4. Semantic HTML5 Element Mandate

| UI Architectural Role | Mandatory HTML5 Element  | Banned Antipattern        |
| :-------------------- | :----------------------- | :------------------------ |
| Top Application Bar   | `<header>`               | `<div class="header">`    |
| Primary Navigation    | `<nav aria-label="...">` | Unlabeled `<div>` lists   |
| Workspace Canvas      | `<main                   | Generic `<div>`           |
:                       : id="main-content">`      : containers                :
| Content Grouping      | `<section                | Anonymous `<div>`         |
:                       : aria-labelledby="...">`  : wrappers                  :
| Feed / Audit Card     | `<article>`              | Generic `<div>` for items |
| Inspector Panel       | `<aside                  | Unlabeled side `<div>`    |
:                       : aria-label="...">`       :                           :
| Key-Value Pairs       | `<dl>`, `<dt>`, `<dd>`   | Nested bordered card soup |
| Action Trigger        | `<button type="button">` | `<div onClick>`, `<a      |
:                       :                          : href="#">`                :
| Route Navigation      | `<a href="...">`         | `<button                  |
:                       :                          : onClick={navigate}>`      :
| Modal / Drawer        | `<dialog>` / Radix       | Non-modal un-trapped      |
:                       : Dialog                   : `<div>`                   :
| Data Grid             | `<table>`, `<thead>`,    | Flex/grid `<div>` rows    |
:                       : `<tbody>`, `<th>`        :                           :
