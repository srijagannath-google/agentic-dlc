# Closed-Loop Evaluation Report — Iteration 1

Generated: 2026-11-05T18:02:23Z  
Project: `dlc_sync_greenfield_leave_request_portal_0vpn43yk`  
Browser runtime: **chrome-headless** (/usr/bin/google-chrome)  
Backend started: **True**  
UI entry: `http://127.0.0.1:8766/`  
Preserved Per-Run Archive: `test/history/iter-1/` · `test/eval_report.iter-01.md` · `test/eval_results.iter-01.json`

## Verdict: **PASS** — 151/151 passed (score 100.0%)

| Total | PASS | FAIL | NOT_RUN | ERROR | Optional skipped |
| --: | --: | --: | --: | --: | --: |
| 151 | 151 | 0 | 0 | 0 | 0 |

Guardrail review: **CLEAR** (baseline `iter-0`, pending hunks: 0)

## Run History & Preserved Per-Iteration Artifacts

| Iter | Timestamp (UTC) | Verdict | PASS / Total | FAIL | NOT_RUN | ERROR | Failed Test IDs | Remediated Test IDs | Preserved Run Artifacts |
| --: | :-- | :-- | --: | --: | --: | --: | :-- | :-- | :-- |
| **1** | `2026-11-05T18:02:23Z` | **PASS** | 151/151 | 0 | 0 | 0 | — | — | `test/history/iter-1/` · `test/eval_report.iter-01.md` · `test/remediation_and_guardrail_audit_report.iter-01.md` |

## Per category

| Category | Total | PASS | FAIL | NOT_RUN | ERROR |
| :-- | --: | --: | --: | --: | --: |
| A11y | 1 | 1 | 0 | 0 | 0 |
| Api | 17 | 17 | 0 | 0 | 0 |
| Edge | 9 | 9 | 0 | 0 | 0 |
| Interact | 10 | 10 | 0 | 0 | 0 |
| Negative | 15 | 15 | 0 | 0 | 0 |
| Positive | 34 | 34 | 0 | 0 | 0 |
| State | 61 | 61 | 0 | 0 | 0 |
| UiLeak | 4 | 4 | 0 | 0 | 0 |

## All results

| Test ID | Category | Runtime | Status | ms | Failed step | Message |
| :-- | :-- | :-- | :-- | --: | :-- | :-- |
| TC-UI-INTERACT-TAB-01 | Interact | browser | PASS | 857 | — | 5 step(s) passed |
| TC-UI-INTERACT-TAB-02 | Interact | browser | PASS | 880 | — | 5 step(s) passed |
| TC-POS-01 | Positive | browser | PASS | 1011 | — | 10 step(s) passed |
| TC-NEG-01 | Negative | browser | PASS | 1221 | — | 11 step(s) passed |
| TC-NEG-02 | Negative | browser | PASS | 1127 | — | 9 step(s) passed |
| TC-UI-INTERACT-02 | Interact | browser | PASS | 1123 | — | 14 step(s) passed |
| TC-EDGE-01 | Edge | browser | PASS | 1012 | — | 11 step(s) passed |
| TC-STATE-01 | State | browser | PASS | 846 | — | 5 step(s) passed |
| TC-POS-02 | Positive | browser | PASS | 860 | — | 6 step(s) passed |
| TC-EDGE-02 | Edge | browser | PASS | 879 | — | 6 step(s) passed |
| TC-EDGE-03 | Edge | browser | PASS | 876 | — | 5 step(s) passed |
| TC-EDGE-04 | Edge | browser | PASS | 879 | — | 5 step(s) passed |
| TC-POS-03 | Positive | browser | PASS | 897 | — | 11 step(s) passed |
| TC-POS-04 | Positive | browser | PASS | 882 | — | 7 step(s) passed |
| TC-POS-05 | Positive | browser | PASS | 1171 | — | 12 step(s) passed |
| TC-NEG-03 | Negative | browser | PASS | 1416 | — | 12 step(s) passed |
| TC-NEG-04 | Negative | browser | PASS | 1207 | — | 12 step(s) passed |
| TC-NEG-05 | Negative | browser | PASS | 1219 | — | 11 step(s) passed |
| TC-EDGE-05 | Edge | browser | PASS | 1197 | — | 10 step(s) passed |
| TC-EDGE-06 | Edge | browser | PASS | 1216 | — | 10 step(s) passed |
| TC-POS-06 | Positive | browser | PASS | 1236 | — | 12 step(s) passed |
| TC-STATE-02 | State | browser | PASS | 1131 | — | 13 step(s) passed |
| TC-POS-07 | Positive | browser | PASS | 1059 | — | 11 step(s) passed |
| TC-POS-08 | Positive | browser | PASS | 1315 | — | 14 step(s) passed |
| TC-STATE-03 | State | browser | PASS | 1154 | — | 6 step(s) passed |
| TC-STATE-04 | State | browser | PASS | 881 | — | 6 step(s) passed |
| TC-STATE-05 | State | browser | PASS | 1281 | — | 14 step(s) passed |
| TC-UI-INTERACT-03 | Interact | browser | PASS | 1073 | — | 14 step(s) passed |
| TC-POS-09 | Positive | browser | PASS | 843 | — | 7 step(s) passed |
| TC-POS-10 | Positive | browser | PASS | 1539 | — | 18 step(s) passed |
| TC-STATE-06 | State | browser | PASS | 901 | — | 5 step(s) passed |
| TC-UI-INTERACT-04 | Interact | browser | PASS | 981 | — | 5 step(s) passed |
| TC-EDGE-07 | Edge | browser | PASS | 1005 | — | 5 step(s) passed |
| TC-POS-11 | Positive | browser | PASS | 1427 | — | 15 step(s) passed |
| TC-POS-12 | Positive | browser | PASS | 1805 | — | 18 step(s) passed |
| TC-NEG-06 | Negative | browser | PASS | 1461 | — | 18 step(s) passed |
| TC-POS-13 | Positive | browser | PASS | 1431 | — | 16 step(s) passed |
| TC-STATE-07 | State | browser | PASS | 1382 | — | 16 step(s) passed |
| TC-NEG-07 | Negative | browser | PASS | 848 | — | 4 step(s) passed |
| TC-STATE-08 | State | browser | PASS | 1062 | — | 12 step(s) passed |
| TC-UI-INTERACT-05 | Interact | browser | PASS | 1057 | — | 8 step(s) passed |
| TC-POS-14 | Positive | browser | PASS | 826 | — | 5 step(s) passed |
| TC-POS-15 | Positive | browser | PASS | 1626 | — | 18 step(s) passed |
| TC-NEG-08 | Negative | browser | PASS | 1960 | — | 21 step(s) passed |
| TC-POS-16 | Positive | browser | PASS | 1672 | — | 19 step(s) passed |
| TC-STATE-09 | State | browser | PASS | 1737 | — | 20 step(s) passed |
| TC-STATE-10 | State | browser | PASS | 1560 | — | 17 step(s) passed |
| TC-POS-17 | Positive | browser | PASS | 1570 | — | 18 step(s) passed |
| TC-NEG-09 | Negative | browser | PASS | 881 | — | 5 step(s) passed |
| TC-STATE-11 | State | browser | PASS | 841 | — | 5 step(s) passed |
| TC-UI-INTERACT-06 | Interact | browser | PASS | 951 | — | 6 step(s) passed |
| TC-POS-18 | Positive | browser | PASS | 1503 | — | 17 step(s) passed |
| TC-POS-19 | Positive | browser | PASS | 1491 | — | 17 step(s) passed |
| TC-NEG-10 | Negative | http | PASS | 4 | — | 2 http step(s) passed |
| TC-EDGE-08 | Edge | http | PASS | 4 | — | 3 http step(s) passed |
| TC-STATE-12 | State | http | PASS | 4 | — | 2 http step(s) passed |
| TC-STATE-13 | State | http | PASS | 2 | — | 1 http step(s) passed |
| TC-NEG-11 | Negative | http | PASS | 4 | — | 2 http step(s) passed |
| TC-STATE-14 | State | http | PASS | 5 | — | 2 http step(s) passed |
| TC-POS-20 | Positive | browser | PASS | 1034 | — | 14 step(s) passed |
| TC-POS-21 | Positive | browser | PASS | 1091 | — | 6 step(s) passed |
| TC-NEG-12 | Negative | http | PASS | 2 | — | 1 http step(s) passed |
| TC-NEG-13 | Negative | http | PASS | 2 | — | 1 http step(s) passed |
| TC-POS-22 | Positive | http | PASS | 2 | — | 1 http step(s) passed |
| TC-EDGE-09 | Edge | http | PASS | 6 | — | 2 http step(s) passed |
| TC-POS-23 | Positive | browser | PASS | 1058 | — | 3 step(s) passed |
| TC-POS-24 | Positive | browser | PASS | 908 | — | 4 step(s) passed |
| TC-POS-25 | Positive | browser | PASS | 1160 | — | 11 step(s) passed |
| TC-POS-26 | Positive | browser | PASS | 1414 | — | 16 step(s) passed |
| TC-UI-INTERACT-07 | Interact | browser | PASS | 907 | — | 5 step(s) passed |
| TC-POS-27 | Positive | browser | PASS | 911 | — | 4 step(s) passed |
| TC-POS-28 | Positive | browser | PASS | 921 | — | 5 step(s) passed |
| TC-POS-29 | Positive | browser | PASS | 781 | — | 2 step(s) passed |
| TC-NEG-14 | Negative | browser | PASS | 1170 | — | 8 step(s) passed |
| TC-UI-INTERACT-08 | Interact | browser | PASS | 982 | — | 7 step(s) passed |
| TC-POS-30 | Positive | http | PASS | 3 | — | 2 http step(s) passed |
| TC-POS-31 | Positive | http | PASS | 2 | — | 1 http step(s) passed |
| TC-POS-32 | Positive | http | PASS | 2 | — | 1 http step(s) passed |
| TC-NEG-15 | Negative | http | PASS | 1 | — | 1 http step(s) passed |
| TC-POS-33 | Positive | http | PASS | 5 | — | 2 http step(s) passed |
| TC-STATE-15 | State | browser | PASS | 1293 | — | 15 step(s) passed |
| TC-STATE-16 | State | browser | PASS | 1595 | — | 18 step(s) passed |
| TC-STATE-17 | State | browser | PASS | 1277 | — | 15 step(s) passed |
| TC-STATE-18 | State | browser | PASS | 1311 | — | 15 step(s) passed |
| TC-STATE-19 | State | browser | PASS | 1412 | — | 16 step(s) passed |
| TC-STATE-20 | State | browser | PASS | 1529 | — | 17 step(s) passed |
| TC-STATE-21 | State | browser | PASS | 1520 | — | 17 step(s) passed |
| TC-STATE-22 | State | browser | PASS | 1635 | — | 19 step(s) passed |
| TC-STATE-23 | State | browser | PASS | 1932 | — | 20 step(s) passed |
| TC-STATE-24 | State | browser | PASS | 1843 | — | 20 step(s) passed |
| TC-STATE-25 | State | browser | PASS | 995 | — | 6 step(s) passed |
| TC-STATE-26 | State | browser | PASS | 1058 | — | 7 step(s) passed |
| TC-STATE-27 | State | browser | PASS | 1331 | — | 10 step(s) passed |
| TC-STATE-28 | State | browser | PASS | 1077 | — | 7 step(s) passed |
| TC-STATE-29 | State | browser | PASS | 989 | — | 6 step(s) passed |
| TC-STATE-30 | State | browser | PASS | 918 | — | 6 step(s) passed |
| TC-STATE-31 | State | browser | PASS | 1002 | — | 7 step(s) passed |
| TC-STATE-32 | State | browser | PASS | 1179 | — | 10 step(s) passed |
| TC-STATE-33 | State | browser | PASS | 1055 | — | 7 step(s) passed |
| TC-STATE-34 | State | browser | PASS | 1050 | — | 7 step(s) passed |
| TC-STATE-35 | State | browser | PASS | 948 | — | 6 step(s) passed |
| TC-STATE-36 | State | browser | PASS | 1102 | — | 13 step(s) passed |
| TC-STATE-37 | State | browser | PASS | 1213 | — | 14 step(s) passed |
| TC-STATE-38 | State | browser | PASS | 1296 | — | 17 step(s) passed |
| TC-STATE-39 | State | browser | PASS | 1290 | — | 14 step(s) passed |
| TC-STATE-40 | State | browser | PASS | 1218 | — | 14 step(s) passed |
| TC-STATE-41 | State | browser | PASS | 1335 | — | 13 step(s) passed |
| TC-STATE-42 | State | browser | PASS | 1448 | — | 16 step(s) passed |
| TC-STATE-43 | State | browser | PASS | 1655 | — | 19 step(s) passed |
| TC-STATE-44 | State | browser | PASS | 1667 | — | 19 step(s) passed |
| TC-STATE-45 | State | browser | PASS | 1004 | — | 6 step(s) passed |
| TC-STATE-46 | State | browser | PASS | 845 | — | 4 step(s) passed |
| TC-STATE-47 | State | browser | PASS | 1352 | — | 15 step(s) passed |
| TC-STATE-48 | State | browser | PASS | 1784 | — | 20 step(s) passed |
| TC-STATE-49 | State | browser | PASS | 1098 | — | 7 step(s) passed |
| TC-STATE-50 | State | browser | PASS | 1336 | — | 15 step(s) passed |
| TC-STATE-51 | State | browser | PASS | 927 | — | 4 step(s) passed |
| TC-STATE-52 | State | browser | PASS | 1645 | — | 15 step(s) passed |
| TC-STATE-53 | State | browser | PASS | 1693 | — | 17 step(s) passed |
| TC-STATE-54 | State | browser | PASS | 1048 | — | 7 step(s) passed |
| TC-STATE-55 | State | browser | PASS | 1411 | — | 15 step(s) passed |
| TC-STATE-56 | State | browser | PASS | 967 | — | 4 step(s) passed |
| TC-STATE-57 | State | browser | PASS | 1387 | — | 15 step(s) passed |
| TC-STATE-58 | State | browser | PASS | 1619 | — | 17 step(s) passed |
| TC-STATE-59 | State | browser | PASS | 1850 | — | 20 step(s) passed |
| TC-STATE-60 | State | browser | PASS | 1796 | — | 20 step(s) passed |
| TC-STATE-61 | State | browser | PASS | 1397 | — | 15 step(s) passed |
| TC-POS-JOURNEY-01 | Positive | browser | PASS | 1402 | — | 16 step(s) passed |
| TC-API-01 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-API-02 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-API-03 | Api | http | PASS | 1 | — | 1 http step(s) passed |
| TC-API-04 | Api | http | PASS | 5 | — | 1 http step(s) passed |
| TC-API-05 | Api | http | PASS | 3 | — | 1 http step(s) passed |
| TC-API-06 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-API-07 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-API-08 | Api | http | PASS | 3 | — | 1 http step(s) passed |
| TC-API-09 | Api | http | PASS | 3 | — | 1 http step(s) passed |
| TC-API-10 | Api | http | PASS | 7 | — | 1 http step(s) passed |
| TC-API-11 | Api | http | PASS | 4 | — | 1 http step(s) passed |
| TC-API-12 | Api | http | PASS | 7 | — | 1 http step(s) passed |
| TC-API-13 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-API-14 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-API-15 | Api | http | PASS | 1 | — | 1 http step(s) passed |
| TC-API-16 | Api | http | PASS | 1 | — | 1 http step(s) passed |
| TC-API-17 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-UI-INTERACT-01 | Interact | static | PASS | 0 | — | 2 static step(s) passed over 114 rendered/static text corpus(es) |
| TC-A11Y-01 | A11y | static | PASS | 0 | — | 2 static step(s) passed over 114 rendered/static text corpus(es) |
| TC-UI-LEAK-01 | UiLeak | static | PASS | 11 | — | 2 static step(s) passed over 114 rendered/static text corpus(es) |
| TC-UI-LEAK-02 | UiLeak | static | PASS | 8 | — | 2 static step(s) passed over 114 rendered/static text corpus(es) |
| TC-UI-LEAK-03 | UiLeak | static | PASS | 35 | — | 10 static step(s) passed over 114 rendered/static text corpus(es) |
| TC-UI-LEAK-04 | UiLeak | static | PASS | 6 | — | 3 static step(s) passed over 114 rendered/static text corpus(es) |

## Failures (expected vs actual)

None.
## Zero-leakage scan (TC-UI-LEAK-01..04)

Tokens scanned: 66 · exact hits: **0** · heuristic warnings: 0

## Interactive control audit (TC-UI-INTERACT-01)

Controls observed across all reached DOM states: 80 · unwired: **0**

## Accessibility lint (TC-A11Y-01)

Findings: **0**

## UX guardrail metrics (TC-UX-SIMPLE-01..03)

- Max visible primary buttons on one screen: 1 (≤ 1) ['[data-testid=submit-btn]']
- Max visible tabs/nav items: 2 (≤ 3)
- Max visible inputs outside `<details>` in one step container: 4 (≤ 5) in `[data-testid=request-form]`
- Main container max-width: 800px

## Visual evidence & viewport screenshots

| View / Capture | Kind | Artifact Path |
| :-- | :-- | :-- |
| Initial landing view (1440x900) | `landing` | `test/history/iter-1/screenshots/landing-initial.png` |
| Tab 1: [data-testid=tab-my-requests] -> #panel-my-requests | `tab` | `test/history/iter-1/screenshots/tab-01-tab-my-requests.png` |
| Tab 2: [data-testid=tab-policy-guide] -> #panel-policy-guide | `tab` | `test/history/iter-1/screenshots/tab-02-tab-policy-guide.png` |
