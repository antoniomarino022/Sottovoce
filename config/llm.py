"""Centralized LLM configurations for the Sottovoce multi-agent pipeline."""

from typing import Any
from langchain_deepseek import ChatDeepSeek

from config.settings import settings

_deepseek_key = settings.DEEPSEEK_API_KEY.get_secret_value() or "sk-not-configured"
_openai_key = settings.OPENAI_API_KEY.get_secret_value()

triage_llm: Any = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0.4,
    timeout=6.0,
    max_retries=1,
    api_key=_deepseek_key,
)

_base_creative = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0.8,
    timeout=10.0,
    max_retries=1,
    api_key=_deepseek_key,
)

if _openai_key:
    from langchain_openai import ChatOpenAI

    _openai_creative = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.8,
        timeout=10.0,
        max_retries=1,
        api_key=_openai_key,
    )
    creative_llm: Any = _base_creative.with_fallbacks([_openai_creative])
else:
    creative_llm: Any = _base_creative

llm: Any = creative_llm

__all__ = [
    "triage_llm",
    "creative_llm",
    "llm",
]
