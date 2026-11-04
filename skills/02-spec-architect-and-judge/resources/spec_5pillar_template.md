# <Project Name> — Application Specification

- **Input Scenario:** `SCENARIO_LEGACY_APP` | `SCENARIO_REQUIREMENTS_DOC`
- **Domain Slug:** `<domainSlug>`
- **Accessibility Standard(s):** `WCAG 2.1 AA` *(plus any the user named in `specs/target_stack.json`)*
- **Regulations / Policies in Scope:** `<names | none declared>`
- **Assumptions:** `ASSUMPTION-01 …` *(autonomous-mode answers to open workflow questions; empty if all were confirmed)*
- **Shared rules by reference:** `_shared/ux_guardrails.md`, `_shared/google_cloud_ui_design.md`, `_shared/zero_leak.md`, `_shared/workflow_chain_of_custody.md`

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

### 1.4 Modernization Enhancements (`REQ-ENH-NN`) *(SCENARIO_LEGACY_APP only — delete this subsection otherwise)*
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

### 3.4 Business Rules & Formulas *(parsed; thresholds are numbers)*
| Rule ID | Formula / Rule | Inputs | Source |
| :-- | :-- | :-- | :-- |

### 3.5 Roles *(parsed; Kind is `external` or `internal` — no other values)*
| Role | Kind | Views | Allowed Transitions |
| :-- | :-- | :-- | :-- |

---

## 4 Pillar 4 — User Experience & Zero Internal Data Leakage (`REQ-UX-NN`)
| ID | Requirement | Derived from |
| :-- | :-- | :-- |

### 4.1 UX Guardrail Overrides *(only deviations from `_shared/ux_guardrails.md`, each justified by a design reference or Gate 1 instruction)*
| Guardrail # | Override | Justification / reference |
| :-- | :-- | :-- |

### 4.2 View & Component Topology *(parsed by scripts — every top-level tab/route must be mutually exclusive; specify the Surface Mode `Operate` | `Read` | `Persuade` | `Express` and Google Cloud UI Design layout archetype; if `resources/design_references/reference_ui_manifest.json` exists, every reference view must be accounted for)*
| View ID | Navigation Tab / Route | UI Pattern (Wizard / Queue / Console / Registry) | Bound Role(s) | Primary CTA & Lifecycle Trigger |
| :-- | :-- | :-- | :-- | :-- |

### 4.3 Zero-Leakage Obligations
*(Cite `_shared/zero_leak.md`; name the ViewModel/label-mapping boundary; list any domain-specific tokens to add to the forbidden list.)*

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
