"""Centralized LLM configurations for the Sottovoce multi-agent pipeline."""

from langchain_deepseek import ChatDeepSeek

from config.settings import settings

_deepseek_key = settings.DEEPSEEK_API_KEY.get_secret_value() or "sk-not-configured"

triage_llm: ChatDeepSeek = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0.4,
    timeout=6.0,
    max_retries=1,
    api_key=_deepseek_key,
)

creative_llm: ChatDeepSeek = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0.8,
    timeout=10.0,
    max_retries=1,
    api_key=_deepseek_key,
)

llm: ChatDeepSeek = creative_llm

__all__ = [
    "triage_llm",
    "creative_llm",
    "llm",
]
