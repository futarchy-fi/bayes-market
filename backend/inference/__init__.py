"""Stable inference contracts and configuration for the Bayes engine seam."""

from .config import DEFAULT_ENGINE_CONFIG, EngineConfig
from .contracts import (
    AtomicEventQueryResult,
    CliqueSummary,
    CompileResult,
    InferenceCompiler,
    InferenceQueryBackend,
    MarginalQueryResult,
)
from .errors import (
    InferenceCompileError,
    InferenceError,
    InferenceQueryError,
    InferenceUnsupportedQueryError,
)

__all__ = [
    "AtomicEventQueryResult",
    "CliqueSummary",
    "CompileResult",
    "DEFAULT_ENGINE_CONFIG",
    "EngineConfig",
    "InferenceCompileError",
    "InferenceCompiler",
    "InferenceError",
    "InferenceQueryBackend",
    "InferenceQueryError",
    "InferenceUnsupportedQueryError",
    "MarginalQueryResult",
]

