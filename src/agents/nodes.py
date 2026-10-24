from typing import Any, cast,Optional

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from config.llm import creative_llm, triage_llm
from src.agents.guardrails import (
    DEFAULT_FALLBACK,
    FALLBACK_RESPONSES,
    AgentName,
    enforce_triage_guardrails,
    validate_agent_output_guardrails,
    validate_input_guardrails,
)
from src.agents.prompts import (
    defense_prompt,
    judge_prompt,
    prosecution_prompt,
    triage_prompt,
)
from src.agents.state import ConfessionState, ModerationStateStatus, TriageResult

NO_DEFENSE_PLACEHOLDER = "Nessuna arringa presentata dalla difesa."


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _existing_violations(state: ConfessionState) -> list[str]:
    return list(state.get("guardrails_triggered") or [])


def _as_text(content: Any) -> str:
    return content if isinstance(content, str) else str(content)


def _triage_update(
    *,
    mod_status: ModerationStateStatus,
    severity: int,
    roast_allowed: bool,
    reason: str,
    violations: list[str],
    message: str,
) -> dict[str, Any]:
    """Build the state update returned by every exit path of the triage node."""
    return {
        "mod_status": mod_status,
        "severity": severity,
        "roast_allowed": roast_allowed,
        "triage_reason": reason,
        "guardrails_triggered": violations,
        "messages": [AIMessage(content=message, name="triage")],
    }


async def _run_persona(
    agent_name: AgentName,
    prompt: ChatPromptTemplate,
    state: ConfessionState,
    output_key: str,
    **prompt_vars: str,
) -> dict[str, Any]:
    """Invoke the creative LLM for a courtroom persona and sanitize its output."""
    try:
        messages = prompt.format_messages(**prompt_vars)
        response = await creative_llm.ainvoke(messages)
        raw_text = _as_text(response.content)
    except Exception:
        raw_text = FALLBACK_RESPONSES.get(agent_name, DEFAULT_FALLBACK)

    _, sanitized_text, output_violations = validate_agent_output_guardrails(
        agent_name, raw_text
    )

    return {
        output_key: sanitized_text,
        "guardrails_triggered": _existing_violations(state) + output_violations,
        "messages": [AIMessage(content=sanitized_text, name=agent_name)],
    }


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------


async def triage_node(state: ConfessionState) -> dict[str, Any]:
    """Safety triage: input validation, LLM classification, fail-closed on errors."""
    content = state.get("content", "")
    existing = _existing_violations(state)

    # Deterministic input validation
    is_valid, validation_reason, input_violations = validate_input_guardrails(content)
    if not is_valid:
        return _triage_update(
            mod_status="rejected",
            severity=10,
            roast_allowed=False,
            reason=f"Input guardrail rejected submission: {validation_reason}",
            violations=existing + input_violations,
            message=f"Input rejected by safety guardrails: {validation_reason}",
        )

    # LLM classification, then deterministic enforcement
    try:
        structured_triage = triage_llm.with_structured_output(TriageResult)
        raw_output: Any = await structured_triage.ainvoke(
            triage_prompt.format_messages(content=content)
        )
        raw_result: TriageResult = (
            TriageResult.model_validate(raw_output)
            if isinstance(raw_output, dict)
            else cast(TriageResult, raw_output)
        )
        result, mod_status, triage_violations = enforce_triage_guardrails(raw_result)

        ai_roast: Optional[str] = None
        output_violations: list[str] = []
        if mod_status == "approved" and result.ai_roast:
            _, sanitized_roast, out_viols = validate_agent_output_guardrails(
                "judge", result.ai_roast
            )
            ai_roast = sanitized_roast
            output_violations = out_viols

        update = _triage_update(
            mod_status=mod_status,
            severity=result.severity,
            roast_allowed=result.roast_allowed,
            reason=result.reason,
            violations=existing + input_violations + triage_violations + output_violations,
            message=(
                f"Triage Decision: status={mod_status}, "
                f"severity={result.severity}, reason={result.reason}"
            ),
        )
        if ai_roast:
            update["ai_roast"] = ai_roast
        return update

    # Fail closed: any triage error blocks the content
    except Exception as exc:
        return _triage_update(
            mod_status="crisis_held",
            severity=10,
            roast_allowed=False,
            reason=f"Fail-closed trigger engaged: LLM classification unavailable ({exc})",
            violations=existing + input_violations + ["fail_closed_error"],
            message="Fail-closed safety trigger engaged.",
        )


# ---------------------------------------------------------------------------
# Courtroom personas
# ---------------------------------------------------------------------------


async def judge_node(state: ConfessionState) -> dict[str, Any]:
    """Deliver the satirical roast. If already generated in single-pass triage, re-use it immediately."""
    if state.get("ai_roast"):
        return {"ai_roast": state.get("ai_roast")}
    if not state.get("roast_allowed", False):
        return {"ai_roast": None}

    return await _run_persona(
        "judge",
        judge_prompt,
        state,
        output_key="ai_roast",
        content=state.get("content", ""),
    )


async def defense_node(state: ConfessionState) -> dict[str, Any]:
    """Courtroom defense, only when the 'ai_lawyer' power is active."""
    if "ai_lawyer" not in (state.get("active_powers") or []):
        return {"ai_defense": None}

    count = int(state.get("escalation_count") or 1)
    if count >= 5:
        instruction = (
            f"Ben {count} cittadini si sono schierati a difesa dell'imputato! "
            "Deposita un ricorso supremo in Cassazione ancora più assurdo, trionfale e spudorato. "
            "Scrivi solo la battuta difensiva, senza prefissi."
        )
    else:
        instruction = "Scrivi solo la tua battuta difensiva, senza prefissi."

    return await _run_persona(
        "defense",
        defense_prompt,
        state,
        output_key="ai_defense",
        content=state.get("content", ""),
        ai_roast=state.get("ai_roast") or "",
        escalation_instruction=instruction,
    )


async def prosecution_node(state: ConfessionState) -> dict[str, Any]:
    """Prosecution requisition, only when the 'ai_prosecutor' power is active."""
    if "ai_prosecutor" not in (state.get("active_powers") or []):
        return {"ai_prosecution": None}

    count = int(state.get("escalation_count") or 1)
    if count >= 10:
        instruction = (
            f"Folla inferocita: {count} cittadini reclamano una condanna esemplare! "
            "Emetti la requisitoria finale da ergastolo popolare più apocalittica e sproporzionata possibile. "
            "Scrivi solo la battuta d'accusa, senza prefissi."
        )
    elif count >= 5:
        instruction = (
            f"Ben {count} cittadini hanno rincarato l'accusa contro l'imputato! "
            "Aggrava la requisitoria chiedendo una pena ancora più spietata e assurda. "
            "Scrivi solo la battuta d'accusa, senza prefissi."
        )
    else:
        instruction = "Scrivi solo la tua battuta d'accusa, senza prefissi."

    return await _run_persona(
        "prosecution",
        prosecution_prompt,
        state,
        output_key="ai_prosecution",
        content=state.get("content", ""),
        ai_roast=state.get("ai_roast") or "",
        ai_defense=state.get("ai_defense") or NO_DEFENSE_PLACEHOLDER,
        escalation_instruction=instruction,
    )


__all__ = [
    "triage_node",
    "judge_node",
    "defense_node",
    "prosecution_node",
]
