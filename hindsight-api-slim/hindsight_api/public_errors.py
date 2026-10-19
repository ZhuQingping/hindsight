"""Customer error boundaries, independent of internal exception diagnostics."""

PUBLIC_INTERNAL_ERROR = "The service could not complete the operation. Contact your service administrator."


def public_error_message(error: BaseException) -> str:
    """Expose explicit client rejections; unknown failures stay in server logs.

    ValueError is deliberately not allowlisted: some operations use it for caller
    input, others raise it for internal bugs. Those boundaries must decide locally.
    Classify before converting an exception to a string or persisting a task error.
    """
    # Lazy imports avoid coupling module initialization to the engine/extension graph.
    from .engine.memory_engine import RetainOperationConflictError, VisionNotSupportedError
    from .engine.providers.none_llm import LLMNotAvailableError
    from .engine.retain.attachment_content import ContentValidationError
    from .extensions import AuthenticationError, OperationValidationError

    if isinstance(
        error,
        (
            AuthenticationError,
            OperationValidationError,
            LLMNotAvailableError,
            RetainOperationConflictError,
            VisionNotSupportedError,
            ContentValidationError,
        ),
    ):
        return str(error)
    return PUBLIC_INTERNAL_ERROR
