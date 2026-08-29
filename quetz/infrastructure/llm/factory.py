"""Factory that builds the underlying LangChain chat model.

Only the infrastructure layer knows about LangChain's concrete model classes
(ChatOllama / ChatOpenAI). The rest of the application depends on the LLM port.
"""
from __future__ import annotations

from quetz import config as q_config


def build_base_chat_model(temperature: float | None = None):
    """Return a concrete LangChain chat model instance for the active MODE.

    ``temperature`` defaults to the configured ``TEMP``. Local (Ollama) models
    also receive ``NUM_CTX`` (context window) and ``NUM_PREDICT`` (max output
    tokens) so they don't hit the default 2K window and exhaust before emitting
    a tool call.
    """
    if temperature is None:
        temperature = q_config.TEMP

    if q_config.MODE == "cloud":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=q_config.MODEL_NAME,
            api_key=q_config.CLOUD_API_KEY,
            base_url=q_config.CLOUD_BASE_URL,
            temperature=temperature,
        )

    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=q_config.MODEL_NAME,
        temperature=temperature,
        num_ctx=q_config.NUM_CTX,
        num_predict=q_config.NUM_PREDICT,
    )
