# <Project Name> — Application Specification

- **Input Scenario:** `Legacy Application Modernization` | `Greenfield Requirements Specification`
- **Domain Slug:** `<domainSlug>`
- **Status:** `🟡 IN REVIEW`
- **Author:** `<primary_human_owner>`
- **Approvals:**
  - **Phases 1.1 - 1.N** - `[Pending Gate 2 / PR Review]` - `{{PENDING_APPROVAL}}`
- **Accessibility Standard(s):** `WCAG 2.1 AA` *(plus any the user named in `specs/target_stack.json`)*
- **Regulations / Policies in Scope:** `<names | none declared>`
- **Assumptions:** `ASSUMPTION-01 …` *(autonomous-mode answers to open workflow questions; empty if all were confirmed)*
- **Architectural & UX Standards:** Enterprise UX Simplicity Guardrails, Material 3 / Cloud Console Design System, Zero Internal Data Leakage Boundary, and Deterministic Workflow Chain of Custody

---

## 1 Pillar 1 — Functionality & Business Rules

### 1.1 Functional Requirements (`REQ-FUNC-NN`)
| ID | Requirement (testable statement) | Actors | Capability ref | Source |
| :-- | :-- | :-- | :-- | :-- |

### 1.2 Journeys & Steps
*(Each multi-step flow: step list derived from the capability inventory and the §3.3 states — never from a fixed count.)*

### 1.3 Validation Rules
| ID | Field / Action | Rule | User-readable message (what failed + the fix) |
| :-- | :-- | :-- | :-- |

### 1.4 Modernization Enhancements (`REQ-ENH-NN`) *(Legacy Application Modernization only — delete this subsection otherwise)*
| ID | Enhancement | Pain point addressed (discovery §5 ref) | Acceptance signal |
| :-- | :-- | :-- | :-- |

---

## 2 Pillar 2 — Security, RBAC, PII & Audit (`REQ-SEC-NN`)
| ID | Requirement | Applies to |
| :-- | :-- | :-- |

### 2.1 RBAC Matrix
| Capability / Transition | <Role A> | <Role B> | … |
| :-- | :-: | :-: | :-: |

### 2.2 PII Fields & Masking *(source of `piiPatterns` for leakage tests)*
| Field | Classification | Masked display format | Storage protection |
| :-- | :-- | :-- | :-- |

### 2.3 Audit Events
| Event | Recorded fields | Retention |
| :-- | :-- | :-- |

---

## 3 Pillar 3 — Accessibility (`REQ-A11Y-NN`) and Lifecycle Tables
| ID | Requirement (measurable) | Standard clause |
| :-- | :-- | :-- |

### 3.3 Lifecycle State Machine *(frozen; parsed by scripts — table must mirror the diagram)*
```mermaid
stateDiagram-v2
    [*] --> <InitialState>
```

| From | To | Trigger | Actor Role | Guard |
| :-- | :-- | :-- | :-- | :-- |

**State labels shown to users:** `| State code | Visible label |` *(the UI never shows the code)*

### 3.4 Business Rules & Formulas *(parsed; thresholds are numbers; include `input -> expected` vectors in `Examples`)*
| Rule ID | Formula / Rule | Inputs | Source | Examples |
| :-- | :-- | :-- | :-- | :-- |

### 3.5 Roles *(parsed; Kind is `external` or `internal` — no other values)*
| Role | Kind | Views | Allowed Transitions |
| :-- | :-- | :-- | :-- |

---

## 4 Pillar 4 — User Experience & Zero Internal Data Leakage (`REQ-UX-NN`)
| ID | Requirement | Derived from |
| :-- | :-- | :-- |

### 4.1 UX Guardrail Overrides *(only deviations from standard Enterprise UX Simplicity Guardrails, each justified by a design reference or Gate 1 instruction)*
| Guardrail # | Override | Justification / reference |
| :-- | :-- | :-- |

### 4.2 View & Component Topology *(every top-level tab/route must be mutually exclusive; specify the Surface Mode `Operate` | `Read` | `Persuade` | `Express` and layout archetype; if `resources/design_references/reference_ui_manifest.json` exists, every reference view must be accounted for)*
| View ID | Navigation Tab / Route | UI Pattern (Wizard / Queue / Console / Registry) | Bound Role(s) | Primary CTA & Lifecycle Trigger |
| :-- | :-- | :-- | :-- | :-- |

### 4.3 Zero-Leakage Obligations
*(State the Zero Internal Data Leakage commitment; name the ViewModel/DTO label-mapping boundary; list any domain-specific tokens prohibited from appearing in visible UI text.)*

---

## 5 Pillar 5 — Target Architecture & Engineering Guidelines (`REQ-ARCH-NN`)
| ID | Requirement | Stack element (`specs/target_stack.json`) |
| :-- | :-- | :-- |
*(Layering, contract-first API, 3NF schema, state-guard enforcement in backend and UI, ViewModel boundary,
`data-testid` contract, observability, runnability commands. Legacy scenario: explicit statement that no legacy
structures, bridges or adapters are carried over. Requirements-document scenario: required integrations listed as components.)*

---

## 6 Traceability
See `specs/traceability_matrix.md` — every `REQ-*` above maps to capability → story → test category.
