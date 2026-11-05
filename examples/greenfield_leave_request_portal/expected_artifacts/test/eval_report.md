# Closed-Loop Evaluation Report — Iteration 1

Generated: 1970-01-01T00:00:00Z  
Project: `greenfield_leave_request_portal`  
Browser runtime: **chrome-headless** (/usr/bin/google-chrome)  
Backend started: **True**  
UI entry: `http://127.0.0.1:8766/`  
Preserved Per-Run Archive: `test/history/iter-1/` · `test/eval_report.iter-01.md` · `test/eval_results.iter-01.json`

## Verdict: **PASS** — 151/151 passed (score 100.0%)

| Total | PASS | FAIL | NOT_RUN | ERROR | Optional skipped |
| --: | --: | --: | --: | --: | --: |
| 151 | 151 | 0 | 0 | 0 | 0 |

Guardrail review: **CLEAR** (baseline `iter-0`, pending hunks: 0, state file `test/.guardrail_state.json`)

## Run History & Preserved Per-Iteration Artifacts

| Iter | Timestamp (UTC) | Verdict | PASS / Total | FAIL | NOT_RUN | ERROR | Failed Test IDs | Remediated Test IDs | Preserved Run Artifacts |
| --: | :-- | :-- | --: | --: | --: | --: | :-- | :-- | :-- |
| **1** | `1970-01-01T00:00:00Z` | **PASS** | 151/151 | 0 | 0 | 0 | — | — | `test/history/iter-1/` · `test/eval_report.iter-01.md` · `test/remediation_and_guardrail_audit_report.iter-01.md` |

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
| TC-UI-INTERACT-TAB-01 | Interact | browser | PASS | 829 | — | 5 step(s) passed |
| TC-UI-INTERACT-TAB-02 | Interact | browser | PASS | 852 | — | 5 step(s) passed |
| TC-POS-01 | Positive | browser | PASS | 1042 | — | 10 step(s) passed |
| TC-NEG-01 | Negative | browser | PASS | 934 | — | 11 step(s) passed |
| TC-NEG-02 | Negative | browser | PASS | 1042 | — | 9 step(s) passed |
| TC-UI-INTERACT-02 | Interact | browser | PASS | 1111 | — | 14 step(s) passed |
| TC-EDGE-01 | Edge | browser | PASS | 1761 | — | 11 step(s) passed |
| TC-STATE-01 | State | browser | PASS | 1331 | — | 5 step(s) passed |
| TC-POS-02 | Positive | browser | PASS | 1614 | — | 6 step(s) passed |
| TC-EDGE-02 | Edge | browser | PASS | 1402 | — | 6 step(s) passed |
| TC-EDGE-03 | Edge | browser | PASS | 1294 | — | 5 step(s) passed |
| TC-EDGE-04 | Edge | browser | PASS | 1413 | — | 5 step(s) passed |
| TC-POS-03 | Positive | browser | PASS | 1500 | — | 11 step(s) passed |
| TC-POS-04 | Positive | browser | PASS | 1448 | — | 7 step(s) passed |
| TC-POS-05 | Positive | browser | PASS | 1815 | — | 12 step(s) passed |
| TC-NEG-03 | Negative | browser | PASS | 1804 | — | 12 step(s) passed |
| TC-NEG-04 | Negative | browser | PASS | 1970 | — | 12 step(s) passed |
| TC-NEG-05 | Negative | browser | PASS | 2025 | — | 11 step(s) passed |
| TC-EDGE-05 | Edge | browser | PASS | 1914 | — | 10 step(s) passed |
| TC-EDGE-06 | Edge | browser | PASS | 1723 | — | 10 step(s) passed |
| TC-POS-06 | Positive | browser | PASS | 1789 | — | 12 step(s) passed |
| TC-STATE-02 | State | browser | PASS | 2036 | — | 13 step(s) passed |
| TC-POS-07 | Positive | browser | PASS | 1723 | — | 11 step(s) passed |
| TC-POS-08 | Positive | browser | PASS | 1968 | — | 14 step(s) passed |
| TC-STATE-03 | State | browser | PASS | 1497 | — | 6 step(s) passed |
| TC-STATE-04 | State | browser | PASS | 1476 | — | 6 step(s) passed |
| TC-STATE-05 | State | browser | PASS | 1922 | — | 14 step(s) passed |
| TC-UI-INTERACT-03 | Interact | browser | PASS | 2032 | — | 14 step(s) passed |
| TC-POS-09 | Positive | browser | PASS | 1501 | — | 7 step(s) passed |
| TC-POS-10 | Positive | browser | PASS | 2274 | — | 18 step(s) passed |
| TC-STATE-06 | State | browser | PASS | 1417 | — | 5 step(s) passed |
| TC-UI-INTERACT-04 | Interact | browser | PASS | 1480 | — | 5 step(s) passed |
| TC-EDGE-07 | Edge | browser | PASS | 1497 | — | 5 step(s) passed |
| TC-POS-11 | Positive | browser | PASS | 1911 | — | 15 step(s) passed |
| TC-POS-12 | Positive | browser | PASS | 2404 | — | 18 step(s) passed |
| TC-NEG-06 | Negative | browser | PASS | 2215 | — | 18 step(s) passed |
| TC-POS-13 | Positive | browser | PASS | 2145 | — | 16 step(s) passed |
| TC-STATE-07 | State | browser | PASS | 2166 | — | 16 step(s) passed |
| TC-NEG-07 | Negative | browser | PASS | 1495 | — | 4 step(s) passed |
| TC-STATE-08 | State | browser | PASS | 1966 | — | 12 step(s) passed |
| TC-UI-INTERACT-05 | Interact | browser | PASS | 1655 | — | 8 step(s) passed |
| TC-POS-14 | Positive | browser | PASS | 1329 | — | 5 step(s) passed |
| TC-POS-15 | Positive | browser | PASS | 2283 | — | 18 step(s) passed |
| TC-NEG-08 | Negative | browser | PASS | 2487 | — | 21 step(s) passed |
| TC-POS-16 | Positive | browser | PASS | 2419 | — | 19 step(s) passed |
| TC-STATE-09 | State | browser | PASS | 2626 | — | 20 step(s) passed |
| TC-STATE-10 | State | browser | PASS | 2305 | — | 17 step(s) passed |
| TC-POS-17 | Positive | browser | PASS | 2475 | — | 18 step(s) passed |
| TC-NEG-09 | Negative | browser | PASS | 1713 | — | 5 step(s) passed |
| TC-STATE-11 | State | browser | PASS | 1560 | — | 5 step(s) passed |
| TC-UI-INTERACT-06 | Interact | browser | PASS | 1571 | — | 6 step(s) passed |
| TC-POS-18 | Positive | browser | PASS | 2289 | — | 17 step(s) passed |
| TC-POS-19 | Positive | browser | PASS | 2195 | — | 17 step(s) passed |
| TC-NEG-10 | Negative | http | PASS | 9 | — | 2 http step(s) passed |
| TC-EDGE-08 | Edge | http | PASS | 10 | — | 3 http step(s) passed |
| TC-STATE-12 | State | http | PASS | 9 | — | 2 http step(s) passed |
| TC-STATE-13 | State | http | PASS | 5 | — | 1 http step(s) passed |
| TC-NEG-11 | Negative | http | PASS | 8 | — | 2 http step(s) passed |
| TC-STATE-14 | State | http | PASS | 10 | — | 2 http step(s) passed |
| TC-POS-20 | Positive | browser | PASS | 1783 | — | 14 step(s) passed |
| TC-POS-21 | Positive | browser | PASS | 1783 | — | 6 step(s) passed |
| TC-NEG-12 | Negative | http | PASS | 4 | — | 1 http step(s) passed |
| TC-NEG-13 | Negative | http | PASS | 4 | — | 1 http step(s) passed |
| TC-POS-22 | Positive | http | PASS | 4 | — | 1 http step(s) passed |
| TC-EDGE-09 | Edge | http | PASS | 9 | — | 2 http step(s) passed |
| TC-POS-23 | Positive | browser | PASS | 1479 | — | 3 step(s) passed |
| TC-POS-24 | Positive | browser | PASS | 1670 | — | 4 step(s) passed |
| TC-POS-25 | Positive | browser | PASS | 2306 | — | 11 step(s) passed |
| TC-POS-26 | Positive | browser | PASS | 2180 | — | 16 step(s) passed |
| TC-UI-INTERACT-07 | Interact | browser | PASS | 1088 | — | 5 step(s) passed |
| TC-POS-27 | Positive | browser | PASS | 1332 | — | 4 step(s) passed |
| TC-POS-28 | Positive | browser | PASS | 1166 | — | 5 step(s) passed |
| TC-POS-29 | Positive | browser | PASS | 916 | — | 2 step(s) passed |
| TC-NEG-14 | Negative | browser | PASS | 1364 | — | 8 step(s) passed |
| TC-UI-INTERACT-08 | Interact | browser | PASS | 1079 | — | 7 step(s) passed |
| TC-POS-30 | Positive | http | PASS | 5 | — | 2 http step(s) passed |
| TC-POS-31 | Positive | http | PASS | 2 | — | 1 http step(s) passed |
| TC-POS-32 | Positive | http | PASS | 2 | — | 1 http step(s) passed |
| TC-NEG-15 | Negative | http | PASS | 3 | — | 1 http step(s) passed |
| TC-POS-33 | Positive | http | PASS | 5 | — | 2 http step(s) passed |
| TC-STATE-15 | State | browser | PASS | 1520 | — | 15 step(s) passed |
| TC-STATE-16 | State | browser | PASS | 1578 | — | 18 step(s) passed |
| TC-STATE-17 | State | browser | PASS | 1381 | — | 15 step(s) passed |
| TC-STATE-18 | State | browser | PASS | 1572 | — | 15 step(s) passed |
| TC-STATE-19 | State | browser | PASS | 1504 | — | 16 step(s) passed |
| TC-STATE-20 | State | browser | PASS | 1585 | — | 17 step(s) passed |
| TC-STATE-21 | State | browser | PASS | 1665 | — | 17 step(s) passed |
| TC-STATE-22 | State | browser | PASS | 1743 | — | 19 step(s) passed |
| TC-STATE-23 | State | browser | PASS | 1795 | — | 20 step(s) passed |
| TC-STATE-24 | State | browser | PASS | 1809 | — | 20 step(s) passed |
| TC-STATE-25 | State | browser | PASS | 953 | — | 6 step(s) passed |
| TC-STATE-26 | State | browser | PASS | 1092 | — | 7 step(s) passed |
| TC-STATE-27 | State | browser | PASS | 1099 | — | 10 step(s) passed |
| TC-STATE-28 | State | browser | PASS | 1089 | — | 7 step(s) passed |
| TC-STATE-29 | State | browser | PASS | 1109 | — | 6 step(s) passed |
| TC-STATE-30 | State | browser | PASS | 1017 | — | 6 step(s) passed |
| TC-STATE-31 | State | browser | PASS | 1065 | — | 7 step(s) passed |
| TC-STATE-32 | State | browser | PASS | 1154 | — | 10 step(s) passed |
| TC-STATE-33 | State | browser | PASS | 1079 | — | 7 step(s) passed |
| TC-STATE-34 | State | browser | PASS | 1077 | — | 7 step(s) passed |
| TC-STATE-35 | State | browser | PASS | 953 | — | 6 step(s) passed |
| TC-STATE-36 | State | browser | PASS | 1119 | — | 13 step(s) passed |
| TC-STATE-37 | State | browser | PASS | 1344 | — | 14 step(s) passed |
| TC-STATE-38 | State | browser | PASS | 1329 | — | 17 step(s) passed |
| TC-STATE-39 | State | browser | PASS | 1246 | — | 14 step(s) passed |
| TC-STATE-40 | State | browser | PASS | 1272 | — | 14 step(s) passed |
| TC-STATE-41 | State | browser | PASS | 1187 | — | 13 step(s) passed |
| TC-STATE-42 | State | browser | PASS | 1481 | — | 16 step(s) passed |
| TC-STATE-43 | State | browser | PASS | 1768 | — | 19 step(s) passed |
| TC-STATE-44 | State | browser | PASS | 1693 | — | 19 step(s) passed |
| TC-STATE-45 | State | browser | PASS | 1155 | — | 6 step(s) passed |
| TC-STATE-46 | State | browser | PASS | 903 | — | 4 step(s) passed |
| TC-STATE-47 | State | browser | PASS | 1323 | — | 15 step(s) passed |
| TC-STATE-48 | State | browser | PASS | 1888 | — | 20 step(s) passed |
| TC-STATE-49 | State | browser | PASS | 1095 | — | 7 step(s) passed |
| TC-STATE-50 | State | browser | PASS | 1339 | — | 15 step(s) passed |
| TC-STATE-51 | State | browser | PASS | 853 | — | 4 step(s) passed |
| TC-STATE-52 | State | browser | PASS | 1373 | — | 15 step(s) passed |
| TC-STATE-53 | State | browser | PASS | 1589 | — | 17 step(s) passed |
| TC-STATE-54 | State | browser | PASS | 1029 | — | 7 step(s) passed |
| TC-STATE-55 | State | browser | PASS | 1369 | — | 15 step(s) passed |
| TC-STATE-56 | State | browser | PASS | 892 | — | 4 step(s) passed |
| TC-STATE-57 | State | browser | PASS | 1361 | — | 15 step(s) passed |
| TC-STATE-58 | State | browser | PASS | 1558 | — | 17 step(s) passed |
| TC-STATE-59 | State | browser | PASS | 1789 | — | 20 step(s) passed |
| TC-STATE-60 | State | browser | PASS | 1805 | — | 20 step(s) passed |
| TC-STATE-61 | State | browser | PASS | 1915 | — | 15 step(s) passed |
| TC-POS-JOURNEY-01 | Positive | browser | PASS | 1434 | — | 16 step(s) passed |
| TC-API-01 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-API-02 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-API-03 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-API-04 | Api | http | PASS | 5 | — | 1 http step(s) passed |
| TC-API-05 | Api | http | PASS | 3 | — | 1 http step(s) passed |
| TC-API-06 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-API-07 | Api | http | PASS | 3 | — | 1 http step(s) passed |
| TC-API-08 | Api | http | PASS | 3 | — | 1 http step(s) passed |
| TC-API-09 | Api | http | PASS | 4 | — | 1 http step(s) passed |
| TC-API-10 | Api | http | PASS | 7 | — | 1 http step(s) passed |
| TC-API-11 | Api | http | PASS | 4 | — | 1 http step(s) passed |
| TC-API-12 | Api | http | PASS | 8 | — | 1 http step(s) passed |
| TC-API-13 | Api | http | PASS | 1 | — | 1 http step(s) passed |
| TC-API-14 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-API-15 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-API-16 | Api | http | PASS | 1 | — | 1 http step(s) passed |
| TC-API-17 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-UI-INTERACT-01 | Interact | static | PASS | 0 | — | 2 static step(s) passed over 114 rendered/static text corpus(es) |
| TC-A11Y-01 | A11y | static | PASS | 0 | — | 2 static step(s) passed over 114 rendered/static text corpus(es) |
| TC-UI-LEAK-01 | UiLeak | static | PASS | 12 | — | 2 static step(s) passed over 114 rendered/static text corpus(es) |
| TC-UI-LEAK-02 | UiLeak | static | PASS | 8 | — | 2 static step(s) passed over 114 rendered/static text corpus(es) |
| TC-UI-LEAK-03 | UiLeak | static | PASS | 34 | — | 10 static step(s) passed over 114 rendered/static text corpus(es) |
| TC-UI-LEAK-04 | UiLeak | static | PASS | 8 | — | 3 static step(s) passed over 114 rendered/static text corpus(es) |

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
| Initial landing view (1440x900) | `landing` | `test/.snapshots/iter-1/screenshots/landing-initial.png` |
| Tab 1: [data-testid=tab-my-requests] -> #panel-my-requests | `tab` | `test/.snapshots/iter-1/screenshots/tab-01-tab-my-requests.png` |
| Tab 2: [data-testid=tab-policy-guide] -> #panel-policy-guide | `tab` | `test/.snapshots/iter-1/screenshots/tab-02-tab-policy-guide.png` |
