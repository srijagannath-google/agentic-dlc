# Specification Quality Scorecard (`specs/application_eval_scorecard.md`)

*Human-readable twin of `specs/application_eval_scorecard.json`. Numbers must be identical in both files.*

- **Spec file:** `specs/application_spec.md` — **specSha256:** `<sha256 of the file as judged>`
- **Rubric version:** `4.0` — **Input Scenario:** `<Legacy Application Modernization | Greenfield Requirements Specification>`
- **TOTAL_SCORE:** `<n>/100` (pass threshold `90`)
- **OVERALL_VERDICT:** `PASS` | `FAIL`
- **Blocking gaps:** `<none>` | list of `gap` text for blocking criteria scored 0

## Pillar totals
| Pillar | Awarded | Max |
| :-- | :-: | :-: |
| 1 Functionality & Business Rules | | 25 |
| 2 Security, RBAC, PII & Audit | | 20 |
| 3 Accessibility | | 20 |
| 4 UX & Zero Leakage | | 15 |
| 5 Target Architecture | | 20 |
| **Total** | | **100** |

## Criteria
| ID | Pillar | Max | Awarded | Blocking | Evidence (verbatim quote from the spec) | Gap |
| :-- | :-: | :-: | :-: | :-: | :-- | :-- |
| `P1-C1` | 1 | | | yes/no | "…" | … or `not applicable: <reason>` |

## Specification Remediation Priorities *(only when FAIL; ordered by points recoverable)*
1. `<criterion id>` — `<gap>`
