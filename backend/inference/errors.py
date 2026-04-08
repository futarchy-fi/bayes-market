"""Inference-specific exceptions kept behind the server's HTTP contract layer."""

from __future__ import annotations

from typing import Any, Mapping


class InferenceError(Exception):
    default_code = "inference_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: Mapping[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code or self.default_code
        self.message = message
        self.details = dict(details or {})


class InferenceCompileError(InferenceError):
    default_code = "inference_compile_error"


class InferenceQueryError(InferenceError):
    default_code = "inference_query_error"


class InferenceUnsupportedQueryError(InferenceQueryError):
    default_code = "inference_unsupported_query"


__all__ = [
    "InferenceCompileError",
    "InferenceError",
    "InferenceQueryError",
    "InferenceUnsupportedQueryError",
]

