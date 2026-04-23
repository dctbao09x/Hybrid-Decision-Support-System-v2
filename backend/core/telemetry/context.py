import os
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)

prompt_id_var: ContextVar[Optional[str]] = ContextVar("prompt_id", default=None)
prompt_version_var: ContextVar[Optional[str]] = ContextVar("prompt_version", default=None)
prompt_hash_var: ContextVar[Optional[str]] = ContextVar("prompt_hash", default=None)

model_id_var: ContextVar[Optional[str]] = ContextVar("model_id", default=None)
model_version_var: ContextVar[Optional[str]] = ContextVar("model_version", default=None)

schema_version_var: ContextVar[Optional[str]] = ContextVar("schema_version", default=None)
ruleset_version_var: ContextVar[Optional[str]] = ContextVar("ruleset_version", default=None)
scoring_version_var: ContextVar[Optional[str]] = ContextVar("scoring_version", default=None)
dataset_version_var: ContextVar[Optional[str]] = ContextVar("dataset_version", default=None)


@dataclass(frozen=True)
class RequestContext:
    request_id: Optional[str]
    correlation_id: Optional[str]


@dataclass(frozen=True)
class PromptContext:
    prompt_id: Optional[str]
    prompt_version: Optional[str]
    prompt_hash: Optional[str]
    model_id: Optional[str]
    model_version: Optional[str]
    schema_version: Optional[str]
    ruleset_version: Optional[str]
    scoring_version: Optional[str]
    dataset_version: Optional[str]


def set_request_context(request_id: Optional[str], correlation_id: Optional[str]) -> None:
    if request_id is not None:
        request_id_var.set(request_id)
    if correlation_id is not None:
        correlation_id_var.set(correlation_id)


def get_request_context() -> RequestContext:
    return RequestContext(request_id_var.get(), correlation_id_var.get())


def set_prompt_context(
    *,
    prompt_id: Optional[str] = None,
    prompt_version: Optional[str] = None,
    prompt_hash: Optional[str] = None,
    model_id: Optional[str] = None,
    model_version: Optional[str] = None,
    schema_version: Optional[str] = None,
    ruleset_version: Optional[str] = None,
    scoring_version: Optional[str] = None,
    dataset_version: Optional[str] = None,
) -> None:
    if prompt_id is not None:
        prompt_id_var.set(prompt_id)
    if prompt_version is not None:
        prompt_version_var.set(prompt_version)
    if prompt_hash is not None:
        prompt_hash_var.set(prompt_hash)
    if model_id is not None:
        model_id_var.set(model_id)
    if model_version is not None:
        model_version_var.set(model_version)
    if schema_version is not None:
        schema_version_var.set(schema_version)
    if ruleset_version is not None:
        ruleset_version_var.set(ruleset_version)
    if scoring_version is not None:
        scoring_version_var.set(scoring_version)
    if dataset_version is not None:
        dataset_version_var.set(dataset_version)


def get_prompt_context() -> PromptContext:
    return PromptContext(
        prompt_id=prompt_id_var.get() or os.getenv("PROMPT_ID"),
        prompt_version=prompt_version_var.get() or os.getenv("PROMPT_VERSION"),
        prompt_hash=prompt_hash_var.get() or os.getenv("PROMPT_HASH"),
        model_id=model_id_var.get() or os.getenv("MODEL_ID"),
        model_version=model_version_var.get() or os.getenv("MODEL_VERSION"),
        schema_version=schema_version_var.get() or os.getenv("SCHEMA_VERSION"),
        ruleset_version=ruleset_version_var.get() or os.getenv("RULESET_VERSION"),
        scoring_version=scoring_version_var.get() or os.getenv("SCORING_VERSION"),
        dataset_version=(
            dataset_version_var.get()
            or os.getenv("DATASET_VERSION")
            or os.getenv("MARKET_DATASET_VERSION")
        ),
    )
