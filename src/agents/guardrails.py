"""Guardrails and safety validation filters for input, triage, and agent outputs."""

import re
from typing import Literal

from src.agents.state import ModerationStateStatus, TriageResult

AgentName = Literal["judge", "defense", "prosecution"]

# ---------------------------------------------------------------------------
# Input validation & multi-country / multilingual security patterns
# ---------------------------------------------------------------------------

MIN_INPUT_LENGTH = 10
MAX_INPUT_LENGTH = 2000

# Violations that make the input invalid (length, prompt injection, or any detected PII).
BLOCKING_VIOLATIONS = frozenset(
    {"content_too_short", "content_too_long", "prompt_injection_detected"}
)

# Multilingual prompt injection & jailbreak patterns (EN, IT, ES, FR, DE, PT + structural tags)
PROMPT_INJECTION_PATTERNS = [
    # English
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts|rules)", re.IGNORECASE),
    re.compile(r"(system\s+prompt|developer\s+mode|jailbreak|do\s+anything\s+now|\bDAN\b)", re.IGNORECASE),
    re.compile(r"(disregard|override|bypass|forget)\s+(all\s+)?(rules|guidelines|safety|instructions|previous)", re.IGNORECASE),
    re.compile(r"reveal\s+(your\s+)?(api\s*key|secret|system|instructions|prompt)", re.IGNORECASE),
    # Italian
    re.compile(r"(ignora|dimentica|disattiva|aggira|sovrascrivi)\s+(tutte\s+)?(le\s+)?(istruzioni|regole|direttive|linee\s+guida|precedenti)", re.IGNORECASE),
    re.compile(r"(prompt\s+di\s+sistema|modalit[àa]\s+sviluppatore|rivela\s+(il\s+prompt|le\s+istruzioni|la\s+chiave))", re.IGNORECASE),
    # Spanish
    re.compile(r"(ignora|olvida|omite|anula)\s+(todas\s+)?(las\s+)?(instrucciones|reglas|directrices)\s*(anteriores|previas)?", re.IGNORECASE),
    re.compile(r"(modo\s+desarrollador|prompt\s+del?\s+sistema|revela\s+(el\s+prompt|las\s+instrucciones))", re.IGNORECASE),
    # French
    re.compile(r"(ignore[rz]?|oublie[rz]?|contourne[rz]?)\s+(toutes\s+)?(les\s+)?(instructions|r[èe]gles|consignes)\s*(pr[ée]c[ée]dentes)?", re.IGNORECASE),
    re.compile(r"(mode\s+d[ée]veloppeur|prompt\s+syst[èe]me)", re.IGNORECASE),
    # German
    re.compile(r"(ignoriere|vergiss|umgehe)\s+(alle\s+)?(vorherigen\s+|bisherigen\s+)?(anweisungen|regeln|instruktionen)", re.IGNORECASE),
    re.compile(r"(entwicklermodus|system[-\s]?prompt)", re.IGNORECASE),
    # Portuguese
    re.compile(r"(ignore|esque[çc]a|desconsidere)\s+(todas\s+)?(as\s+)?(instru[çc][õo]es|regras)\s*(anteriores|pr[ée]vias)?", re.IGNORECASE),
    # Role/delimiter hijacking attempts (XML/ChatML/System tag breakouts)
    re.compile(r"<\s*/?\s*(system|confessione|battuta_del_giudice|battuta_della_difesa|instruction|prompt)\s*>", re.IGNORECASE),
    re.compile(r"(\[SYSTEM\]|\[INST\]|<\|im_start\|>|<\|system\|>)", re.IGNORECASE),
]

# Multi-country & international PII patterns
PII_PATTERNS = [
    # Universal: Email & Payment Cards & IPv4
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("credit_card", re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")),
    # International IBAN (ISO 13616: IT, DE, FR, ES, GB, CH, NL, etc.)
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}[-\s]?(?:[A-Z0-9]{4}[-\s]?){2,7}[A-Z0-9]{1,4}\b")),
    # International & multi-country phone numbers:
    # - E.164 with country code (+39, +1, +44, +33, +49, +34, +41, etc.)
    # - Italian mobile (3xx xxxxxxx)
    # - US/CA NANP ((xxx) xxx-xxxx or xxx-xxx-xxxx)
    (
        "phone_number",
        re.compile(
            r"(?:\+\d{1,3}[-\s.]?\(?\d{1,4}\)?[-\s.]?\d{2,4}[-\s.]?\d{2,4}[-\s.]?\d{0,4}\b"
            r"|\b(?:\+?39)?\s*3\d{2}[\s.-]*\d{6,7}\b"
            r"|\b\(\d{3}\)\s*\d{3}[-\s.]\d{4}\b)"
        ),
    ),
    # Italy: Codice Fiscale
    (
        "italian_codice_fiscale",
        re.compile(
            r"\b[A-Z]{6}\d{2}[A-EHLMPR-T][0-9LMNP-V]{2}[A-Z][0-9LMNP-V]{3}[A-Z]\b",
            re.IGNORECASE,
        ),
    ),
    # US: Social Security Number (SSN)
    ("us_ssn", re.compile(r"\b(?!000|666|9\d{2})\d{3}[-\s](?!00)\d{2}[-\s](?!0000)\d{4}\b")),
    # UK: National Insurance Number (NINO)
    ("uk_nino", re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b", re.IGNORECASE)),
    # Spain: DNI / NIE
    ("es_dni_nie", re.compile(r"\b(?:[XYZ]\d{7}|\d{8})[-\s]?[A-Z]\b", re.IGNORECASE)),
]

_XML_TAG_ESCAPE_RE = re.compile(
    r"<\s*(/?)\s*(confessione|battuta_del_giudice|battuta_della_difesa|system|instruction|prompt)\s*>",
    re.IGNORECASE,
)


def _matches_any(patterns: list[re.Pattern[str]], text: str) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _detect_pii(text: str) -> list[str]:
    """Return the names of all PII types found in the text."""
    return [name for name, pattern in PII_PATTERNS if pattern.search(text)]


def redact_pii(text: str) -> str:
    """Replace any detected PII in the text with [REDACTED] so it never leaks to external LLMs."""
    redacted = text
    for name, pattern in PII_PATTERNS:
        redacted = pattern.sub(f"[REDACTED_{name.upper()}]", redacted)
    return redacted


def sanitize_prompt_input(text: str) -> str:
    """Neutralize XML/structural delimiter tags and redact PII before formatting LLM prompts."""
    escaped = _XML_TAG_ESCAPE_RE.sub(r"[\1\2]", text)
    return redact_pii(escaped)


def validate_input_guardrails(content: str) -> tuple[bool, str, list[str]]:
    """Validate incoming confession: length, multilingual prompt injection, and multi-country PII."""
    text = content.strip()
    violations: list[str] = []

    if len(text) < MIN_INPUT_LENGTH:
        violations.append("content_too_short")
    if len(text) > MAX_INPUT_LENGTH:
        violations.append("content_too_long")
    if _matches_any(PROMPT_INJECTION_PATTERNS, text):
        violations.append("prompt_injection_detected")

    pii_found = [f"pii_detected_{name}" for name in _detect_pii(text)]
    violations.extend(pii_found)

    # Block on length, prompt injection, OR any explicit PII to prevent doxxing & external LLM leaks
    is_valid = BLOCKING_VIOLATIONS.isdisjoint(violations) and not pii_found
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
# Agent output validation (Multilingual self-harm & hate speech)
# ---------------------------------------------------------------------------

PROHIBITED_OUTPUT_THEMES = [
    # Self-harm / suicide incitement (IT, EN, ES, FR, DE)
    re.compile(
        r"\b(suicid\w*|uccid\w*|tagliati|ammazz\w*|impiccat\w*|"
        r"kill\s+yourself|kys|end\s+your\s+life|"
        r"suic[íi]date|m[áa]tate|"
        r"suicide[-\s]?toi|tue[-\s]?toi|"
        r"bring\s+dich\s+um)\b",
        re.IGNORECASE,
    ),
    # Hate speech / slurs (IT, EN, ES, FR)
    re.compile(
        r"\b(negro|nigger|nigga|frocio|faggot|maric[óo]n|p[ée]d[ée]|"
        r"handicappat\w*|mongoloid\w*|ritardat\w*|retard\w*)\b",
        re.IGNORECASE,
    ),
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
    "redact_pii",
    "sanitize_prompt_input",
    "validate_input_guardrails",
    "enforce_triage_guardrails",
    "validate_agent_output_guardrails",
]
