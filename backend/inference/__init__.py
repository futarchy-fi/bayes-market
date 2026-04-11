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
from .current_model import (
    CURRENT_MODEL_COMPILER,
    CURRENT_MODEL_QUERY_BACKEND,
    CURRENT_MODEL_EXACT_ELIGIBILITY_REASON,
    CurrentModelCompileArtifact,
    CurrentModelCompiler,
    CurrentModelQueryBackend,
    canonical_json_hash,
    compile_current_market_artifact,
    compile_current_market_result,
    compile_current_model_artifact,
    compile_current_model_result,
)
from .cache import (
    COMPILE_RESULT_CACHE,
    CacheStats,
    CompileResultCache,
)
from .errors import (
    InferenceCompileError,
    InferenceError,
    InferenceQueryError,
    InferenceUnsupportedQueryError,
)

__all__ = [
    "AtomicEventQueryResult",
    "COMPILE_RESULT_CACHE",
    "CacheStats",
    "CompileResultCache",
    "CURRENT_MODEL_COMPILER",
    "CURRENT_MODEL_QUERY_BACKEND",
    "CURRENT_MODEL_EXACT_ELIGIBILITY_REASON",
    "CliqueSummary",
    "CompileResult",
    "CurrentModelCompileArtifact",
    "CurrentModelCompiler",
    "CurrentModelQueryBackend",
    "DEFAULT_ENGINE_CONFIG",
    "EngineConfig",
    "InferenceCompileError",
    "InferenceCompiler",
    "InferenceError",
    "InferenceQueryBackend",
    "InferenceQueryError",
    "InferenceUnsupportedQueryError",
    "MarginalQueryResult",
    "canonical_json_hash",
    "compile_current_market_artifact",
    "compile_current_market_result",
    "compile_current_model_artifact",
    "compile_current_model_result",
]
