# Google Cloud UI Design System & Enterprise Frontend Standards (`google-cloud-ui-design`)

Applies to **Stage 2** (`specs/application_spec.md` §4), **Stage 4A** (`design/solution_design.md` §3),
**Stage 4B** (`test/test_plan.md` & `test/test_cases.json`), **Stage 5** (`06-coding-agent` building `src/ui/`),
and **Stage 6** (`07-test-runner-and-healer`). Full layout blueprints, complete React/Next.js + ShadCN UI
implementations, and visual reference assets live in `<PLUGIN>/skills/google-cloud-ui-design/SKILL.md` and
`<PLUGIN>/skills/google-cloud-ui-design/references/*.md`.

User design references in `resources/design_references/` or explicit Gate 1 instructions take precedence; record
any override in `specs/application_spec.md` §4.1.

---

## 1. Surface Mode Selection (`impeccable` Framework) & Reference Layout Archetypes

Every UI surface (`specs/application_spec.md` §4.1 and `design/solution_design.md` §3.1) **must declare its
primary Surface Mode** and **Reference Layout Archetype** before authoring components:

| Surface Mode | Primary User Goal | Visual Priority & Tonal Budget | Reference Layout Archetypes (`<PLUGIN>/skills/google-cloud-ui-design/references/`) |
| :-- | :-- | :-- | :-- |
| **`Operate`** | Complete operational tasks rapidly and accurately without visual friction | Scannable hierarchy, compact density (`36px` controls, `40px–48px` table rows), keyboard shortcuts (`⌘K`), instant status clarity, zero decorative bloat | 1. **Admin / FinOps Operations Dashboard** (`references/admin-dashboard.md`)<br>2. **Master-Detail Split-Screen Operations Queue** (`references/master-detail-workspace.md`)<br>3. **Full-Viewport GIS Map & Telemetry Stage** (`references/gis-map-telemetry.md`)<br>4. **50/50 Split-View Document & Compliance Auditor** (`references/document-auditor.md`)<br>6. **2-Zone Gemini Enterprise Agent & HITL Workspace** (`references/ai-agent-workspace.md`)<br>7. **Declarative `A2UI v0.9` Agent Surface** (`references/gemini-enterprise-a2ui.md`) |
| **`Read`** | Absorb complex policy, audit evidence, or structured documentation with low fatigue | Focused reading measure (`60ch–75ch` / `720px–840px`), generous line height (`1.5–1.65`), calm background (`#F8F9FA` / `#131314`) | **50/50 Split-View Document & Compliance Auditor** (`references/document-auditor.md`) or focused step-by-step intake form (`max-w-3xl`) |
| **`Persuade`** | Understand platform value and convert with confidence | Clear focal point, `Google Sans` display headlines, structured proof, decisive primary action button | 5. **Enterprise Solution Landing Page** (`references/marketing-landing.md`) |
| **`Express`** | Experience brand differentiation and executive narrative | Choreographed motion (`cubic-bezier(0.2, 0, 0, 1)`), asymmetric focal composition | Executive overview / Hero showcase (`references/marketing-landing.md`) |

> **Never mix modes on the same viewport.** An **`Operate`** workspace must never have a marketing hero banner
> at the top; a **`Persuade`** landing page must never dump raw multi-axis operational telemetry into the hero fold.

---

## 2. Anti-Slop Craft Floor (8 Mandatory Bans)

1. **No AI Gradient Slop:** Never apply purple-to-blue/pink linear gradients (`linear-gradient(135deg, #6366f1, #a855f7)`) to primary buttons, cards, or text headings (`background-clip: text`). Primary actions use solid `--g-blue` (`#1A73E8` Light / `#8AB4F8` Dark).
2. **No Glowing Neon Dark-Mode Halos:** Never use `box-shadow: 0 0 20px rgba(26, 115, 232, 0.4)` in dark mode. Dark mode elevation uses surface luminance steps (`#131314` → `#1E1F20` → `#282A2C`) and `1px solid` borders (`#3C4043`).
3. **No Decorative Glassmorphism on Data Surfaces:** Never apply `backdrop-filter: blur()` to data tables, forms, or standard cards. Reserve translucent surfaces strictly for floating map HUD controls (`references/gis-map-telemetry.md`) or modal backdrops.
4. **No "Card Soup" or Nested Scrollbars (Unified Surface Rule):**
   - Never place a scrollable box inside another scrollable box within the same pane. Each split pane owns at most **one** vertical scroll container (`overflow-y-auto`).
   - Never wrap every single metadata field (`Applicant`, `Status`, `Created At`, `Amount`) or KPI stat in its own individual bordered box (`border rounded-lg p-3`) inside a detail panel or dashboard strip. Render a **single unified surface** (`rounded-xl border border-[var(--g-border)] bg-[var(--g-surface)]`) divided by `1px solid var(--g-border-subtle)` hairlines (`divide-x`, `divide-y`, or `<Separator />`) and semantic `<dl>` (`<dt>` / `<dd>`) description lists.
5. **No Decorative Eyebrows, Arbitrary Section Numbers, or `<Badge>` Clutter:**
   - Never stack uppercase micro-eyebrows above section titles unless the eyebrow carries live interactive state.
   - Never prefix static panels with `01 / 02 / 03` unless the user is in a sequential multi-step wizard.
   - Reserve `<Badge>` strictly for a **single Status column** in a data table or a **single Severity state** on an audit finding. Never attach pills to navigation tabs, card headers, KPI titles, or sidebar items.
6. **No Rainbow Metric or Icon Coloring:** Never color KPI values green, blue, amber, and purple across a 4-stat strip, and never tint routine navigation/metadata icons in rainbow brand colors. All KPI numbers and `lucide-react` icons remain monochrome (`--g-ink` / `--g-ink-secondary`); semantic color belongs strictly on status badges or delta trend pills (`+4.2%`).
7. **No Un-Animated Toasts or Abrupt Overlay Unmounts:** Never hand-roll fixed-div notifications or abruptly unmount drawers/modals. Use `sonner` (`<Toaster />`) for non-blocking feedback and ShadCN `Sheet` / `Dialog` with symmetric open/close transitions.
8. **No Raw JSON, Internal Identifiers, or Model SKU Strings in UI Chrome:** Never render raw JSON payloads, database column names, or raw model version strings (`gemini-2.5-flash`, `gemini-1.5-pro`) in user-facing panels. Label AI surfaces `"Gemini"` or `"Ask Gemini"` with verifiable source citation chips.

---

## 3. Google Material 3 / Cloud Console Token System (`--g-*`) & Theme Provider

Every application must define the canonical `--g-*` CSS custom properties in `:root` (Light Mode) and `.dark` (Dark Mode) in its global stylesheet (`globals.css` / `styles.css`), default to `defaultTheme="system"` via `window.matchMedia("(prefers-color-scheme: dark)")`, and expose a 3-way `System | Light | Dark` theme switcher:

```css
:root {
  --g-bg: #F8F9FA;
  --g-surface: #FFFFFF;
  --g-surface-dim: #F1F3F4;
  --g-surface-high: #E8EAED;
  --g-ink: #202124;
  --g-ink-secondary: #5F6368;
  --g-ink-muted: #80868B;
  --g-border: #DADCE0;
  --g-border-subtle: #E8EAED;
  --g-border-strong: #BDC1C6;

  --g-blue: #1A73E8;
  --g-blue-hover: #1557B0;
  --g-blue-tint: #E8F0FE;
  --g-red: #D93025;
  --g-red-tint: #FCE8E6;
  --g-green: #1E8E3E;
  --g-green-tint: #E6F4EA;
  --g-amber: #F9AB00;
  --g-amber-text: #B06000; /* 4.7:1 WCAG AA contrast on light backgrounds */
  --g-amber-tint: #FEF7E0;
  --g-purple: #9334E6;
  --g-purple-tint: #F3E8FD;

  --font-display: 'Google Sans', 'Inter', system-ui, sans-serif;
  --font-sans: 'Google Sans Text', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono: 'JetBrains Mono', 'Roboto Mono', monospace;
}

.dark {
  --g-bg: #131314;
  --g-surface: #1E1F20;
  --g-surface-dim: #18191A;
  --g-surface-high: #282A2C;
  --g-ink: #E8EAED;
  --g-ink-secondary: #9AA0A6;
  --g-ink-muted: #5F6368;
  --g-border: #3C4043;
  --g-border-subtle: #282A2C;
  --g-border-strong: #5F6368;

  --g-blue: #8AB4F8;
  --g-blue-hover: #AECBFA;
  --g-blue-tint: rgba(138, 180, 248, 0.14);
  --g-red: #F28B82;
  --g-red-tint: rgba(242, 139, 130, 0.14);
  --g-green: #81C995;
  --g-green-tint: rgba(129, 201, 149, 0.14);
  --g-amber: #FDD663;
  --g-amber-text: #FDD663;
  --g-amber-tint: rgba(253, 214, 99, 0.14);
  --g-purple: #C58AF9;
  --g-purple-tint: rgba(197, 138, 249, 0.14);
}
```

- **60-30-10 Tonal Balance:** 60% neutral canvas (`--g-bg` / `--g-surface`), 30% structural elevation & `1px` borders (`--g-surface-dim` / `--g-border`), ≤10% semantic status accents (`--g-blue`, `--g-green`, `--g-amber`, `--g-red`, `--g-purple`).
- **Base Interactive & Select Reset (`@layer base`):** All enabled interactive controls (`button`, `[role="button"]`, `[role="tab"]`, `a[href]`, `select`, `summary`) must set `cursor: pointer`. Native `<select>` elements must declare symmetrical `12px` (`0.75rem`) right padding (`background-position: right 0.75rem center; padding-right: 2.25rem;`).

---

## 4. Component Architecture, Navigation Rail & Spatial Discipline

1. **ShadCN UI + Radix Primitives (for React / Next.js / TypeScript target stacks):**
   - Use ShadCN UI (`@radix-ui/*`) + Tailwind CSS + `lucide-react` (`size={16}` or `size={18}`, `strokeWidth={1.75}`) + `sonner` (`<Toaster />`) + `@tanstack/react-table` + `react-resizable-panels`.
   - **Never hand-roll modals, dropdowns, tabs, command palettes, or split panes** with raw `<div onClick>` when building React/Next.js applications.
2. **Collapsible Left Navigation Rail (`240px–256px` expanded / `56px` collapsed):**
   - Header must be a single horizontal flex row (`flex items-center justify-between w-full px-3 h-12 border-b border-[var(--g-border-subtle)]`) with left brand icon + application/organization title (`truncate`) and a flush-right collapse button (`ml-auto shrink-0`).
   - Top header bars are capped to identity, global search (`⌘K`), role/persona selector, theme toggle (`System | Light | Dark`), and 1–2 primary action buttons. Move secondary utilities (`Reset Demo`, `Language`) to the sidebar footer.
3. **Interactive 50/50 Split Panes (`ResizablePanelGroup`):**
   - Side-by-side workspaces (Master-Detail queues, Document Auditors) open at an even `50% / 50%` split (`defaultSize={50}`) separated by a draggable `ResizableHandle withHandle` (`cursor: col-resize`, `aria-label="Resize panels"`, double-click to reset to `50/50`). Never clutter the top bar with `35/65` or `50/50` ratio buttons.
4. **Numeric & Typographic Discipline (`tabular-nums`):**
   - Apply `font-variant-numeric: tabular-nums` (`tabular-nums`) to every KPI value, currency figure, percentage, badge count, timer, and table cell. Right-align all numeric/currency table columns (`text-right font-mono tabular-nums`).
5. **Complete 4-State Coverage:**
   - Every data view and async panel must implement: (1) **Loading** (`Skeleton` matching exact row/panel geometry — never a blocking page spinner), (2) **Empty** (`lucide-react` icon + plain explanation + recovery action button), (3) **Error** (human-readable banner + inline `Retry` button + expandable `<details>` diagnostics), and (4) **Populated / Extreme** (`truncate` + `Tooltip`, `tabular-nums`, sticky table headers).
6. **Semantic HTML5 Landmarks & WCAG 2.1 AA Accessibility:**
   - First focusable element in `<body>` must be `<a href="#main-content" class="sr-only focus:not-sr-only ...">Skip to main content</a>`.
   - Use semantic HTML5 landmarks (`<header>`, `<nav aria-label="...">`, `<main id="main-content">`, `<section>`, `<aside>`, `<dl>`/`<dt>`/`<dd>`, `<footer>`, `<table>`/`<th scope="col">`).
   - Action-oriented `[Verb] + [Object]` button labels (`"Approve Application"`, `"Export Audit CSV"`). Keep at least `8px` (`gap-2`) separation between primary and destructive buttons, and guard irreversible actions with an `AlertDialog` confirmation.
