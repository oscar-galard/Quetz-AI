"""Factory that builds the underlying LangChain chat model.

Only the infrastructure layer knows about LangChain's concrete model classes
(ChatOllama / ChatOpenAI). The rest of the application depends on the LLM port.
"""
from __future__ import annotations

from quetz import config as q_config


def build_base_chat_model(temperature: float = 0.0):
    """Return a concrete LangChain chat model instance for the active MODE."""
    if q_config.MODE == "cloud":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=q_config.MODEL_NAME,
            api_key=q_config.CLOUD_API_KEY,
            base_url=q_config.CLOUD_BASE_URL,
            temperature=temperature,
        )

    from langchain_ollama import ChatOllama

    return ChatOllama(model=q_config.MODEL_NAME, temperature=temperature)
