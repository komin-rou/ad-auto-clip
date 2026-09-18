"""Shared domain errors used across pipeline and batch orchestration."""


class TransientPipelineError(RuntimeError):
    """An operation failed for a temporary reason and is safe to retry."""
