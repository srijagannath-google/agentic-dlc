# UX Simplicity, Progressive Disclosure, Accessibility & Google Cloud UI Design Guardrails

Applies to **Stage 2** (`specs/application_spec.md` §4), **Stage 4A** (`design/solution_design.md` §3), **Stage 5** (`06-coding-agent`) and **Stage 6** (`07-test-runner-and-healer`). Also read `<PLUGIN>/_shared/google_cloud_ui_design.md` and `<PLUGIN>/skills/google-cloud-ui-design/SKILL.md` (`references/tokens-and-accessibility.md` + the matching layout blueprint in `references/*.md`).

User design references in `resources/design_references/` or explicit Gate 1 instructions take precedence; record any override in spec §4.1.

---

## Core UX & Google Cloud UI Design Guardrails

1. **Declare Surface Mode (`Operate` | `Read` | `Persuade` | `Express`) & Reference Layout Archetype.**
   - Every view must declare its primary Surface Mode and map to one of the 6 Google Cloud UI Design layout archetypes (`Admin/FinOps Dashboard`, `Master-Detail Split-Screen Operations Queue`, `Full-Viewport GIS Map & Telemetry Stage`, `50/50 Split-View Document & Compliance Auditor`, `Enterprise Solution Landing Page`, or `2-Zone Gemini Enterprise Agent & HITL Workspace` in `<PLUGIN>/skills/google-cloud-ui-design/references/`). Never mix modes on the same viewport (no marketing hero banners inside an `Operate` workspace).
2. **One primary task per view.**
   - At most **one** primary filled CTA button (`bg-[var(--g-blue)]` / `[data-primary="true"]`) per visible panel/section (`TC-UX-SIMPLE-01`). All secondary actions use outline/ghost treatment (`variant="outline"` / `variant="ghost"`).
   - Button labels must use explicit **`[Verb] + [Object]`** phrasing (e.g., `"Approve Application"`, `"Export Audit CSV"` — never vague `"Submit"` or `"OK"`). Separate destructive actions from primary actions by at least `8px` (`gap-2`) and guard irreversible mutations with an `AlertDialog` confirmation.
3. **Top-level navigation ≤ 5 items & Collapsible Left Navigation Rail.**
   - Group views by **user goal or role workspace**, never by database table.
   - Left navigation rail (`240px–256px` expanded, `56px` collapsed) uses a single horizontal header row (`flex items-center justify-between w-full px-3 h-12 border-b border-[var(--g-border-subtle)]`) with left brand icon + application title (`truncate`) and a flush-right collapse button (`ml-auto shrink-0`).
   - Clicking a tab or nav item switches the active panel (`hidden` / `aria-selected`) so only **one** `[role="tabpanel"]` is visible at a time (`TC-UX-SIMPLE-03`).
4. **Progressive disclosure on forms.**
   - At most **5 visible input fields per step** outside `<details>` (`TC-UX-SIMPLE-02`). Longer forms split into steps or place optional/audit metadata in a collapsed `<details>` drawer.
5. **Unified Surfaces (`divide-x` / `divide-y` + `<dl>`) — Zero "Card Soup" & Focused Reading Measure.**
   - Never wrap individual KPI metrics or metadata attributes in separate bordered mini-cards inside a panel ("card soup"), and never nest a vertical scrollbar inside another vertical scrollbar. Render a **single unified surface** (`rounded-xl border border-[var(--g-border)] bg-[var(--g-surface)]`) divided by `1px solid var(--g-border-subtle)` hairlines (`divide-x`, `divide-y`, `<Separator />`) and semantic `<dl>` (`<dt>` / `<dd>`) grids.
   - Focused **`Read`** views and step-by-step intake forms constrain reading width to `60ch–75ch` (`720px–840px` / `max-w-3xl`), whereas **`Operate`** workspaces use a full-viewport application shell (`h-screen w-screen overflow-hidden`) or `max-w-7xl` dashboard container with 50/50 `ResizablePanelGroup` split panes (`defaultSize={50}`, draggable `ResizableHandle withHandle`, double-click reset to 50/50).
6. **Google Material 3 / Cloud Console Token System (`--g-*`), 60-30-10 Tonal Balance & Anti-Slop Craft Floor.**
   - Define the canonical `:root` (Light) and `.dark` (Dark) `--g-*` CSS custom properties (`--g-bg`, `--g-surface`, `--g-surface-dim`, `--g-surface-high`, `--g-ink`, `--g-ink-secondary`, `--g-ink-muted`, `--g-border`, `--g-border-subtle`, `--g-blue`, `--g-green`, `--g-amber`, `--g-amber-text`, `--g-red`, `--g-purple`) from `<PLUGIN>/_shared/google_cloud_ui_design.md`. Default to `defaultTheme="system"` with a `System | Light | Dark` toggle.
   - **Anti-Slop Bans:** No purple-to-blue AI gradients on buttons/cards/text; no neon dark-mode box-shadows; no decorative glassmorphism on tables/forms; no rainbow KPI numbers or rainbow icons (keep KPI numbers and `lucide-react` icons monochrome `--g-ink` / `--g-ink-secondary`); reserve `<Badge>` strictly for a single table Status column or finding Severity; never expose raw JSON, database column names, or raw model SKU strings (`gemini-2.5-flash`) in UI chrome.
7. **Numeric Discipline (`tabular-nums`), Plain-Language Validation & Complete 4-State Coverage.**
   - Apply `font-variant-numeric: tabular-nums` (`tabular-nums`) to all KPI numbers, currency amounts, percentages, counts, timestamps, and right-aligned numeric table columns (`text-right font-mono tabular-nums`).
   - Every async panel and data view must implement **Loading** (`Skeleton`), **Empty** (icon + explanation + recovery action), **Error** (plain-language message naming the field and how to fix it + inline `Retry` + `<details>`), and **Populated** states.
8. **Role- & state-gated actions.**
   - Controls for transitions not permitted in the current state or for the active role (spec §3.3 / §3.5) are **disabled (`disabled` + `aria-disabled="true"`) or omitted** in the UI **and** rejected (`403` / `409`) by the backend.
9. **WCAG 2.1 AA Baseline & Semantic HTML5 Element Mandate (`TC-A11Y-01`).**
   - `<html lang="en">`; `<a href="#main-content">Skip to main content</a>` as the first focusable element in `<body>`; semantic landmarks (`<header>`, `<nav aria-label="...">`, `<main id="main-content">`, `<section>`, `<aside>`, `<dl>`, `<footer>`, `<table>`/`<th scope="col">`).
   - Programmatic `<label for>` (or `aria-label` / `aria-labelledby`) on every `<input>`, `<select>`, `<textarea>`; `aria-live="polite"` on status banners; `role="alert"` on validation errors; visible `:focus-visible` ring (`2px solid var(--g-blue)`).
   - Contrast ≥ 4.5:1 for normal text (use `--g-amber-text: #B06000` on light amber badges, never `#F9AB00` text on white) and ≥ 3:1 for large text/UI components; `cursor: pointer` on all enabled interactive elements; symmetrical `12px` right padding on `<select>` carets.
   - Add jurisdiction-specific standards (Section 508, EN 301 549, WCAG 2.2) only when recorded in `specs/target_stack.json#accessibilityStandard`.
