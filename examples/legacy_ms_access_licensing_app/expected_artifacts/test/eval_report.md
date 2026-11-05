# Closed-Loop Evaluation Report — Iteration 1

Generated: 2026-11-05T18:04:08Z  
Project: `dlc_sync_legacy_ms_access_licensing_app_gahxvkn3`  
Browser runtime: **chrome-headless** (/usr/bin/google-chrome)  
Backend started: **True**  
UI entry: `http://127.0.0.1:8767/`  
Preserved Per-Run Archive: `test/history/iter-1/` · `test/eval_report.iter-01.md` · `test/eval_results.iter-01.json`

## Verdict: **PASS** — 136/136 passed (score 100.0%)

| Total | PASS | FAIL | NOT_RUN | ERROR | Optional skipped |
| --: | --: | --: | --: | --: | --: |
| 136 | 136 | 0 | 0 | 0 | 0 |

Guardrail review: **CLEAR** (baseline `iter-0`, pending hunks: 0)

## Run History & Preserved Per-Iteration Artifacts

| Iter | Timestamp (UTC) | Verdict | PASS / Total | FAIL | NOT_RUN | ERROR | Failed Test IDs | Remediated Test IDs | Preserved Run Artifacts |
| --: | :-- | :-- | --: | --: | --: | --: | :-- | :-- | :-- |
| **1** | `2026-11-05T18:04:08Z` | **PASS** | 136/136 | 0 | 0 | 0 | — | — | `test/history/iter-1/` · `test/eval_report.iter-01.md` · `test/remediation_and_guardrail_audit_report.iter-01.md` |

## Per category

| Category | Total | PASS | FAIL | NOT_RUN | ERROR |
| :-- | --: | --: | --: | --: | --: |
| A11y | 1 | 1 | 0 | 0 | 0 |
| Api | 20 | 20 | 0 | 0 | 0 |
| Edge | 6 | 6 | 0 | 0 | 0 |
| Interact | 13 | 13 | 0 | 0 | 0 |
| Negative | 24 | 24 | 0 | 0 | 0 |
| Positive | 47 | 47 | 0 | 0 | 0 |
| State | 21 | 21 | 0 | 0 | 0 |
| UiLeak | 4 | 4 | 0 | 0 | 0 |

## All results

| Test ID | Category | Runtime | Status | ms | Failed step | Message |
| :-- | :-- | :-- | :-- | --: | :-- | :-- |
| TC-UI-INTERACT-TAB-01 | Interact | browser | PASS | 992 | — | 9 step(s) passed |
| TC-UI-INTERACT-TAB-02 | Interact | browser | PASS | 780 | — | 9 step(s) passed |
| TC-UI-INTERACT-TAB-03 | Interact | browser | PASS | 849 | — | 9 step(s) passed |
| TC-UI-INTERACT-TAB-04 | Interact | browser | PASS | 973 | — | 10 step(s) passed |
| TC-UI-INTERACT-TAB-05 | Interact | browser | PASS | 868 | — | 10 step(s) passed |
| TC-UI-INTERACT-TAB-06 | Interact | browser | PASS | 890 | — | 10 step(s) passed |
| TC-POS-01 | Positive | browser | PASS | 937 | — | 18 step(s) passed |
| TC-NEG-01 | Negative | browser | PASS | 847 | — | 9 step(s) passed |
| TC-NEG-02 | Negative | browser | PASS | 872 | — | 11 step(s) passed |
| TC-POS-02 | Positive | browser | PASS | 892 | — | 12 step(s) passed |
| TC-UI-INTERACT-02 | Interact | browser | PASS | 881 | — | 19 step(s) passed |
| TC-POS-03 | Positive | browser | PASS | 856 | — | 7 step(s) passed |
| TC-POS-04 | Positive | browser | PASS | 896 | — | 11 step(s) passed |
| TC-EDGE-01 | Edge | browser | PASS | 859 | — | 11 step(s) passed |
| TC-EDGE-02 | Edge | browser | PASS | 908 | — | 11 step(s) passed |
| TC-EDGE-03 | Edge | browser | PASS | 851 | — | 12 step(s) passed |
| TC-POS-05 | Positive | browser | PASS | 844 | — | 13 step(s) passed |
| TC-NEG-03 | Negative | browser | PASS | 833 | — | 15 step(s) passed |
| TC-POS-06 | Positive | browser | PASS | 904 | — | 19 step(s) passed |
| TC-POS-07 | Positive | browser | PASS | 1025 | — | 24 step(s) passed |
| TC-NEG-04 | Negative | browser | PASS | 1192 | — | 22 step(s) passed |
| TC-NEG-05 | Negative | browser | PASS | 1026 | — | 22 step(s) passed |
| TC-NEG-06 | Negative | browser | PASS | 936 | — | 21 step(s) passed |
| TC-POS-08 | Positive | browser | PASS | 1046 | — | 15 step(s) passed |
| TC-NEG-07 | Negative | browser | PASS | 935 | — | 9 step(s) passed |
| TC-EDGE-04 | Edge | browser | PASS | 1044 | — | 28 step(s) passed |
| TC-POS-09 | Positive | browser | PASS | 1059 | — | 21 step(s) passed |
| TC-NEG-08 | Negative | browser | PASS | 1054 | — | 21 step(s) passed |
| TC-NEG-09 | Negative | browser | PASS | 944 | — | 16 step(s) passed |
| TC-STATE-01 | State | browser | PASS | 855 | — | 8 step(s) passed |
| TC-UI-INTERACT-03 | Interact | browser | PASS | 981 | — | 21 step(s) passed |
| TC-POS-10 | Positive | browser | PASS | 841 | — | 9 step(s) passed |
| TC-POS-11 | Positive | browser | PASS | 901 | — | 6 step(s) passed |
| TC-POS-12 | Positive | browser | PASS | 858 | — | 12 step(s) passed |
| TC-STATE-02 | State | browser | PASS | 829 | — | 6 step(s) passed |
| TC-UI-INTERACT-04 | Interact | browser | PASS | 1040 | — | 11 step(s) passed |
| TC-POS-13 | Positive | browser | PASS | 964 | — | 11 step(s) passed |
| TC-POS-14 | Positive | browser | PASS | 971 | — | 10 step(s) passed |
| TC-NEG-10 | Negative | browser | PASS | 949 | — | 9 step(s) passed |
| TC-STATE-03 | State | browser | PASS | 946 | — | 9 step(s) passed |
| TC-POS-15 | Positive | browser | PASS | 1040 | — | 10 step(s) passed |
| TC-UI-INTERACT-05 | Interact | browser | PASS | 1029 | — | 9 step(s) passed |
| TC-STATE-04 | State | browser | PASS | 1130 | — | 8 step(s) passed |
| TC-POS-16 | Positive | browser | PASS | 953 | — | 10 step(s) passed |
| TC-NEG-11 | Negative | browser | PASS | 939 | — | 9 step(s) passed |
| TC-POS-17 | Positive | browser | PASS | 858 | — | 10 step(s) passed |
| TC-STATE-05 | State | browser | PASS | 965 | — | 9 step(s) passed |
| TC-POS-18 | Positive | browser | PASS | 814 | — | 10 step(s) passed |
| TC-POS-19 | Positive | browser | PASS | 846 | — | 8 step(s) passed |
| TC-POS-20 | Positive | browser | PASS | 876 | — | 7 step(s) passed |
| TC-POS-21 | Positive | browser | PASS | 951 | — | 7 step(s) passed |
| TC-POS-22 | Positive | browser | PASS | 1142 | — | 9 step(s) passed |
| TC-NEG-12 | Negative | browser | PASS | 961 | — | 8 step(s) passed |
| TC-STATE-06 | State | browser | PASS | 1117 | — | 6 step(s) passed |
| TC-POS-23 | Positive | browser | PASS | 966 | — | 11 step(s) passed |
| TC-NEG-13 | Negative | browser | PASS | 915 | — | 10 step(s) passed |
| TC-POS-24 | Positive | browser | PASS | 1008 | — | 8 step(s) passed |
| TC-UI-INTERACT-06 | Interact | browser | PASS | 1072 | — | 23 step(s) passed |
| TC-POS-25 | Positive | browser | PASS | 838 | — | 5 step(s) passed |
| TC-EDGE-05 | Edge | browser | PASS | 804 | — | 5 step(s) passed |
| TC-EDGE-06 | Edge | browser | PASS | 783 | — | 5 step(s) passed |
| TC-POS-26 | Positive | browser | PASS | 974 | — | 11 step(s) passed |
| TC-NEG-14 | Negative | browser | PASS | 857 | — | 8 step(s) passed |
| TC-STATE-07 | State | browser | PASS | 882 | — | 9 step(s) passed |
| TC-NEG-15 | Negative | http | PASS | 7 | — | 2 http step(s) passed |
| TC-STATE-08 | State | http | PASS | 6 | — | 2 http step(s) passed |
| TC-NEG-16 | Negative | http | PASS | 2 | — | 1 http step(s) passed |
| TC-POS-27 | Positive | http | PASS | 4 | — | 1 http step(s) passed |
| TC-NEG-17 | Negative | http | PASS | 1 | — | 1 http step(s) passed |
| TC-STATE-09 | State | browser | PASS | 761 | — | 6 step(s) passed |
| TC-POS-28 | Positive | http | PASS | 3 | — | 1 http step(s) passed |
| TC-POS-29 | Positive | http | PASS | 7 | — | 2 http step(s) passed |
| TC-NEG-18 | Negative | http | PASS | 1 | — | 1 http step(s) passed |
| TC-POS-31 | Positive | http | PASS | 14 | — | 5 http step(s) passed |
| TC-NEG-19 | Negative | http | PASS | 1 | — | 1 http step(s) passed |
| TC-NEG-20 | Negative | http | PASS | 1 | — | 1 http step(s) passed |
| TC-NEG-21 | Negative | http | PASS | 2 | — | 1 http step(s) passed |
| TC-POS-33 | Positive | browser | PASS | 825 | — | 5 step(s) passed |
| TC-POS-34 | Positive | browser | PASS | 843 | — | 6 step(s) passed |
| TC-POS-35 | Positive | browser | PASS | 883 | — | 12 step(s) passed |
| TC-POS-36 | Positive | browser | PASS | 899 | — | 7 step(s) passed |
| TC-POS-37 | Positive | browser | PASS | 933 | — | 22 step(s) passed |
| TC-POS-38 | Positive | browser | PASS | 798 | — | 4 step(s) passed |
| TC-POS-39 | Positive | browser | PASS | 857 | — | 5 step(s) passed |
| TC-POS-40 | Positive | static | PASS | 4 | — | 2 static step(s) passed over 1 rendered/static text corpus(es) |
| TC-POS-41 | Positive | http | PASS | 5 | — | 2 http step(s) passed |
| TC-POS-42 | Positive | http | PASS | 2 | — | 1 http step(s) passed |
| TC-POS-43 | Positive | http | PASS | 1 | — | 1 http step(s) passed |
| TC-NEG-22 | Negative | http | PASS | 2 | — | 1 http step(s) passed |
| TC-POS-44 | Positive | http | PASS | 1 | — | 1 http step(s) passed |
| TC-POS-46 | Positive | http | PASS | 3 | — | 1 http step(s) passed |
| TC-NEG-23 | Negative | http | PASS | 1 | — | 1 http step(s) passed |
| TC-NEG-24 | Negative | http | PASS | 1 | — | 1 http step(s) passed |
| TC-STATE-10 | State | browser | PASS | 991 | — | 8 step(s) passed |
| TC-STATE-11 | State | browser | PASS | 963 | — | 8 step(s) passed |
| TC-STATE-12 | State | browser | PASS | 884 | — | 8 step(s) passed |
| TC-STATE-13 | State | browser | PASS | 878 | — | 8 step(s) passed |
| TC-STATE-14 | State | browser | PASS | 886 | — | 8 step(s) passed |
| TC-STATE-15 | State | browser | PASS | 927 | — | 8 step(s) passed |
| TC-STATE-16 | State | browser | PASS | 891 | — | 8 step(s) passed |
| TC-STATE-17 | State | browser | PASS | 995 | — | 8 step(s) passed |
| TC-STATE-18 | State | browser | PASS | 982 | — | 8 step(s) passed |
| TC-STATE-19 | State | browser | PASS | 872 | — | 9 step(s) passed |
| TC-STATE-20 | State | browser | PASS | 855 | — | 9 step(s) passed |
| TC-STATE-21 | State | browser | PASS | 934 | — | 9 step(s) passed |
| TC-POS-JOURNEY-01 | Positive | browser | PASS | 1082 | — | 22 step(s) passed |
| TC-API-01 | Api | http | PASS | 3 | — | 1 http step(s) passed |
| TC-API-02 | Api | http | PASS | 3 | — | 1 http step(s) passed |
| TC-API-03 | Api | http | PASS | 5 | — | 1 http step(s) passed |
| TC-API-04 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-API-05 | Api | http | PASS | 3 | — | 1 http step(s) passed |
| TC-API-06 | Api | http | PASS | 3 | — | 1 http step(s) passed |
| TC-API-07 | Api | http | PASS | 4 | — | 1 http step(s) passed |
| TC-API-08 | Api | http | PASS | 3 | — | 1 http step(s) passed |
| TC-API-09 | Api | http | PASS | 4 | — | 1 http step(s) passed |
| TC-API-10 | Api | http | PASS | 4 | — | 1 http step(s) passed |
| TC-API-11 | Api | http | PASS | 3 | — | 1 http step(s) passed |
| TC-API-12 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-API-13 | Api | http | PASS | 4 | — | 1 http step(s) passed |
| TC-API-14 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-API-15 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-API-16 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-API-17 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-API-18 | Api | http | PASS | 3 | — | 1 http step(s) passed |
| TC-API-19 | Api | http | PASS | 2 | — | 1 http step(s) passed |
| TC-API-20 | Api | http | PASS | 1 | — | 1 http step(s) passed |
| TC-UI-INTERACT-01 | Interact | static | PASS | 0 | — | 2 static step(s) passed over 86 rendered/static text corpus(es) |
| TC-A11Y-01 | A11y | static | PASS | 0 | — | 2 static step(s) passed over 86 rendered/static text corpus(es) |
| TC-POS-30 | Positive | static | PASS | 33 | — | 15 static step(s) passed over 86 rendered/static text corpus(es) |
| TC-POS-32 | Positive | static | PASS | 0 | — | 2 static step(s) passed over 86 rendered/static text corpus(es) |
| TC-UI-INTERACT-07 | Interact | static | PASS | 0 | — | 2 static step(s) passed over 86 rendered/static text corpus(es) |
| TC-POS-45 | Positive | static | PASS | 5 | — | 2 static step(s) passed over 86 rendered/static text corpus(es) |
| TC-UI-LEAK-01 | UiLeak | static | PASS | 5 | — | 2 static step(s) passed over 86 rendered/static text corpus(es) |
| TC-UI-LEAK-02 | UiLeak | static | PASS | 3 | — | 2 static step(s) passed over 86 rendered/static text corpus(es) |
| TC-UI-LEAK-03 | UiLeak | static | PASS | 22 | — | 11 static step(s) passed over 86 rendered/static text corpus(es) |
| TC-UI-LEAK-04 | UiLeak | static | PASS | 4 | — | 3 static step(s) passed over 86 rendered/static text corpus(es) |

## Failures (expected vs actual)

None.
## Zero-leakage scan (TC-UI-LEAK-01..04)

Tokens scanned: 134 · exact hits: **0** · heuristic warnings: 0

## Interactive control audit (TC-UI-INTERACT-01)

Controls observed across all reached DOM states: 34 · unwired: **0**

## Accessibility lint (TC-A11Y-01)

Findings: **0**

## UX guardrail metrics (TC-UX-SIMPLE-01..03)

- Max visible primary buttons on one screen: 1 (≤ 1) ['[data-testid=step1-continue-btn]']
- Max visible tabs/nav items: 3 (≤ 3)
- Max visible inputs outside `<details>` in one step container: 5 (≤ 5) in `[data-testid=step-1]`
- Main container max-width: 800px

## Visual evidence & viewport screenshots

| View / Capture | Kind | Artifact Path |
| :-- | :-- | :-- |
| Initial landing view (1440x900) | `landing` | `test/history/iter-1/screenshots/landing-initial.png` |
| Tab 1: [data-testid=tab-new-application] -> #panel-new-application | `tab` | `test/history/iter-1/screenshots/tab-01-tab-new-application.png` |
| Tab 2: [data-testid=tab-my-applications] -> #panel-my-applications | `tab` | `test/history/iter-1/screenshots/tab-02-tab-my-applications.png` |
| Tab 3: [data-testid=tab-fee-calculator] -> #panel-fee-calculator | `tab` | `test/history/iter-1/screenshots/tab-03-tab-fee-calculator.png` |
| Tab 4: [data-testid=tab-review-queue] -> #panel-review-queue | `tab` | `test/history/iter-1/screenshots/tab-04-tab-review-queue.png` |
| Tab 5: [data-testid=tab-buyers] -> #panel-buyers | `tab` | `test/history/iter-1/screenshots/tab-05-tab-buyers.png` |
| Tab 6: [data-testid=tab-agents] -> #panel-agents | `tab` | `test/history/iter-1/screenshots/tab-06-tab-agents.png` |
