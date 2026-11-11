#!/usr/bin/env python3
"""Gemini Decisions API (`gemini-decision-1`) zero-dependency control plane for agentic-dlc v4.8.

Evaluates up to 1,000 closed-set programmatic questions (`noul` Yes/No, `choice` multi-option, and `score`
ordered rubric levels `0..N-1`) in a single shared-prefix Tree-Prefill forward pass against:
    POST https://generativelanguage.googleapis.com/v1beta/decisions  (model: models/gemini-decision-1)
at $0.10 / 1M input tokens and $0.00 output tokens, with SHA-256 content-addressed caching in
`<PROJECT_ROOT>/specs/.decisions_cache.json` and deterministic offline fallback when `GEMINI_API_KEY` is unset.

Supported CLI Actions:
  classify-intent     Classify Stage 0 user prompt into specLifecycleMode, ceremonyTrack & scenarioHint
  triage-files        Batch-score Stage 1 repository files for domain rules, workflow states & security sinks
  detect-ambiguities  Evaluate calibrated semantic conflict & uncertainty questions (`pre-spec` | `pre-stories`)
                      to escalate low-confidence (< 0.75) or high-conflict (P >= 0.55) items into `grill-me`
  score-rubric        Two-Tier Hybrid Judge pre-check batching all 20 Spec or Architecture rubric criteria
                      in 1 CreateDecision call so Pro LLM judges focus prose only on failing/uncertain criteria
  route-stories       Score `backlog/user_stories.json` slices to route low-risk slices to Gemini Flash and
                      complex state/security/crypto slices to Gemini Pro + CodeMender verification

Only the Python 3.10+ standard library is used.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dlc_common as dlc  # noqa: E402

DEFAULT_DECISIONS_URL = "https://generativelanguage.googleapis.com/v1beta/decisions"
DEFAULT_DECISIONS_MODEL = "models/gemini-decision-1"
INPUT_COST_PER_1M_USD = 0.10
MAX_QUESTIONS_PER_BATCH = 1000
MAX_SHARED_CHARS = 800_000  # ~200K tokens (< 256K context limit)


def load_env_files(project_root: Path | None = None) -> None:
    """Load GEMINI_API_KEY / DLC_DECISIONS_API_URL from <PROJECT_ROOT>/.env and ~/.gemini/config/agentic-dlc.env."""
    candidates = [Path.home() / ".gemini" / "config" / "agentic-dlc.env"]
    if project_root:
        candidates.insert(0, project_root / ".env")
    for env_path in candidates:
        if not env_path.is_file():
            continue
        for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


# --------------------------------------------------------------------------------------
# Question builders (exact v1beta DecisionService JSON contract)
# --------------------------------------------------------------------------------------
def make_noul_question(question: str, true_desc: str = "", false_desc: str = "") -> dict[str, Any]:
    q: dict[str, Any] = {"question": question}
    if true_desc or false_desc:
        q["criteria"] = {
            "true_description": true_desc or "Yes, clearly evidenced in the provided context.",
            "false_description": false_desc or "No, absent or contradicted by the provided context.",
        }
    return {"noul": q}


def make_choice_question(
    question: str,
    options: dict[str, str],
    include_none_of_above: bool = False,
) -> dict[str, Any]:
    return {
        "choice": {
            "question": question,
            "options": options,
            "include_none_of_above": include_none_of_above,
        }
    }


def make_score_question(question: str, criteria_levels: list[str]) -> dict[str, Any]:
    return {
        "score": {
            "question": question,
            "criteria": criteria_levels,
        }
    }


# --------------------------------------------------------------------------------------
# Answer normalizers (handle snake_case & camelCase v1beta responses uniformly)
# --------------------------------------------------------------------------------------
def _norm_noul_answer(raw: dict[str, Any]) -> dict[str, Any]:
    inner = raw.get("noul") if isinstance(raw.get("noul"), dict) else raw
    p_yes = float(inner.get("p_yes", inner.get("pYes", 1.0 if inner.get("value") else 0.0)))
    p_no = float(inner.get("p_no", inner.get("pNo", max(0.0, 1.0 - p_yes))))
    val = inner.get("value")
    if val is None:
        val = p_yes >= 0.5
    conf = float(inner.get("confidence", max(p_yes, p_no)))
    return {"type": "noul", "value": bool(val), "p_yes": round(p_yes, 4), "p_no": round(p_no, 4), "confidence": round(conf, 4)}


def _norm_choice_answer(raw: dict[str, Any], options: dict[str, str]) -> dict[str, Any]:
    inner = raw.get("choice") if isinstance(raw.get("choice"), dict) else raw
    probs_raw = inner.get("probabilities") or inner.get("optionProbabilities") or {}
    probs = {str(k): round(float(v), 4) for k, v in probs_raw.items()} if isinstance(probs_raw, dict) else {}
    best = inner.get("most_likely_option") or inner.get("mostLikelyOption") or inner.get("choice") or inner.get("value")
    if not best and probs:
        best = max(probs.items(), key=lambda kv: kv[1])[0]
    if not best and options:
        best = next(iter(options.keys()))
    conf = float(inner.get("confidence", probs.get(str(best), 0.75)))
    return {"type": "choice", "choice": str(best or ""), "probabilities": probs, "confidence": round(conf, 4)}


def _norm_score_answer(raw: dict[str, Any], num_levels: int) -> dict[str, Any]:
    inner = raw.get("score") if isinstance(raw.get("score"), dict) else raw
    probs_raw = inner.get("probabilities") or inner.get("levelProbabilities") or []
    if isinstance(probs_raw, list) and probs_raw:
        probs = [round(float(x), 4) for x in probs_raw]
    elif isinstance(probs_raw, dict) and probs_raw:
        probs = [round(float(probs_raw.get(str(i), 0.0)), 4) for i in range(num_levels)]
    else:
        probs = []
    score_val = inner.get("score")
    if score_val is None and probs:
        score_val = sum(idx * p for idx, p in enumerate(probs))
    score_f = float(score_val if score_val is not None else 0.0)
    level = inner.get("most_likely_level", inner.get("mostLikelyLevel"))
    if level is None:
        level = max(range(len(probs)), key=lambda i: probs[i]) if probs else int(round(score_f))
    conf = float(inner.get("confidence", max(probs) if probs else 0.8))
    variance = float(inner.get("variance", 0.0))
    return {
        "type": "score",
        "score": round(score_f, 4),
        "most_likely_level": int(level),
        "max_level": max(0, num_levels - 1),
        "probabilities": probs,
        "variance": round(variance, 4),
        "confidence": round(conf, 4),
    }


def normalize_answers(questions: dict[str, dict[str, Any]], raw_answers: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for qid, qspec in questions.items():
        ans = raw_answers.get(qid) if isinstance(raw_answers, dict) else {}
        if not isinstance(ans, dict):
            ans = {}
        if "noul" in qspec:
            out[qid] = _norm_noul_answer(ans)
        elif "choice" in qspec:
            out[qid] = _norm_choice_answer(ans, qspec["choice"].get("options") or {})
        elif "score" in qspec:
            out[qid] = _norm_score_answer(ans, len(qspec["score"].get("criteria") or []))
    return out


# --------------------------------------------------------------------------------------
# SHA-256 Content-Addressed Cache & HTTP Client
# --------------------------------------------------------------------------------------
def cache_path(root: Path) -> Path:
    return root / "specs" / ".decisions_cache.json"


def _load_cache(root: Path | None) -> dict[str, Any]:
    if root is None:
        return {"entries": {}}
    p = cache_path(root)
    if not p.is_file():
        return {"entries": {}}
    try:
        doc = dlc.read_json(p)
        return doc if isinstance(doc, dict) and isinstance(doc.get("entries"), dict) else {"entries": {}}
    except Exception:
        return {"entries": {}}


def _save_cache(root: Path | None, cache_doc: dict[str, Any]) -> None:
    if root is None:
        return
    p = cache_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Cap cache at 250 entries to stay lightweight
    entries = cache_doc.get("entries") or {}
    if len(entries) > 250:
        keep_keys = list(entries.keys())[-200:]
        cache_doc["entries"] = {k: entries[k] for k in keep_keys}
    dlc.write_json(p, cache_doc)


def estimate_cost(input_text: str) -> dict[str, Any]:
    est_tokens = max(1, math.ceil(len(input_text) / 4))
    cost_usd = round((est_tokens / 1_000_000.0) * INPUT_COST_PER_1M_USD, 6)
    return {
        "estimatedInputTokens": est_tokens,
        "outputTokens": 0,
        "ratePer1MInputTokensUsd": INPUT_COST_PER_1M_USD,
        "estimatedCostUsd": cost_usd,
    }


def evaluate_decisions(
    shared_text: str,
    questions: dict[str, dict[str, Any]],
    *,
    root: Path | None = None,
    offline: bool = False,
    fallback_fn=None,
) -> dict[str, Any]:
    """Call Gemini Decisions API (`POST /v1beta/decisions`) with SHA-256 caching and graceful offline fallback."""
    bounded_text = shared_text[:MAX_SHARED_CHARS]
    model = os.environ.get("DLC_DECISIONS_MODEL") or DEFAULT_DECISIONS_MODEL
    endpoint = os.environ.get("DLC_DECISIONS_API_URL") or DEFAULT_DECISIONS_URL
    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()

    q_items = list(questions.items())[:MAX_QUESTIONS_PER_BATCH]
    bounded_questions = dict(q_items)
    key_material = json.dumps(
        {"model": model, "inputSha256": dlc.sha256_bytes(bounded_text.encode("utf-8")), "questions": bounded_questions},
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    cache_key = dlc.sha256_bytes(key_material)
    cost_meta = estimate_cost(bounded_text)

    if not offline and api_key:
        cache_doc = _load_cache(root)
        cached = (cache_doc.get("entries") or {}).get(cache_key)
        if isinstance(cached, dict) and isinstance(cached.get("answers"), dict):
            return {
                "mode": "cache-hit",
                "model": model,
                "cacheKey": cache_key,
                "questionCount": len(bounded_questions),
                "cost": {**cost_meta, "estimatedCostUsd": 0.0, "cached": True},
                "answers": cached["answers"],
            }

        payload = {
            "model": model,
            "input": [{"role": "user", "parts": [{"text": bounded_text}]}],
            "questions": bounded_questions,
        }
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "x-goog-api-key": api_key,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_json = json.loads(resp.read().decode("utf-8", errors="replace"))
            raw_ans = resp_json.get("answers") or resp_json.get("results") or resp_json.get("decisions") or {}
            norm_ans = normalize_answers(bounded_questions, raw_ans)
            cache_doc.setdefault("entries", {})[cache_key] = {
                "cachedAtUtc": dlc.utc_now_iso(False),
                "questionCount": len(bounded_questions),
                "answers": norm_ans,
            }
            _save_cache(root, cache_doc)
            return {
                "mode": "live-gemini-decision-1",
                "model": model,
                "cacheKey": cache_key,
                "questionCount": len(bounded_questions),
                "cost": {**cost_meta, "cached": False},
                "answers": norm_ans,
            }
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            err_msg = str(exc)[:220]
            dlc.warn(f"Gemini Decisions API call fell back to local deterministic scorer ({err_msg})")
            fallback_reason = f"api_error:{err_msg}"
    else:
        fallback_reason = "offline_flag" if offline else "GEMINI_API_KEY_not_configured"

    answers = fallback_fn(bounded_text, bounded_questions) if fallback_fn else normalize_answers(bounded_questions, {})
    return {
        "mode": "offline-heuristic-fallback",
        "fallbackReason": fallback_reason,
        "model": model,
        "cacheKey": cache_key,
        "questionCount": len(bounded_questions),
        "cost": {"estimatedInputTokens": 0, "outputTokens": 0, "ratePer1MInputTokensUsd": INPUT_COST_PER_1M_USD, "estimatedCostUsd": 0.0, "cached": False},
        "answers": answers,
    }


# --------------------------------------------------------------------------------------
# Action 1: Stage 0 User Intent & Track Classification (`classify-intent`)
# --------------------------------------------------------------------------------------
def classify_intent(prompt_text: str, root: Path | None = None, offline: bool = False) -> dict[str, Any]:
    questions = {
        "lifecycle_mode": make_choice_question(
            "What specification lifecycle mode matches the user's request?",
            {
                "retro-spec": "Reverse engineer or document an existing application into a specification ONLY, without modernizing, rebuilding, or creating backlog stories.",
                "delta": "Add a Phase N+1 enhancement, change request, or new feature delta to an already-built living specification.",
                "standard": "Modernize/rebuild a legacy application into a new target stack OR build a new application end-to-end from requirements.",
            },
        ),
        "ceremony_track": make_choice_question(
            "What governance ceremony track fits the risk and compliance profile of the request?",
            {
                "quick": "Rapid prototype, hackathon demo, or lightweight internal utility requesting minimal human stops.",
                "standard": "Standard enterprise application modernization or greenfield delivery.",
                "regulated": "Regulated public-sector, healthcare (HIPAA), financial/payment (PCI/SOX), or federal (FedRAMP) workload requiring two-person review and Red-Team audit.",
            },
        ),
        "is_reverse_engineer_ambiguous": make_noul_question(
            "Does the user say 'reverse engineer' without clarifying whether they want documentation-only (`retro-spec`) vs. full modernization & rebuild (`standard`)?",
            "User says 'reverse engineer' or 'analyze legacy code' without stating whether to stop at documentation or build modernized code.",
            "User clearly states whether they want documentation-only or full modernization/build.",
        ),
    }

    def _fallback(text: str, qs: dict[str, Any]) -> dict[str, Any]:
        low = text.lower()
        has_rev = bool(re.search(r"\breverse[- ]engineer\b|\bdocument\s+existing\b|\bretro[- ]?spec\b", low))
        has_build = bool(re.search(r"\bmoderniz|\brebuild\b|\bmigrat|\brewrite\b|\btarget\s+stack\b|\bcontainer", low))
        is_delta = bool(re.search(r"\bphase\s*[2-9]|\bdelta\b|\bchange\s+request\b|\badd\s+feature\b", low))
        if has_rev and not has_build:
            l_mode, l_probs = "retro-spec", {"retro-spec": 0.84, "standard": 0.12, "delta": 0.04}
        elif is_delta:
            l_mode, l_probs = "delta", {"delta": 0.85, "standard": 0.12, "retro-spec": 0.03}
        else:
            l_mode, l_probs = "standard", {"standard": 0.88, "retro-spec": 0.07, "delta": 0.05}

        if re.search(r"\bhipaa\b|\bpci\b|\bfedramp\b|\bsox\b|\bregulated\b|\bclassified\b", low):
            track, t_probs = "regulated", {"regulated": 0.9, "standard": 0.08, "quick": 0.02}
        elif re.search(r"\bprototype\b|\bquick\b|\bpoc\b|\bhackathon\b", low):
            track, t_probs = "quick", {"quick": 0.85, "standard": 0.13, "regulated": 0.02}
        else:
            track, t_probs = "standard", {"standard": 0.86, "quick": 0.07, "regulated": 0.07}

        ambig = has_rev and not has_build and "only" not in low and "retro-spec" not in low
        return normalize_answers(qs, {
            "lifecycle_mode": {"most_likely_option": l_mode, "probabilities": l_probs, "confidence": max(l_probs.values())},
            "ceremony_track": {"most_likely_option": track, "probabilities": t_probs, "confidence": max(t_probs.values())},
            "is_reverse_engineer_ambiguous": {"p_yes": 0.78 if ambig else 0.12, "p_no": 0.22 if ambig else 0.88, "value": ambig, "confidence": 0.78 if ambig else 0.88},
        })

    res = evaluate_decisions(prompt_text, questions, root=root, offline=offline, fallback_fn=_fallback)
    ans = res["answers"]
    return {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "action": "classify-intent",
        "executionMode": res["mode"],
        "cost": res["cost"],
        "recommendedSpecLifecycleMode": ans["lifecycle_mode"]["choice"],
        "recommendedCeremonyTrack": ans["ceremony_track"]["choice"],
        "askReverseEngineerDisambiguation": bool(ans["is_reverse_engineer_ambiguous"]["value"]),
        "answers": ans,
    }


# --------------------------------------------------------------------------------------
# Action 2: Stage 1 Large-Repo Map-Reduce File Triage (`triage-files`)
# --------------------------------------------------------------------------------------
def triage_files(root: Path, offline: bool = False) -> dict[str, Any]:
    inv = dlc.load_inventory(root)
    files = [f for f in (inv.get("files") or []) if isinstance(f, dict) and f.get("relativePath")]
    snippets: list[str] = []
    questions: dict[str, dict[str, Any]] = {}

    # Cap at 200 files x 4 questions = 800 questions (within 1,000-question single-call ceiling)
    scoped_files = files[:200]
    file_texts: dict[str, str] = {}
    for idx, f in enumerate(scoped_files):
        rel = str(f["relativePath"])
        p = root / rel
        txt = ""
        if p.is_file() and f.get("sizeBytes", 0) > 0 and p.suffix.lower() not in {".accdb", ".mdb", ".dbf", ".bak", ".sqlite", ".db", ".xlsx", ".xls", ".pdf", ".png", ".jpg"}:
            try:
                txt = p.read_bytes()[:4000].decode("utf-8", errors="replace")
            except OSError:
                txt = ""
        file_texts[rel] = txt
        snippets.append(f"=== FILE [{idx}] {rel} (category={f.get('category')}) ===\n{txt[:1800]}")
        questions[f"f{idx}_rule"] = make_noul_question(f"Does file [{idx}] ({rel}) contain business rules, calculations, fees, or validation logic?")
        questions[f"f{idx}_state"] = make_noul_question(f"Does file [{idx}] ({rel}) define or mutate workflow lifecycle states, statuses, or role approvals?")
        questions[f"f{idx}_sec"] = make_noul_question(f"Does file [{idx}] ({rel}) handle authentication, authorization, SQL execution, deserialization, secrets, or sensitive PII?")

    shared_ctx = "\n\n".join(snippets) if snippets else "No text files scanned."

    def _fallback(_text: str, qs: dict[str, Any]) -> dict[str, Any]:
        raw: dict[str, Any] = {}
        for idx, f in enumerate(scoped_files):
            rel = str(f["relativePath"])
            t = file_texts.get(rel, "")
            has_r = bool(re.search(r"\b(?:if|case|select\s+case|evaluate|decimal|round|fee|rate|threshold|limit|total|validate)\b", t, re.I))
            has_st = bool(re.search(r"\b(?:status|state|approve|reject|submit|review|workflow|role|transition)\b", t, re.I))
            has_sc = bool(re.search(r"\b(?:password|secret|token|auth|login|execute|select\s+|insert\s+|md5|sha1|pickle|deserialize)\b", t, re.I))
            raw[f"f{idx}_rule"] = {"p_yes": 0.82 if has_r else 0.15, "value": has_r, "confidence": 0.82}
            raw[f"f{idx}_state"] = {"p_yes": 0.80 if has_st else 0.15, "value": has_st, "confidence": 0.80}
            raw[f"f{idx}_sec"] = {"p_yes": 0.85 if has_sc else 0.12, "value": has_sc, "confidence": 0.85}
        return normalize_answers(qs, raw)

    res = evaluate_decisions(shared_ctx, questions, root=root, offline=offline, fallback_fn=_fallback) if questions else {
        "mode": "empty", "cost": estimate_cost(""), "answers": {}
    }
    ans = res["answers"]
    triaged: list[dict[str, Any]] = []
    for idx, f in enumerate(scoped_files):
        rel = str(f["relativePath"])
        p_rule = ans.get(f"f{idx}_rule", {}).get("p_yes", 0.0)
        p_state = ans.get(f"f{idx}_state", {}).get("p_yes", 0.0)
        p_sec = ans.get(f"f{idx}_sec", {}).get("p_yes", 0.0)
        priority = round(max(p_rule, p_state, p_sec), 4)
        triaged.append({
            "relativePath": rel,
            "category": f.get("category"),
            "pDomainRule": p_rule,
            "pWorkflowState": p_state,
            "pSecuritySink": p_sec,
            "priorityScore": priority,
            "deepReadRecommended": priority >= 0.35 or f.get("category") in ("legacy_schema", "requirements_doc", "policy"),
            "securityDeepScanRecommended": p_sec >= 0.45,
        })

    out_doc = {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "generatedAtUtc": dlc.utc_now_iso(False),
        "executionMode": res["mode"],
        "cost": res["cost"],
        "totalFilesTriaged": len(triaged),
        "deepReadCount": sum(1 for x in triaged if x["deepReadRecommended"]),
        "securityDeepScanCount": sum(1 for x in triaged if x["securityDeepScanRecommended"]),
        "files": triaged,
    }
    dlc.write_json(root / "specs" / ".decisions_file_triage.json", out_doc)
    return out_doc


# --------------------------------------------------------------------------------------
# Action 3: Semantic Conflict & Calibrated Uncertainty Detector (`detect-ambiguities`)
# --------------------------------------------------------------------------------------
def detect_ambiguities(root: Path, stage: str = "pre-spec", offline: bool = False) -> dict[str, Any]:
    norm_stage = dlc.normalize_clarification_stage(stage)
    parts: list[str] = []
    if norm_stage == "pre-spec":
        disc_p = root / "specs" / "discovery_architecture_and_inventory.md"
        if disc_p.is_file():
            parts.append(f"=== DISCOVERY BLUEPRINT ===\n{dlc.read_text(disc_p)[:30000]}")
        inv_p = root / "specs" / "input_inventory.json"
        if inv_p.is_file():
            inv = dlc.read_json(inv_p)
            for f in (inv.get("files") or [])[:15]:
                fp = root / str(f.get("relativePath") or "")
                if fp.is_file() and fp.suffix.lower() in {".md", ".txt", ".sql", ".bas", ".vb", ".cs", ".java", ".py", ".cbl"}:
                    parts.append(f"=== INPUT {f['relativePath']} ===\n{dlc.read_text(fp)[:6000]}")
    else:
        spec_p = root / "specs" / "application_spec.md"
        if spec_p.is_file():
            parts.append(f"=== APPLICATION SPEC ===\n{dlc.read_text(spec_p)[:50000]}")

    shared_ctx = "\n\n".join(parts) or "Empty stage context."
    questions = {
        "rule_contradiction": make_noul_question(
            "Do any two sections, queries, forms, or rules state conflicting numeric thresholds, rates, SLAs, or approval conditions?",
            "Two or more places give different numbers, formulas, or eligibility conditions for the same concept.",
            "All business rules and thresholds are consistent across the artifacts.",
        ),
        "workflow_role_ambiguity": make_noul_question(
            "Are any workflow transitions missing an explicit authorized actor role, rejection/return path, or prerequisite guard?",
            "At least one workflow transition has an unclear actor role, missing guard, or dead-end rejection handling.",
            "Every workflow transition has an explicit actor role, guard condition, and terminal/return behavior.",
        ),
        "security_trust_gap": make_noul_question(
            "Are authentication, cross-tenant/record-ownership authorization (BOLA), or sensitive field masking rules underspecified for external or privileged roles?",
            "Authentication mechanism, record-level tenant isolation, or PII masking behavior is ambiguous or missing.",
            "Authentication, role/tenant isolation, and data protection rules are explicitly specified.",
        ),
    }

    def _fallback(text: str, qs: dict[str, Any]) -> dict[str, Any]:
        has_conflict = bool(re.search(r"\b(?:CONFLICT|CONTRADICTION|TBD|FIXME|\?\?\?)\b", text, re.I))
        has_assump = bool(re.search(r"\bASSUMPTION-\d+\b", text))
        return normalize_answers(qs, {
            "rule_contradiction": {"p_yes": 0.75 if has_conflict else 0.10, "value": has_conflict, "confidence": 0.85},
            "workflow_role_ambiguity": {"p_yes": 0.65 if has_assump else 0.15, "value": has_assump, "confidence": 0.85},
            "security_trust_gap": {"p_yes": 0.20, "value": False, "confidence": 0.88},
        })

    res = evaluate_decisions(shared_ctx, questions, root=root, offline=offline, fallback_fn=_fallback)
    ans = res["answers"]
    escalated: list[dict[str, Any]] = []
    meta_map = {
        "rule_contradiction": (
            "contradiction-conflict",
            "Semantic contradiction or threshold discrepancy detected across project artifacts — please confirm which business rule / threshold is authoritative.",
            "Adopt the governed policy/specification table formula as authoritative and parameterize thresholds in configuration.",
        ),
        "workflow_role_ambiguity": (
            "workflow-state",
            "Workflow role ownership or rejection/return transition guard has calibrated uncertainty — please confirm actor roles and return-to-draft behavior.",
            "Enforce explicit reviewer role separation and return rejected items to an editable revision state with a mandatory audit reason.",
        ),
        "security_trust_gap": (
            "security-pii",
            "Security trust boundary, record-level tenant isolation (BOLA), or sensitive field masking requires confirmation — what policy should govern access?",
            "Enforce OIDC authentication, strict server-side record-ownership checks on every ID route, and masked-by-default PII rendering.",
        ),
    }
    for qid, (cat, q_text, rec_ans) in meta_map.items():
        item = ans.get(qid, {})
        p_yes = float(item.get("p_yes", 0.0))
        conf = float(item.get("confidence", 1.0))
        if p_yes >= 0.55 or conf < 0.75:
            escalated.append({
                "signalId": qid,
                "category": cat,
                "pConflictOrGap": p_yes,
                "confidence": conf,
                "question": q_text,
                "recommendedAnswer": rec_ans,
            })

    out_doc = {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "generatedAtUtc": dlc.utc_now_iso(False),
        "stage": norm_stage,
        "executionMode": res["mode"],
        "cost": res["cost"],
        "escalateToGrillMe": len(escalated) > 0,
        "escalatedSignals": escalated,
        "answers": ans,
    }
    dlc.write_json(root / "specs" / f".decisions_ambiguities_{norm_stage}.json", out_doc)
    return out_doc


# --------------------------------------------------------------------------------------
# Action 4: Two-Tier Hybrid Rubric Pre-Judge (`score-rubric` for Spec & Architecture)
# --------------------------------------------------------------------------------------
def score_rubric(root: Path, target: str = "spec", offline: bool = False) -> dict[str, Any]:
    if target == "spec":
        rubric = dlc.load_schema("spec_rubric.json")
        spec_p = dlc.require_file(root / "specs" / "application_spec.md", "Stage 2 discovery-architect")
        corpus = dlc.read_text(spec_p)
        out_p = root / "specs" / ".decisions_rubric_precheck.json"
    else:
        rubric = dlc.load_schema("architecture_rubric.json")
        design_files = sorted((root / "design").glob("*.md"))
        if not design_files:
            raise dlc.GateFailure("No design/*.md files found for --target architecture.")
        corpus = "\n\n".join(f"=== {p.name} ===\n{dlc.read_text(p)}" for p in design_files if "scorecard" not in p.name)
        out_p = root / "design" / ".decisions_rubric_precheck.json"

    inv_p = root / "specs" / "input_inventory.json"
    scenario = (dlc.read_json(inv_p).get("inputScenario") if inv_p.is_file() else None) or "SCENARIO_REQUIREMENTS_DOC"

    questions: dict[str, dict[str, Any]] = {}
    applicable_criteria: list[dict[str, Any]] = []
    na_criteria_ids: list[str] = []

    for c in rubric.get("criteria") or []:
        cid = c["id"]
        applies = c.get("appliesTo")
        if applies and scenario not in applies:
            na_criteria_ids.append(cid)
            continue
        applicable_criteria.append(c)
        max_pts = int(c["maxPoints"])
        desc = c.get("description") or c.get("title") or cid
        levels = [f"0/{max_pts} points: Criterion '{c['title']}' is missing or absent ({desc})."]
        for pt in range(1, max_pts):
            levels.append(f"{pt}/{max_pts} points: Criterion '{c['title']}' is partially addressed with minor omissions.")
        levels.append(f"{max_pts}/{max_pts} points: Criterion '{c['title']}' is completely and verifiably satisfied ({desc}).")
        questions[f"score_{cid}"] = make_score_question(
            f"Score rubric criterion {cid} ({c['title']}): {desc}",
            levels,
        )
        if c.get("blocking"):
            questions[f"block_{cid}"] = make_noul_question(
                f"Does the document satisfy blocking criterion {cid} ({c['title']}) with concrete, non-placeholder content?",
                f"Yes, {cid} is substantively satisfied.",
                f"No, {cid} is completely missing or placeholder-only.",
            )

    def _fallback(text: str, qs: dict[str, Any]) -> dict[str, Any]:
        raw: dict[str, Any] = {}
        low = text.lower()
        for c in applicable_criteria:
            cid = c["id"]
            max_pts = int(c["maxPoints"])
            title_words = [w for w in re.findall(r"[a-z]{4,}", (c.get("title") or "").lower()) if w not in {"with", "from", "that", "this"}]
            hits = sum(1 for w in title_words if w in low)
            ratio = (hits / len(title_words)) if title_words else 1.0
            est = max_pts if ratio >= 0.5 else max(1, max_pts // 2)
            raw[f"score_{cid}"] = {"score": float(est), "most_likely_level": est, "confidence": 0.85 if ratio >= 0.5 else 0.65}
            if c.get("blocking"):
                raw[f"block_{cid}"] = {"p_yes": 0.9 if est > 0 else 0.1, "value": est > 0, "confidence": 0.88}
        return normalize_answers(qs, raw)

    res = evaluate_decisions(corpus, questions, root=root, offline=offline, fallback_fn=_fallback)
    ans = res["answers"]

    scored_items: list[dict[str, Any]] = []
    needs_pro_review: list[str] = []
    est_total = 0

    for cid in na_criteria_ids:
        rc = next(x for x in rubric["criteria"] if x["id"] == cid)
        est_total += int(rc["maxPoints"])
        scored_items.append({
            "id": cid,
            "maxPoints": int(rc["maxPoints"]),
            "estimatedAwarded": int(rc["maxPoints"]),
            "confidence": 1.0,
            "notApplicableAutoFull": True,
            "needsProGenerativeCritique": False,
        })

    for c in applicable_criteria:
        cid = c["id"]
        max_pts = int(c["maxPoints"])
        s_ans = ans.get(f"score_{cid}", {})
        b_ans = ans.get(f"block_{cid}", {})
        est_award = int(round(float(s_ans.get("score", max_pts))))
        est_award = max(0, min(max_pts, est_award))
        if c.get("blocking") and b_ans and not b_ans.get("value", True):
            est_award = 0
        conf = float(s_ans.get("confidence", 0.8))
        needs_pro = (est_award < max_pts) or (conf < 0.80)
        if needs_pro:
            needs_pro_review.append(cid)
        est_total += est_award
        scored_items.append({
            "id": cid,
            "title": c.get("title"),
            "maxPoints": max_pts,
            "estimatedAwarded": est_award,
            "weightedScore": s_ans.get("score"),
            "confidence": conf,
            "blocking": bool(c.get("blocking")),
            "needsProGenerativeCritique": needs_pro,
        })

    out_doc = {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "generatedAtUtc": dlc.utc_now_iso(False),
        "target": target,
        "executionMode": res["mode"],
        "cost": res["cost"],
        "estimatedTotalScore": est_total,
        "passingScore": rubric.get("passingScore", 90),
        "totalCriteria": len(scored_items),
        "criteriaNeedingProReviewCount": len(needs_pro_review),
        "criteriaNeedingProReview": needs_pro_review,
        "criteria": scored_items,
    }
    out_p.parent.mkdir(parents=True, exist_ok=True)
    dlc.write_json(out_p, out_doc)
    return out_doc


# --------------------------------------------------------------------------------------
# Action 5: Cost- & Security-Aware Per-Story Model Router (`route-stories`)
# --------------------------------------------------------------------------------------
def route_stories(root: Path, offline: bool = False) -> dict[str, Any]:
    stories = dlc.load_stories(root)
    story_blobs: list[str] = []
    questions: dict[str, dict[str, Any]] = {}

    for s in stories[:250]:
        sid = str(s["id"])
        acs = "; ".join(f"[{a.get('tag')}] {a.get('when')} -> {a.get('then')}" for a in (s.get("acceptanceCriteria") or [])[:6])
        story_blobs.append(
            f"=== STORY {sid}: {s.get('title')} (points={s.get('storyPoints')}, reqs={s.get('requirementRefs')}, rules={s.get('businessRuleRefs')}) ===\n{acs}"
        )
        questions[f"{sid}_tier"] = make_choice_question(
            f"Which coding model tier is cost-optimal for implementing story {sid} without sacrificing correctness?",
            {
                "flash": "Standard CRUD endpoint, read-only queue/list UI, static configuration, or straightforward form binding.",
                "pro": "Complex multi-state workflow guard, RBAC/BOLA security boundary, cryptographic/masking logic, financial/decimal calculation, or cross-service integration.",
            },
        )
        questions[f"{sid}_sec"] = make_score_question(
            f"Rate the security criticality of story {sid} from 0 (low) to 3 (critical):",
            [
                "0: Pure presentation, styling, or non-sensitive static scaffolding.",
                "1: Standard authenticated read or non-privileged form validation.",
                "2: Mutates business state, enforces role visibility, or processes user-supplied query/body parameters.",
                "3: Enforces authentication/authorization boundaries, tenant isolation, PII masking, cryptography, or external webhook/payment integration.",
            ],
        )

    shared_ctx = "\n\n".join(story_blobs)

    def _fallback(_text: str, qs: dict[str, Any]) -> dict[str, Any]:
        raw: dict[str, Any] = {}
        for s in stories[:250]:
            sid = str(s["id"])
            blob = json.dumps(s).lower()
            reqs = " ".join(str(r) for r in (s.get("requirementRefs") or []))
            has_sec_req = "REQ-SEC" in reqs or bool(re.search(r"\b(?:auth|rbac|permission|mask|encrypt|token|bola|security|secret|audit)\b", blob))
            has_complex = has_sec_req or bool(s.get("businessRuleRefs")) or int(s.get("storyPoints") or 3) >= 5 or bool(re.search(r"\b(?:transition|approve|reject|certify|state)\b", blob))
            sec_lvl = 3 if has_sec_req else (2 if has_complex else 1)
            tier = "pro" if (sec_lvl >= 2 or has_complex) else "flash"
            raw[f"{sid}_tier"] = {"most_likely_option": tier, "probabilities": {"pro": 0.85 if tier == "pro" else 0.2, "flash": 0.8 if tier == "flash" else 0.15}, "confidence": 0.84}
            raw[f"{sid}_sec"] = {"score": float(sec_lvl), "most_likely_level": sec_lvl, "confidence": 0.85}
        return normalize_answers(qs, raw)

    res = evaluate_decisions(shared_ctx, questions, root=root, offline=offline, fallback_fn=_fallback)
    ans = res["answers"]

    routes: list[dict[str, Any]] = []
    for s in stories[:250]:
        sid = str(s["id"])
        t_ans = ans.get(f"{sid}_tier", {})
        sc_ans = ans.get(f"{sid}_sec", {})
        sec_score = float(sc_ans.get("score", 1.0))
        tier = "pro" if (t_ans.get("choice") == "pro" or sec_score >= 2.0) else "flash"
        routes.append({
            "storyId": sid,
            "title": s.get("title"),
            "recommendedModelTier": tier,
            "securityCriticalityScore": round(sec_score, 2),
            "requiresCodeMenderVerify": sec_score >= 2.0,
            "confidence": t_ans.get("confidence", 0.8),
        })

    flash_cnt = sum(1 for r in routes if r["recommendedModelTier"] == "flash")
    pro_cnt = sum(1 for r in routes if r["recommendedModelTier"] == "pro")
    out_doc = {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "generatedAtUtc": dlc.utc_now_iso(False),
        "executionMode": res["mode"],
        "cost": res["cost"],
        "totalStories": len(routes),
        "flashStoryCount": flash_cnt,
        "proStoryCount": pro_cnt,
        "routes": routes,
    }
    dlc.write_json(root / "specs" / ".story_model_routing.json", out_doc)
    return out_doc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument(
        "--action",
        required=True,
        choices=["classify-intent", "triage-files", "detect-ambiguities", "score-rubric", "route-stories"],
    )
    ap.add_argument("--prompt", default="", help="User prompt text for --action classify-intent")
    ap.add_argument("--stage", default="pre-spec", choices=["pre-spec", "pre-stories", "stage4a"])
    ap.add_argument("--target", default="spec", choices=["spec", "architecture"])
    ap.add_argument("--offline", action="store_true", help="Force local deterministic scorer without network calls")
    args = ap.parse_args()

    root: Path | None = None
    if args.project_root or args.action != "classify-intent":
        root = dlc.resolve_project_root(args.project_root)
    load_env_files(root)

    if args.action == "classify-intent":
        out = classify_intent(args.prompt, root=root, offline=args.offline)
    elif args.action == "triage-files":
        assert root is not None
        out = triage_files(root, offline=args.offline)
    elif args.action == "detect-ambiguities":
        assert root is not None
        out = detect_ambiguities(root, stage=args.stage, offline=args.offline)
    elif args.action == "score-rubric":
        assert root is not None
        out = score_rubric(root, target=args.target, offline=args.offline)
    else:
        assert root is not None
        out = route_stories(root, offline=args.offline)

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
