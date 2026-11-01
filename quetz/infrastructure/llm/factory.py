"""Factory that builds planner and executor chat models.

Only the infrastructure layer knows about LangChain's concrete model classes
(ChatOllama / ChatOpenAI). The planner is typically cloud-hosted; the executor
is the local stateless model, optionally constrained by a JSON schema.
"""
from __future__ import annotations

from quetz import config as q_config
from quetz.application.prompts.executor import EDIT_PLAN_SCHEMA


def build_chat_model(
    role: str = "executor",
    *,
    structured: bool | dict = False,
    temperature: float | None = None,
):
    """Return a concrete LangChain chat model for ``role``.

    ``structured`` asks local Ollama models to constrain output to the edit-plan
    JSON schema. The executor defaults to local; the planner falls back to the
    legacy cloud configuration.
    """
    if temperature is None:
        temperature = q_config.TEMP

    if role == "planner":
        mode = q_config.PLANNER_MODE
        model = q_config.PLANNER_MODEL
        api_key = q_config.PLANNER_API_KEY
        base_url = q_config.PLANNER_BASE_URL
        num_ctx = q_config.PLANNER_NUM_CTX
        num_predict = q_config.PLANNER_NUM_PREDICT
    else:
        mode = q_config.EXECUTOR_MODE
        model = q_config.EXECUTOR_MODEL
        api_key = q_config.CLOUD_API_KEY
        base_url = q_config.CLOUD_BASE_URL
        num_ctx = q_config.EXECUTOR_NUM_CTX
        num_predict = q_config.EXECUTOR_NUM_PREDICT

    if mode == "cloud":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
        )

    from langchain_ollama import ChatOllama

    kwargs = {
        "model": model,
        "temperature": temperature,
        "num_ctx": num_ctx,
        "num_predict": num_predict,
    }
    if structured:
        kwargs["format"] = EDIT_PLAN_SCHEMA if structured is True else structured
    return ChatOllama(**kwargs)


def build_base_chat_model(temperature: float | None = None):
    """Backwards-compatible alias for the executor model."""
    return build_chat_model("executor", temperature=temperature)
