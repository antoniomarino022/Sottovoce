"""Guardrails and safety validation filters for input, triage, and agent outputs."""

import re
from typing import Literal

from src.agents.state import ModerationStateStatus, TriageResult

AgentName = Literal["judge", "defense", "prosecution"]

# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

MIN_INPUT_LENGTH = 10
MAX_INPUT_LENGTH = 2000

# Violations that make the input invalid. PII violations are only reported.
BLOCKING_VIOLATIONS = frozenset(
    {"content_too_short", "content_too_long", "prompt_injection_detected"}
)

PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"(system\s+prompt|developer\s+mode|jailbreak)", re.IGNORECASE),
    re.compile(r"(disregard|override)\s+(rules|guidelines|safety)", re.IGNORECASE),
    re.compile(r"reveal\s+(api\s*key|secret|system)", re.IGNORECASE),
]

PII_PATTERNS = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("italian_phone", re.compile(r"\b(?:\+?39)?\s*3\d{2}\s*\d{6,7}\b")),
    ("credit_card", re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")),
    (
        "italian_codice_fiscale",
        re.compile(
            r"\b[A-Z]{6}\d{2}[A-EHLMPR-T][0-9LMNP-V]{2}[A-Z][0-9LMNP-V]{3}[A-Z]\b",
            re.IGNORECASE,
        ),
    ),
]


def _matches_any(patterns: list[re.Pattern[str]], text: str) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _detect_pii(text: str) -> list[str]:
    """Return the names of all PII types found in the text."""
    return [name for name, pattern in PII_PATTERNS if pattern.search(text)]


def validate_input_guardrails(content: str) -> tuple[bool, str, list[str]]:
    """Validate incoming confession: length, prompt injection, explicit PII."""
    text = content.strip()
    violations: list[str] = []

    if len(text) < MIN_INPUT_LENGTH:
        violations.append("content_too_short")
    if len(text) > MAX_INPUT_LENGTH:
        violations.append("content_too_long")
    if _matches_any(PROMPT_INJECTION_PATTERNS, text):
        violations.append("prompt_injection_detected")

    violations.extend(f"pii_detected_{name}" for name in _detect_pii(text))

    is_valid = BLOCKING_VIOLATIONS.isdisjoint(violations)
    reason = ", ".join(violations) or "input_valid"
    return is_valid, reason, violations


# ---------------------------------------------------------------------------
# Triage enforcement
# ---------------------------------------------------------------------------

CRISIS_SEVERITY_THRESHOLD = 10
HIGH_SEVERITY_THRESHOLD = 8


def enforce_triage_guardrails(
    triage_result: TriageResult,
) -> tuple[TriageResult, ModerationStateStatus, list[str]]:
    """Enforce deterministic safety invariants over LLM triage classifications."""
    severity = triage_result.severity
    roast_allowed = triage_result.roast_allowed

    status: ModerationStateStatus
    violation: str | None = None

    if severity >= CRISIS_SEVERITY_THRESHOLD:
        severity = 10
        roast_allowed = False
        status = "crisis_held"
        violation = "enforced_crisis_held_for_high_severity"

    elif severity >= HIGH_SEVERITY_THRESHOLD:
        roast_allowed = False
        status = "rejected"
        violation = "enforced_rejection_for_high_severity"

    elif not roast_allowed:
        status = "rejected"
        violation = "enforced_rejection_for_disallowed_roast"

    else:
        status = "approved"

    enforced_result = TriageResult(
        severity=severity,
        roast_allowed=roast_allowed,
        reason=triage_result.reason,
        ai_roast=triage_result.ai_roast if (roast_allowed and status == "approved") else None,
    )
    return enforced_result, status, [violation] if violation else []


# ---------------------------------------------------------------------------
# Agent output validation
# ---------------------------------------------------------------------------

PROHIBITED_OUTPUT_THEMES = [
    re.compile(r"\b(suicid\w*|uccid\w*|tagliati|ammazz\w*)\b", re.IGNORECASE),
    re.compile(r"\b(negro|frocio|handicappat\w*|mongoloid\w*|ritardat\w*)\b", re.IGNORECASE),
]

DEFAULT_FALLBACK = "Intervento ritirato d'ufficio per violazione dei termini della corte satirica."

FALLBACK_RESPONSES: dict[str, str] = {
    "judge": (
        "La Suprema Corte sospende temporaneamente la sentenza per eccesso verbale contrario "
        "al codice satirico: l'imputato resta comunque diffidato dal ripetere l'insano gesto."
    ),
    "defense": (
        "L'Avvocato della Difesa ritira l'arringa per un improvviso cavillo deontologico, "
        "ribadendo comunque la presunzione di innocenza universale del cliente."
    ),
    "prosecution": (
        "Il Pubblico Ministero viene richiamato all'ordine dal collegio per intemperanza procedurale: "
        "la requisitoria è rimandata a giudizio divino."
    ),
}


def validate_agent_output_guardrails(
    agent_name: AgentName,
    text: str,
) -> tuple[bool, str, list[str]]:
    """Check persona output for prohibited themes and PII leaks.

    Returns (is_safe, text_or_fallback, violations).
    """
    violations: list[str] = []

    if _matches_any(PROHIBITED_OUTPUT_THEMES, text):
        violations.append("prohibited_theme_detected")

    violations.extend(f"output_pii_leak_{name}" for name in _detect_pii(text))

    if violations:
        return False, FALLBACK_RESPONSES.get(agent_name, DEFAULT_FALLBACK), violations

    return True, text, violations


__all__ = [
    "DEFAULT_FALLBACK",
    "FALLBACK_RESPONSES",
    "validate_input_guardrails",
    "enforce_triage_guardrails",
    "validate_agent_output_guardrails",
]
