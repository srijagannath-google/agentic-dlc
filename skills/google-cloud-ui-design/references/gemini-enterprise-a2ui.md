# Declarative Agentic UI Surfaces (`A2UI v0.9`) for Gemini Enterprise

When modernizing legacy form-heavy or analytical applications onto **Gemini Enterprise** or hybrid conversational + workspace surfaces (`specs/target_stack.json#frontend.kind == "gemini-enterprise-a2ui"` or `aiSurface.protocol == "a2ui-v0.9"`), agents must never stream raw, untrusted HTML or free-form Markdown walls for structured workflows. Instead, emit **schema-validated `A2UI v0.9` JSON component payloads** rendered by the host client's trusted component catalog.

## 1. Core `A2UI v0.9` Architectural Principles

1. **Declarative JSON, Never Executable Code:** Backend agents emit typed component trees (`surfaceUpdate` / `dataModelUpdate`) referencing registered client components (`Canvas`, `RichTable`, `VegaChart`, `ActionCard`, `CitationChip`, `ApprovalCard`, `StepperForm`). No inline `<script>` or raw SQL/API strings ever cross the UI boundary.
2. **Two-Way Data Binding with Explicit Action Envelopes:** Interactive components bind form inputs to JSON Pointer paths (`/draftRequest/startDate`) and emit typed `userAction` events (`{"actionId": "submit_for_review", "contextPath": "/draftRequest"}`) validated against `specs/application_spec.md §3.3` `(fromState, trigger, actorRole)` guards on the server.
3. **Human-in-the-Loop Confirmation (`ApprovalCard`):** Any state-mutating or irreversible transition (`Approve`, `Reject`, `Disburse`, `Revoke`) renders an `ApprovalCard` displaying human-readable field labels, computed business-rule impacts (`§3.4`), and explicit primary/secondary action buttons—never executing silently inside a chat turn.
4. **Grounded Provenance (`CitationChip`):** Whenever an agentic copilot summarizes policy rules, eligibility calculations, or historical records, attach `CitationChip` elements pointing to human-readable policy sections or record display titles (never raw database primary keys, UUIDs, or table names—honouring `_shared/zero_leak.md`).

## 2. Standard `A2UI v0.9` Component Mapping

| Legacy / Business Pattern | `A2UI v0.9` Component | UX & Accessibility Contract (WCAG 2.1 AA) |
| :-- | :-- | :-- |
| Multi-tab Access / WinForms screen with > 15 fields | `Canvas` + `StepperForm` (<= 5 visible inputs per step) | Progressive disclosure; explicit `<label>` binding; inline validation summary with `role="alert"`. |
| Dense tabular subform / queue grid | `RichTable` | Sortable human-readable column headers, status badge mapped via ViewModel label dictionary, row-level action menu gated by `actorRole`. |
| Static legacy crystal/tabular report | `VegaChart` + summary KPI `ActionCard` | Accessible chart title, `aria-label` data summary, high-contrast Google Cloud token palette (`#1A73E8`, `#1E8E3E`, `#F9AB00`, `#D93025`), and tabular toggle for screen readers. |
| Approval / sign-off dialog | `ApprovalCard` | Displays current state badge, actor role, prerequisite checklist, and at most **1 primary CTA** (`data-testid="action-<trigger-slug>"`). |
| Policy / rule explanation | `CitationChip` | Keyboard-focusable chip opening a clean drawer with policy clause title and effective date. |

## 3. Dual-Mode Testability in Stage 5 & Stage 6

When `frontend.kind == "gemini-enterprise-a2ui"` (or when `aiSurface.protocol == "a2ui-v0.9"` augments a React/Angular/Next.js frontend):
- `src/ui/` includes a lightweight, standard-compliant **A2UI Host Renderer** so `bash src/run.sh` (`APP_ENV=local`) renders every `A2UI v0.9` payload into real semantic HTML elements carrying the contract-first `data-testid` attributes declared in `test/test_cases.json`.
- Stage 6 (`run_closed_loop_eval.py`) verifies full DOM interactivity, tab exclusivity, WCAG 2.1 AA compliance, and zero internal identifier leakage across every rendered `A2UI` component state.
