# Security Chain of Custody, CodeMender (`cm`) & Gemini Decisions API (`v4.8`)

Security in `agentic-dlc` is **not** an end-of-pipeline compliance checkbox — it is an active **path-driving spine** that governs `clean-room-rebuild` vs. `in-place-upgrade`, Strangler wave sequencing, Business Analyst `grill-me` threat decisions, executable shift-left `TC-SEC-*` verification, ALM `BUG-SEC-*` defect tracking & rectification, and container release gating.

---

## 1. End-to-End Security Chain of Custody (Stages 0 → 9)

| Stage | Security & Control-Plane Action | Artefact / Evidence | Enforcement Gate |
| :-- | :-- | :-- | :-- |
| **Stage 0 · Setup** | Verify CodeMender (`cm`) CLI availability (alert user with install instructions if absent); configure optional `codemender-security` domain pack and `GEMINI_API_KEY` (`gemini-decision-1` control plane). | `specs/project_setup.json`, `~/.gemini/config/agentic-dlc.env` | `gate_0_setup` |
| **Stage 1 · Legacy Security Baseline** | Run CodeMender (`cm find <inputs> --format=sarif`) + deterministic security posture scan on `resources/inputs/` to extract injection sinks, broken crypto, unsafe deserialization, hardcoded credentials, and sensitive PII/regulated fields. Systemic `CRITICAL`/`HIGH` debt overrides `in-place-upgrade` → `clean-room-rebuild`. | `specs/legacy_security_findings.sarif` (when `cm` installed), `specs/legacy_security_summary.json`, `specs/input_inventory.json#securityPostureSignals` | `gate_1_discovery` |
| **Pre-Spec `grill-me` (Mandatory on Findings)** | **Mandatory Rule:** Whenever Stage 1 (`cm` or built-in scan) detects **any** security finding (`findingCount > 0`), `clarification-griller` **ALWAYS** quizzes the human / Business Analyst via a `🔥 Grill-Me` `security-pii` question on what path forward to take (`clean-room-rebuild` + anti-regression tests vs. `GRP-00-SEC` Sprint 1 hardening wave vs. risk-first Strangler wave ordering). | `specs/clarification_decisions.json` (`DECISION-NN`, category `security-pii`) | `SD-GRILL-00` / `SD-GRILL-01` |
| **Stage 2 · Specification Pillar 2** | Translate Stage 1 security findings, sensitive data fields, and `DECISION-NN` answers into explicit `REQ-SEC-*` requirements (authn/authz, tenant isolation, field masking, input parameterization, rate limiting, audit immutability). Hybrid `gemini-decision-1` pre-scores all 20 rubric criteria in one forward pass before `spec-judge`. | `specs/application_spec.md` (Pillar 2 + §3.5), `specs/application_eval_scorecard.json` | `gate_2_spec` |
| **Stage 3 · Abuse-Case User Stories** | Every mutating or external-facing `US-FUNC-*` slice includes `[NEGATIVE — SECURITY / ABUSE CASE]` acceptance criteria (BOLA/IDOR cross-tenant tampering, unauthorized role rejection, injection/payload rejection), plus `US-SEC-*` Sprint 1 remediation slices when `modernizationMode == "in-place-upgrade"`. `gemini-decision-1` scores per-story complexity & security criticality (`Flash` vs. `Pro` model routing). | `backlog/user_stories.{json,md}`, `specs/.story_model_routing.json` | `gate_3_backlog` |
| **Stage 4A & 4B · Threat Design & `TC-SEC-*` Suite** | `design/security_architecture.md` documents 5-layer defense-in-depth + AI Trust Layer (`ZeroTrustSecurityAdversary` Red-Team persona); `derive_test_cases.py` generates `TC-SEC-*` (`Security` category: unauthorized mutating-route probes + `TC-SEC-LEGACY-*` anti-regression checks). | `design/security_architecture.md`, `test/test_cases.json` (`TC-SEC-*`) | `gate_4_design_and_tests` |
| **Post-Stage-5 · Target Scan, ALM Defect Log & Rectification** | Right after building `src/` (`validate_build.py`), auto-generate `.codemender/config.yaml`, run `cm find ./src/ --format=sarif` (+ `cm verify <id>`) and deterministic security checks on `src/`. **Every finding is logged as `BUG-SEC-01..N` (`issueType: "Bug"`) in `backlog/defects.{json,md}` and synced to Jira / Azure DevOps.** Gate 5 FAILS until `cm fix <id>` or `coding-agent` rectifies every finding and a clean re-scan transitions `BUG-SEC-*` to `Done` with remediation comments! | `.codemender/config.yaml`, `test/security_post_build_report.json`, `backlog/defects.{json,md}` (`BUG-SEC-*`) | `gate_5_build` |
| **Stage 6 · Closed-Loop Eval & Gate 4 Diff Audit** | Execute `TC-SEC-*` dynamic tests alongside functional/state/a11y/leak tests; any Stage 6 self-healing diff touching `@dlc-sec`, RBAC, masking, or sanitization triggers **Gate 4** (`FLAGGED_REQUIRES_HUMAN_APPROVAL`). | `test/eval_results.json`, `test/remediation_and_guardrail_audit_report.md` | `gate_6_eval` |
| **Stages 7 & 8 · Zero-Open-Security-Bug Release Gate** | Verify `@dlc-sec:REQ-SEC-NN` pragmas in `src/` and block container / GDC packaging if any `BUG-SEC-*` defect remains open (`status != "Done"`). Enforce rootless `USER 65532:65532`, `readOnlyRootFilesystem: true`, GDC Policy Controller OPA constraints, and `STRICT` mTLS. | `test/drift_report.json`, `deploy/gdc/{policy-controller,service-mesh}/*` | `gate_7_drift`, `gate_8_packaging` |

---

## 2. CodeMender (`cm` CLI) Installation & Local Execution Contract

CodeMender operates on a **"centralized brain, local hands"** model: the standalone `cm` binary runs locally on the developer workstation or CI agent, keeping source code, builds, and sandboxed PoC verification local while sending bounded context outbound to Vertex AI.

1. **Missing-`cm` Machine Alert Policy:**
   - Checked automatically during `bootstrap.sh` / `bootstrap.ps1`, Stage 0 (`setup_project_connection.py`), Stage 1 (`scan_input_sources.py`), and Post-Stage-5 (`validate_build.py`).
   - Binary resolution order: `$CM_BIN` → `cm` on `$PATH` → `~/.codemender/cm` → `/usr/local/bin/cm`.
   - Whenever `cm` is not installed on the machine, the harness prints a prominent `[⚠️ SECURITY ALERT — CODEMENDER ('cm') CLI NOT INSTALLED]` notice instructing the user how to install `cm` (`~/.codemender/cm`, authenticate via `gcloud auth application-default login` or `CM_API_KEY`, see `https://docs.cloud.google.com/gemini-enterprise-agent-platform/codemender/set-up-environment`) and runs built-in deterministic security checks so baseline protection remains active.
2. **Stage 1 Legacy Scan (`resources/inputs/`):**
   - Runs `cm find "<input_dir>" --format=sarif --output "<PROJECT_ROOT>/specs/legacy_security_findings.sarif"`.
   - Any discovered vulnerability **always** triggers a `pre-spec` `🔥 Grill-Me` question so the user decides how legacy security risk drives the modernization path.
3. **Post-Stage-5 Target Build Scan, ALM `BUG-SEC-*` Defect Sync & Rectification (`src/`):**
   - Auto-generates `<PROJECT_ROOT>/.codemender/config.yaml` bound to `specs/target_stack.json#commands.{build,test,reset}`.
   - Runs `cm find ./src/ --format=sarif` (+ `cm verify <finding-id>` to confirm exploitability with zero false positives).
   - Logs each finding as `BUG-SEC-01..N` (`issueType: "Bug"`, `status: "In Progress"`) in `backlog/defects.json` & `backlog/defects.md` and syncs to Jira / Azure DevOps (`alm_jira_ado_bridge.py --action sync-defects`).
   - Fails Gate 5 until `cm fix <finding-id>` or `coding-agent` rectifies the vulnerability and a clean re-scan transitions `BUG-SEC-01..N` to `"Done"` with remediation notes.

---

## 3. Code Security Annotation Pragmas (`@dlc-sec`)

Annotate security enforcement points in `src/` alongside `@dlc-guard` and `@dlc-rule`:
- `@dlc-sec:REQ-SEC-01` — Authentication /RBAC / BOLA tenant-ownership check
- `@dlc-sec:REQ-SEC-02` — Parameterized query / input validation / output encoding boundary
- `@dlc-sec-safe` — Explicit line-level opt-out for verified non-exploitable test/demo constructs (audited in Stage 6 Gate 4)

---

## 4. Low-Cost Probabilistic Control Plane (`Gemini Decisions API` · `gemini-decision-1`)

When `GEMINI_API_KEY` is configured in `<PROJECT_ROOT>/.env` or `~/.gemini/config/agentic-dlc.env`, `scripts/dlc_decisions_client.py` calls `POST https://generativelanguage.googleapis.com/v1beta/decisions` (`model: "models/gemini-decision-1"`, Tree-Prefill scoring at **\$0.10 / 1M input tokens** and **\$0.00 output tokens**, cached by SHA-256 in `specs/.decisions_cache.json`):
1. **`classify-intent` (Stage 0):** Classifies user prompt intent (`retro-spec | modernize | greenfield | delta`) and ceremony track (`quick | standard | regulated`).
2. **`triage-files` (Stage 1 Large-Repo Map-Reduce):** Scores hundreds of files in one shared-prefix call (`has_domain_rule`, `has_workflow_state`, `has_security_sink`) to skip boilerplate DTOs and focus `discovery-architect` + `cm find` on high-signal modules.
3. **`detect-ambiguities` (`pre-spec` & `pre-stories`):** Evaluates calibrated semantic contradiction probabilities (`p_yes >= 0.55` or `confidence < 0.75`) across multimodal docs/code to escalate hidden business-rule or security conflicts into `🔥 Grill-Me`.
4. **`score-rubric` (Stages 2 & 4A Hybrid Judge):** Pre-scores all 20 rubric criteria (`schemas/spec_rubric.json` / `schemas/architecture_rubric.json`) as ordered `score` + blocking `noul` questions so generative Pro judges focus token spend on criteria scoring `< maxPoints`.
5. **`route-stories` (Stage 3 → Stages 5/6):** Scores every story in `backlog/user_stories.json` to assign `recommendedModelTier` (`flash` for low-risk CRUD/UI slices vs. `pro` + CodeMender verification for complex state/security/crypto slices).
