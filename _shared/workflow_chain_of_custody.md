# Workflow Chain of Custody — canonical copy (shared)

The application's lifecycle state machine is the backbone every stage derives from. It must be **extracted,
never invented**.

## Stage 1 — Extract or ask
- **Legacy inputs:** derive states from status columns/enums, form button handlers, queries that filter on
  status, report selection criteria, and any workflow documentation. Record the evidence (file + line/object
  name) for every state and transition in `specs/discovery_architecture_and_inventory.md §3`.
- **Requirements documents:** derive states from the documented process steps, approval paths and SLAs.
- **Ask-don't-assume:** if any of the following is not evidenced, list it under
  `§3.1 Open Workflow Questions` and ask the user at Gate 1 before Stage 2:
  which roles may trigger each transition; whether rejection is terminal or returns to an editable state;
  whether holds/escalations exist; what the terminal/fulfilment states are; whether records can be reopened.
- In autonomous mode with unanswered questions, choose the **most restrictive** reading (fewer transitions,
  fewer roles) and record each assumption as `ASSUMPTION-NN` in the spec so it is visible and testable.

## Stage 2 — Freeze
`specs/application_spec.md §3.3` contains one `stateDiagram-v2` block **and** an equivalent transition table:

| From | To | Trigger | Actor Role | Guard |
| :-- | :-- | :-- | :-- | :-- |

plus `§3.5 Roles` (`| Role | Kind | Views | Allowed Transitions |`, Kind = `external` or `internal`). Scripts parse the table (`dlc_common.parse_state_machine`).

## Stage 3 — Stories carry transitions
Every workflow story lists `workflowTransitions` it implements, and includes, as applicable:
- `[NEGATIVE — ROLE VISIBILITY]`: controls for internal-role transitions are not rendered for external roles;
- `[NEGATIVE — WORKFLOW PREREQUISITE GATE]`: a transition not allowed from the record's current state is blocked
  with a user-readable reason;
- `[POSITIVE — INTERACTIVE COMPLETENESS]`: every control the story introduces has defined behaviour.

## Stage 4B — Tests are generated from the table
`05/scripts/derive_test_cases.py` creates `TC-STATE-*` for every illegal (state, trigger) pair and every
(role, trigger) pair the role does not own, and `TC-POS-*` for every legal path.

## Stage 5 — Code enforces it in two places
- **UI:** controls are rendered/enabled from `(currentState, currentRole)` using the same table (ideally as a
  data structure, not scattered `if`s).
- **Backend/API:** every transition endpoint validates `(fromState, trigger, role)` against the table and
  returns a 4xx with a human-readable message otherwise. The UI is never the only guard.

## Stage 6 — Verified, not trusted
State tests run in a real browser (and over HTTP when a backend exists). Any self-healing change touching a
transition guard, role check or business formula is flagged for human approval (Gate 4).
