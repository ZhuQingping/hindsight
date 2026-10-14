"""Customer error messages, separate from internal exception diagnostics.

Only error boundaries use this helper. Successful responses and customer memory
or file contents must never pass through a product-name replacement filter.
"""

PUBLIC_INTERNAL_ERROR = "The service could not complete the operation. Contact your service administrator."


def public_error_message(error: object) -> str:
    """Keep useful errors, but do not expose implementation identity or settings."""
    message = str(error)
    if "hindsight" in message.casefold():
        return PUBLIC_INTERNAL_ERROR
    return message
