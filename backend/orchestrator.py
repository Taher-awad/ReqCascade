"""Cascading Waterfall Pipeline Orchestrator.

Pipeline: Raw Text → Atomics → Business Reqs → HLFRs → LLFRs → Test Reqs → Test Cases
Each stage feeds the next. Dual-gate validation (semantic + LLM critic) between every stage.
Demo pruning: first 2 BRs, first HLFR, first LLFR expanded to full depth.
"""
import asyncio
import json
import time
import re
import logging
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

from prompts import (
    PREPROCESSOR_PROMPT,
    BUSINESS_REQ_PROMPT,
    HLFR_PROMPT,
    LLFR_PROMPT,
    TEST_REQ_PROMPT,
    TEST_CASE_PROMPT,
    CRITIC_PROMPT,
    STAGE_CRITIC_CONTEXT,
    STAGE_META,
)
import gemini_client as llm_client
from validator import semantic_validator

MAX_VALIDATION_RETRIES = 4

# ── Gate thresholds per stage depth ──────────────────────────────
GATE_A_THRESHOLDS = {
    "atomics": 0.55,
    "br": 0.55,
    "hlfr": 0.50,
    "llfr": 0.50,
    "tr": 0.45,
    "tc": 0.45,
}
GATE_B_THRESHOLD = 7   # Default Gate B minimum score (out of 10)

# Stage-aware Gate B thresholds — deeper stages legitimately introduce
# implementation detail not in the parent, so the critic is calibrated lower.
GATE_B_THRESHOLDS = {
    "br":   7,   # Must faithfully represent the raw atomic requirement
    "hlfr": 7,   # Must faithfully represent the business requirement
    "llfr": 6,   # Allowed to add logical impl steps not explicit in HLFR
    "tr":   5,   # Translating LLFR to test goals introduces test-specific framing
    "tc":   5,   # Step-by-step test steps inherently diverge from abstract TR
}

# ── Node ID counters (lock-protected for parallel safety) ────────
_node_counter = 0
_node_counter_lock = asyncio.Lock()

async def _next_id(prefix: str) -> str:
    global _node_counter
    async with _node_counter_lock:
        _node_counter += 1
        return f"{prefix}-{_node_counter}"


async def run_pipeline(
    input_text: str,
    model: str = "gemini-2.5-flash",
) -> AsyncGenerator[dict, None]:
    """
    Execute the cascading waterfall pipeline as an async generator of SSE events.

    Pipeline: Input → Atomics → BRs → HLFRs → LLFRs → TRs → TCs
    Demo pruning: first 2 BRs expanded, first HLFR, first LLFR → all TRs → all TCs.
    """
    global _node_counter
    _node_counter = 0

    pipeline_start = time.time()
    gate_stats = {"passed": 0, "failed": 0, "total": 0, "scores_a": [], "scores_b": []}


    # ── STAGE 0: ATOMIC DECOMPOSITION ────────────────────────────
    yield _event("stage_start", {"stage": "atomics", **STAGE_META["atomics"]})

    full_text = ""
    async for chunk in llm_client.generate(
        model=model,
        system_prompt=PREPROCESSOR_PROMPT,
        user_prompt=input_text,
        temperature=0.1,
        format="json",
    ):
        full_text += chunk
        yield _event("stage_chunk", {"stage": "atomics", "text": chunk})

    atomic_requirements = _parse_requirements(full_text)

    # Gate 0: validate atomics capture the full input
    combined_atomics = " ".join(atomic_requirements)
    gate_a_0 = semantic_validator.calculate_trace_score(input_text, combined_atomics)
    gate_stats["scores_a"].append(gate_a_0)
    gate_stats["total"] += 1
    if gate_a_0 >= GATE_A_THRESHOLDS["atomics"]:
        gate_stats["passed"] += 1

    yield _event("stage_complete", {
        "stage": "atomics",
        "requirements": atomic_requirements,
        "count": len(atomic_requirements),
        "gate_a": round(gate_a_0, 4),
    })

    # ── STAGE 1: BUSINESS REQUIREMENTS (all atomics — PARALLEL) ────
    yield _event("stage_start", {"stage": "br", **STAGE_META["br"]})

    async def _generate_br(i, ar):
        """Generate a single BR with retry loop — runs in parallel."""
        br_id = f"BR-{i+1}"
        critic_feedback = ""
        prompt_used = ""
        for retry in range(MAX_VALIDATION_RETRIES):
            br_data, prompt_used = await _stage_generate(BUSINESS_REQ_PROMPT, ar, model, context_str=ar, critic_feedback=critic_feedback)
            if isinstance(br_data, dict):
                br_data["br_id"] = br_id
            else:
                br_data = {"br_id": br_id, "business_rule": str(br_data), "business_objective": str(br_data)}

            source_text = ar
            target_text = br_data.get("business_rule", "") + " " + br_data.get("acceptance_criteria", "")
            gate_a, gate_b, passed = await _dual_gate_validate(source_text, target_text, "br", model, gate_stats)
            
            if passed:
                break
            critic_feedback = f"Issues: {', '.join(gate_b.get('issues', []))}\nMissing: {', '.join(gate_b.get('missing_elements', []))}"

        return {
            "data": br_data, "gate_a": gate_a, "gate_b": gate_b,
            "source": ar, "passed": passed, "br_id": br_id, "index": i,
            "prompt_used": prompt_used,
        }

    # Launch all BRs in parallel (semaphore limits to 4 concurrent API calls)
    br_tasks = [_generate_br(i, ar) for i, ar in enumerate(atomic_requirements)]
    br_results = await asyncio.gather(*br_tasks, return_exceptions=True)

    business_reqs = []
    for result in br_results:
        if isinstance(result, Exception):
            logger.error(f"BR generation failed: {result}")
            continue
        business_reqs.append(result)
        yield _event("node_complete", {
            "stage": "br",
            "id": result["br_id"],
            "parent_id": "root",
            "data": result["data"],
            "gate_a": round(result["gate_a"], 4),
            "gate_b": result["gate_b"],
            "passed": result["passed"],
            "prompt_used": result.get("prompt_used", ""),
            "label": result["data"].get("business_objective", result["source"])[:80],
        })

    yield _event("stage_complete", {"stage": "br", "count": len(business_reqs)})

    # ── STAGE 2: HLFRs (first 2 BRs, rest pruned) ───────────────
    yield _event("stage_start", {"stage": "hlfr", **STAGE_META["hlfr"]})

    all_hlfrs = {}  # br_id -> list of hlfrs
    for i, br_entry in enumerate(business_reqs):
        br_data = br_entry["data"]
        br_id = br_data["br_id"]

        if i >= 2:
            # Pruned — emit placeholder
            yield _event("node_pruned", {
                "stage": "hlfr",
                "id": f"hlfr-pruned-{br_id}",
                "parent_id": br_id,
                "label": f"HLFRs for {br_id}",
                "parent_data": br_data,
            })
            continue

        hlfr_input = json.dumps(br_data)
        
        critic_feedback = ""
        hlfr_prompt_used = ""
        for retry in range(MAX_VALIDATION_RETRIES):
            hlfr_list, hlfr_prompt_used = await _stage_generate(HLFR_PROMPT, hlfr_input, model, context_str=br_entry["source"], critic_feedback=critic_feedback)

            if isinstance(hlfr_list, dict):
                hlfr_list = [hlfr_list]
            elif not isinstance(hlfr_list, list):
                hlfr_list = [{"hlfr_id": f"HLFR-{i+1}.1", "function_name": str(hlfr_list), "description": str(hlfr_list)}]

            # Assign proper IDs
            for j, hlfr in enumerate(hlfr_list):
                hlfr["hlfr_id"] = f"HLFR-{i+1}.{j+1}"
                hlfr["parent_br"] = br_id

            all_passed = True
            feedback_acc = []
            final_nodes = []
            
            for hlfr in hlfr_list:
                source_text = br_data.get("business_rule", "")
                target_text = hlfr.get("description", "") + " " + hlfr.get("expected_behavior", "")
                gate_a, gate_b, passed = await _dual_gate_validate(source_text, target_text, "hlfr", model, gate_stats)
                
                final_nodes.append((hlfr, gate_a, gate_b, passed))
                if not passed:
                    all_passed = False
                    issues = gate_b.get("issues", [])
                    missing = gate_b.get("missing_elements", [])
                    feedback_acc.append(f"Function {hlfr.get('function_name', 'Unnamed')}: Issues: {', '.join(issues)}. Missing: {', '.join(missing)}")
            
            if all_passed:
                break
                
            critic_feedback = "\n".join(feedback_acc)

        all_hlfrs[br_id] = hlfr_list

        for hlfr, gate_a, gate_b, passed in final_nodes:
            yield _event("node_complete", {
                "stage": "hlfr",
                "id": hlfr["hlfr_id"],
                "parent_id": br_id,
                "data": hlfr,
                "gate_a": round(gate_a, 4),
                "gate_b": gate_b,
                "passed": passed,
                "prompt_used": hlfr_prompt_used,
                "label": hlfr.get("function_name", hlfr["hlfr_id"]),
            })

    yield _event("stage_complete", {"stage": "hlfr", "count": sum(len(v) for v in all_hlfrs.values())})

    # ── STAGE 3: LLFRs (first HLFR of first BR only) ────────────
    yield _event("stage_start", {"stage": "llfr", **STAGE_META["llfr"]})

    all_llfrs = []
    first_br_id = business_reqs[0]["data"]["br_id"] if business_reqs else None
    first_br_hlfrs = all_hlfrs.get(first_br_id, [])

    for h_idx, hlfr in enumerate(first_br_hlfrs):
        hlfr_id = hlfr["hlfr_id"]

        if h_idx >= 1:
            # Pruned
            yield _event("node_pruned", {
                "stage": "llfr",
                "id": f"llfr-pruned-{hlfr_id}",
                "parent_id": hlfr_id,
                "label": f"LLFRs for {hlfr_id}",
                "parent_data": hlfr,
            })
            continue

        llfr_input = json.dumps(hlfr)
        
        critic_feedback = ""
        llfr_prompt_used = ""
        for retry in range(MAX_VALIDATION_RETRIES):
            llfr_list, llfr_prompt_used = await _stage_generate(LLFR_PROMPT, llfr_input, model, context_str=br_entry["source"], critic_feedback=critic_feedback)

            if isinstance(llfr_list, dict):
                llfr_list = [llfr_list]
            elif not isinstance(llfr_list, list):
                llfr_list = [{"llfr_id": f"LLFR-{hlfr_id.split('-')[1]}.1", "title": str(llfr_list)}]

            for j, llfr_node in enumerate(llfr_list):
                llfr_node["llfr_id"] = f"LLFR-{hlfr_id.replace('HLFR-', '')}.{j+1}"
                llfr_node["parent_hlfr"] = hlfr_id

            all_passed = True
            feedback_acc = []
            final_nodes = []

            for llfr_node in llfr_list:
                source_text = hlfr.get("description", "") + " " + hlfr.get("expected_behavior", "")
                behaviors = llfr_node.get("detailed_behavior", [])
                target_text = " ".join(behaviors) if isinstance(behaviors, list) else str(behaviors)
                gate_a, gate_b, passed = await _dual_gate_validate(source_text, target_text, "llfr", model, gate_stats)
                
                final_nodes.append((llfr_node, gate_a, gate_b, passed))
                if not passed:
                    all_passed = False
                    issues = gate_b.get("issues", [])
                    missing = gate_b.get("missing_elements", [])
                    feedback_acc.append(f"Title {llfr_node.get('title', 'Unnamed')}: Issues: {', '.join(issues)}. Missing: {', '.join(missing)}")
            
            if all_passed:
                break
                
            critic_feedback = "\n".join(feedback_acc)

        all_llfrs.extend(llfr_list)

        for llfr_node, gate_a, gate_b, passed in final_nodes:
            yield _event("node_complete", {
                "stage": "llfr",
                "id": llfr_node["llfr_id"],
                "parent_id": hlfr_id,
                "data": llfr_node,
                "gate_a": round(gate_a, 4),
                "gate_b": gate_b,
                "passed": passed,
                "prompt_used": llfr_prompt_used,
                "label": llfr_node.get("title", llfr_node["llfr_id"]),
            })

    yield _event("stage_complete", {"stage": "llfr", "count": len(all_llfrs)})

    # Also prune HLFRs from second BR
    if len(business_reqs) > 1:
        second_br_id = business_reqs[1]["data"]["br_id"]
        second_br_hlfrs = all_hlfrs.get(second_br_id, [])
        for hlfr in second_br_hlfrs:
            yield _event("node_pruned", {
                "stage": "llfr",
                "id": f"llfr-pruned-{hlfr['hlfr_id']}",
                "parent_id": hlfr["hlfr_id"],
                "label": f"LLFRs for {hlfr['hlfr_id']}",
                "parent_data": hlfr,
            })

    # ── STAGE 4: TEST REQUIREMENTS (first LLFR → ALL TRs) ───────
    yield _event("stage_start", {"stage": "tr", **STAGE_META["tr"]})

    all_trs = []
    first_llfr = all_llfrs[0] if all_llfrs else None

    # Prune remaining LLFRs
    for llfr in all_llfrs[1:]:
        yield _event("node_pruned", {
            "stage": "tr",
            "id": f"tr-pruned-{llfr['llfr_id']}",
            "parent_id": llfr["llfr_id"],
            "label": f"Test Reqs for {llfr['llfr_id']}",
            "parent_data": llfr,
        })

    if first_llfr:
        tr_input = json.dumps(first_llfr)
        
        critic_feedback = ""
        tr_prompt_used = ""
        for retry in range(MAX_VALIDATION_RETRIES):
            tr_list, tr_prompt_used = await _stage_generate(TEST_REQ_PROMPT, tr_input, model, context_str=business_reqs[0]["source"], critic_feedback=critic_feedback)

            if isinstance(tr_list, dict):
                tr_list = [tr_list]
            elif not isinstance(tr_list, list):
                tr_list = [{"tr_id": "TR-1", "test_objective": str(tr_list)}]

            llfr_id = first_llfr["llfr_id"]
            for j, tr in enumerate(tr_list):
                tr["tr_id"] = f"TR-{llfr_id.replace('LLFR-', '')}.{j+1}"
                tr["parent_llfr"] = llfr_id

            all_passed = True
            feedback_acc = []
            final_nodes = []

            for tr in tr_list:
                behaviors = first_llfr.get("detailed_behavior", [])
                source_text = " ".join(behaviors) if isinstance(behaviors, list) else str(behaviors)
                target_text = tr.get("test_objective", "") + " " + " ".join(tr.get("conditions_to_verify", []))
                gate_a, gate_b, passed = await _dual_gate_validate(source_text, target_text, "tr", model, gate_stats)
                
                final_nodes.append((tr, gate_a, gate_b, passed))
                if not passed:
                    all_passed = False
                    issues = gate_b.get("issues", [])
                    missing = gate_b.get("missing_elements", [])
                    feedback_acc.append(f"Objective {tr.get('test_objective', 'Unnamed')}: Issues: {', '.join(issues)}. Missing: {', '.join(missing)}")

            if all_passed:
                break
                
            critic_feedback = "\n".join(feedback_acc)

        all_trs = tr_list

        for tr, gate_a, gate_b, passed in final_nodes:
            yield _event("node_complete", {
                "stage": "tr",
                "id": tr["tr_id"],
                "parent_id": llfr_id,
                "data": tr,
                "gate_a": round(gate_a, 4),
                "gate_b": gate_b,
                "passed": passed,
                "prompt_used": tr_prompt_used,
                "label": tr.get("test_objective", tr["tr_id"])[:80],
            })

    yield _event("stage_complete", {"stage": "tr", "count": len(all_trs)})

    # ── STAGE 5: TEST CASES (ALL TRs → TCs — PARALLEL) ─────────
    yield _event("stage_start", {"stage": "tc", **STAGE_META["tc"]})

    async def _generate_tc(tr):
        """Generate one TC with retry loop — runs in parallel across all TRs."""
        tc_input = json.dumps(tr)
        tr_id    = tr["tr_id"]
        critic_feedback = ""
        tc_prompt_used  = ""

        for retry in range(MAX_VALIDATION_RETRIES):
            tc_data, tc_prompt_used = await _stage_generate(
                TEST_CASE_PROMPT, tc_input, model,
                context_str=business_reqs[0]["source"],
                critic_feedback=critic_feedback,
            )

            if isinstance(tc_data, list):
                tc_data = tc_data[0] if tc_data else {}
            if not isinstance(tc_data, dict):
                tc_data = {"tc_id": "TC-1", "title": str(tc_data)}

            tc_data["tc_id"]     = f"TC-{tr_id.replace('TR-', '')}.1"
            tc_data["parent_tr"] = tr_id

            source_text = tr.get("test_objective", "") + " " + " ".join(tr.get("expected_results", []))
            steps   = tc_data.get("test_steps", [])
            results = tc_data.get("expected_result", [])
            target_text = (
                " ".join(steps if isinstance(steps, list) else [str(steps)])
                + " "
                + " ".join(results if isinstance(results, list) else [str(results)])
            )
            gate_a, gate_b, passed = await _dual_gate_validate(
                source_text, target_text, "tc", model, gate_stats
            )

            if passed:
                break
            critic_feedback = (
                f"Issues: {', '.join(gate_b.get('issues', []))}\n"
                f"Missing: {', '.join(gate_b.get('missing_elements', []))}"
            )

        return {
            "tc_data": tc_data, "gate_a": gate_a, "gate_b": gate_b,
            "passed": passed, "tr_id": tr_id, "prompt_used": tc_prompt_used,
        }

    tc_tasks   = [_generate_tc(tr) for tr in all_trs]
    tc_results = await asyncio.gather(*tc_tasks, return_exceptions=True)

    all_tcs = []
    for result in tc_results:
        if isinstance(result, Exception):
            logger.error(f"TC generation failed: {result}")
            continue
        all_tcs.append(result["tc_data"])
        yield _event("node_complete", {
            "stage":       "tc",
            "id":          result["tc_data"]["tc_id"],
            "parent_id":   result["tr_id"],
            "data":        result["tc_data"],
            "gate_a":      round(result["gate_a"], 4),
            "gate_b":      result["gate_b"],
            "passed":      result["passed"],
            "prompt_used": result["prompt_used"],
            "label":       result["tc_data"].get("title", result["tc_data"]["tc_id"])[:80],
        })

    yield _event("stage_complete", {"stage": "tc", "count": len(all_tcs)})


    # ── PIPELINE COMPLETE ────────────────────────────────────────
    total_duration = int((time.time() - pipeline_start) * 1000)

    avg_a = sum(gate_stats["scores_a"]) / len(gate_stats["scores_a"]) if gate_stats["scores_a"] else 0
    avg_b = sum(gate_stats["scores_b"]) / len(gate_stats["scores_b"]) if gate_stats["scores_b"] else 0

    yield _event("pipeline_complete", {
        "duration_ms": total_duration,
        "gates_passed": gate_stats["passed"],
        "gates_total": gate_stats["total"],
        "gates_failed": gate_stats["failed"],
        "avg_gate_a": round(avg_a, 4),
        "avg_gate_b": round(avg_b, 1),
        "stats": {
            "atomics": len(atomic_requirements),
            "brs": len(business_reqs),
            "hlfrs": sum(len(v) for v in all_hlfrs.values()),
            "llfrs": len(all_llfrs),
            "trs": len(all_trs),
            "tcs": len(all_tcs),
        }
    })


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

async def _stage_generate(
    prompt: str, 
    input_data: str, 
    model: str, 
    max_retries: int = 2,
    context_str: str = "",
    critic_feedback: str = ""
) -> tuple[dict | list, str]:
    """Call LLM with a stage prompt, parse JSON, retry on failure.
    Uses generate_full (throttled) for parallel-safe execution.
    Returns (parsed_result, compiled_user_prompt) for full audit traceability."""
    
    user_prompt = input_data
    if context_str:
        user_prompt += f"\n\nGLOBAL CONTEXT (Original Requirement):\n{context_str}\n\nMake sure your generated JSON does not contradict the tone, constraints, or ultimate goal of the original requirement above."
    
    if critic_feedback:
        user_prompt += f"\n\nCRITIC FEEDBACK FROM PREVIOUS ATTEMPT:\n{critic_feedback}\n\nYour previous attempt failed the validation gate due to the above issues. Correct them in this retry."

    for attempt in range(max_retries + 1):
        full_text = await llm_client.generate_full(
            model=model,
            system_prompt=prompt,
            user_prompt=user_prompt,
            temperature=0.1 + (0.1 * attempt),
            format="json",
        )

        if "[LLM ERROR:" in full_text or "[GEMINI ERROR:" in full_text:
            raise RuntimeError(f"API Error encountered: {full_text}")

        parsed = _parse_json_output(full_text)
        if parsed is not None:
            return parsed, user_prompt

    # All retries failed — return raw text wrapped
    return {"raw_output": full_text, "parse_error": True}, user_prompt


async def _dual_gate_validate(
    source_text: str,
    target_text: str,
    stage: str,
    model: str,
    gate_stats: dict,
) -> tuple[float, dict, bool]:
    """Run both validation gates and return (gate_a_score, gate_b_result, passed)."""
    # Gate A: Semantic cosine similarity (instant, local)
    gate_a = semantic_validator.calculate_trace_score(source_text, target_text)
    gate_stats["scores_a"].append(gate_a)

    # Gate B: LLM critic (Gemini call using key rotation)
    context = STAGE_CRITIC_CONTEXT.get(stage, "General Requirements Analysis")
    # Use larger windows at deeper stages to prevent truncation-caused failures
    input_limit  = 800 if stage in ("llfr", "tr", "tc") else 600
    output_limit = 1500 if stage in ("tr", "tc") else 1000
    critic_prompt = CRITIC_PROMPT.format(
        stage_context=context,
        input_text=source_text[:input_limit],
        output_text=target_text[:output_limit],
    )
    gate_b = {"score": 5, "issues": ["Critic call failed"], "verdict": "fail"}

    try:
        critic_text = await llm_client.generate_full(
            model=model,
            system_prompt="You are a strict validation critic. Return ONLY valid JSON.",
            user_prompt=critic_prompt,
            temperature=0.0,
            format="json",
        )

        if "[LLM ERROR:" in critic_text or "[GEMINI ERROR:" in critic_text:
            raise RuntimeError(f"API Error encountered: {critic_text}")

        parsed = _parse_json_output(critic_text)
        if parsed and isinstance(parsed, dict) and "score" in parsed:
            gate_b = parsed
    except Exception:
        pass

    gate_b_score = gate_b.get("score", 0)
    gate_stats["scores_b"].append(gate_b_score)
    gate_stats["total"] += 1

    threshold_a = GATE_A_THRESHOLDS.get(stage, 0.50)
    threshold_b = GATE_B_THRESHOLDS.get(stage, GATE_B_THRESHOLD)
    passed = gate_a >= threshold_a and gate_b_score >= threshold_b

    if passed:
        gate_stats["passed"] += 1
    else:
        gate_stats["failed"] += 1

    return gate_a, gate_b, passed


async def expand_pruned_node(parent_data: dict, stage: str, model: str = "gemini-2.5-flash") -> AsyncGenerator[dict, None]:
    """On-demand expansion: generate children for a pruned node."""
    prompt_map = {
        "hlfr": HLFR_PROMPT,
        "llfr": LLFR_PROMPT,
        "tr": TEST_REQ_PROMPT,
        "tc": TEST_CASE_PROMPT,
    }
    prompt = prompt_map.get(stage)
    if not prompt:
        yield _event("error", {"message": f"Unknown stage: {stage}"})
        return

    input_data = json.dumps(parent_data)
    # expand_pruned_node: _stage_generate now returns (result, prompt_used) tuple
    result, _ = await _stage_generate(prompt, input_data, model)

    if isinstance(result, dict):
        result = [result]
    elif not isinstance(result, list):
        result = [{"data": str(result)}]

    for item in result:
        yield _event("node_complete", {
            "stage": stage,
            "id": await _next_id(stage.upper()),
            "data": item,
            "gate_a": 0,
            "gate_b": {"score": 0, "verdict": "pending"},
            "passed": True,
            "label": str(item.get("title", item.get("function_name", item.get("test_objective", ""))))[:80],
        })


def _parse_json_output(text: str) -> dict | list | None:
    """Parse JSON from LLM output, handling various wrapper formats."""
    text = text.strip()
    # Strip <think> blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Strip markdown code fences
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    text = text.strip()

    # Try direct parse
    try:
        result = json.loads(text)
        return result
    except json.JSONDecodeError:
        pass

    # Try extracting array
    match = re.search(r'\[[\s\S]*\]', text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Try extracting object
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _parse_requirements(text: str) -> list[str]:
    """Parse a JSON array of requirements from preprocessor output."""
    text = text.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)

    try:
        result = json.loads(text)
        if isinstance(result, dict) and "atomic_requirements" in result:
            return [str(r).strip() for r in result["atomic_requirements"] if str(r).strip()]
        elif isinstance(result, list):
            return [str(r).strip() for r in result if str(r).strip()]
    except json.JSONDecodeError:
        pass

    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, dict) and "atomic_requirements" in result:
                return [str(r).strip() for r in result["atomic_requirements"] if str(r).strip()]
        except json.JSONDecodeError:
            pass

    clean_text = text.replace('\n', ' ').strip()
    return [clean_text] if clean_text else []


def _event(event_type: str, data: dict) -> dict:
    """Create a standardized SSE event dict."""
    return {"event": event_type, "data": data}
