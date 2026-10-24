"""Centralized LLM configurations for the Hot-Mic multi-agent pipeline."""

from langchain_deepseek import ChatDeepSeek

from config.settings import settings

triage_llm: ChatDeepSeek = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0.0,
    timeout=6.0,
    max_retries=1,
    api_key=settings.DEEPSEEK_API_KEY.get_secret_value(),
)

creative_llm: ChatDeepSeek = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0.8,
    timeout=10.0,
    max_retries=1,
    api_key=settings.DEEPSEEK_API_KEY.get_secret_value(),
)

llm: ChatDeepSeek = creative_llm

__all__ = [
    "triage_llm",
    "creative_llm",
    "llm",
]
