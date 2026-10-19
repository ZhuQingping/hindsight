"""ContextBase-Vapi: Persistent memory for Vapi voice AI calls.

Provides a webhook handler that adds ContextBase long-term memory to Vapi
voice calls — recalling relevant context at call start and retaining the
transcript when the call ends.

Basic usage::

    from fastapi import FastAPI, Request
    from contextbase_vapi import ContextBaseVapiWebhook

    app = FastAPI()
    memory = ContextBaseVapiWebhook(
        bank_id="user-123",
        contextbase_api_url="http://localhost:8888",
    )

    @app.post("/webhook")
    async def vapi_webhook(request: Request):
        event = await request.json()
        response = await memory.handle(event)
        return response or {}
"""

from .config import (
    ContextBaseVapiConfig,
    configure,
    get_config,
    reset_config,
)
from .errors import ContextBaseVapiError
from .webhook import ContextBaseVapiWebhook

__version__ = "0.1.0"

__all__ = [
    "configure",
    "get_config",
    "reset_config",
    "ContextBaseVapiConfig",
    "ContextBaseVapiError",
    "ContextBaseVapiWebhook",
]
